"""Управление списком гридов Space Engineers.

Модуль предоставляет класс :class:`Grids`, который следит за ключами Redis
``se:<owner>:grids`` и ``se:<owner>:grid:<grid_id>:gridinfo``.  Он автоматически
обновляет состояние при появлении новых гридов, изменении уже существующих и
удалении устаревших.  Пользователь может подписываться на события «добавлен»
``(added)``, «обновлён`` (``updated``) и «удалён`` (``removed``).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from .redis_client import RedisEventClient

GridCallback = Callable[["GridState"], None]
GridRemovedCallback = Callable[["GridState"], None]


@dataclass
class GridState:
    """Снимок состояния одного грида."""

    owner_id: str
    grid_id: str
    descriptor: Dict[str, Any] = field(default_factory=dict)
    info: Dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "GridState":
        """Создать копию состояния, независимую от оригинала."""

        return GridState(
            owner_id=self.owner_id,
            grid_id=self.grid_id,
            descriptor=dict(self.descriptor),
            info=dict(self.info),
        )

    @property
    def name(self) -> Optional[str]:
        """Наиболее подходящее имя грида."""

        for source in (self.info, self.descriptor):
            if not isinstance(source, dict):
                continue
            for key in ("name", "gridName", "displayName", "DisplayName"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        fallback = self.descriptor.get("id") or self.info.get("id")
        if fallback is not None:
            return f"Grid_{fallback}"
        return None


class Grids:
    """Отслеживает гриды игрока и генерирует события при изменениях."""

    def __init__(
        self,
        redis: RedisEventClient,
        owner_id: str,
        player_id: Optional[str] = None,
    ) -> None:
        self.redis = redis
        self.owner_id = str(owner_id)
        self.player_id = str(player_id or owner_id)
        self.grids_key = f"se:{self.owner_id}:grids"
        self._lock = threading.RLock()
        self._states: Dict[str, GridState] = {}
        self._descriptor_cache: Dict[str, Dict[str, Any]] = {}
        self._grid_subscriptions: Dict[str, Any] = {}
        self._on_added: List[GridCallback] = []
        self._on_updated: List[GridCallback] = []
        self._on_removed: List[GridRemovedCallback] = []

        self._grids_subscription = self.redis.subscribe_to_key(
            self.grids_key, self._on_grids_change
        )

        initial_payload = self.redis.get_json(self.grids_key)
        if initial_payload is not None:
            self._process_grids_payload(initial_payload)

    # ------------------------------------------------------------------
    # Подписки на события
    # ------------------------------------------------------------------
    def on_added(self, callback: GridCallback) -> None:
        """Подписаться на появление нового грида."""

        with self._lock:
            self._on_added.append(callback)

    def on_updated(self, callback: GridCallback) -> None:
        """Подписаться на изменения существующего грида."""

        with self._lock:
            self._on_updated.append(callback)

    def on_removed(self, callback: GridRemovedCallback) -> None:
        """Подписаться на удаление грида."""

        with self._lock:
            self._on_removed.append(callback)

    # ------------------------------------------------------------------
    def list(self) -> List[GridState]:
        """Текущий снимок всех известных гридов."""

        with self._lock:
            return [state.clone() for state in self._states.values()]

    # ------------------------------------------------------------------
    def close(self) -> None:
        """Отменить все подписки."""

        with self._lock:
            for sub in list(self._grid_subscriptions.values()):
                try:
                    sub.close()
                except Exception:
                    pass
            self._grid_subscriptions.clear()

            try:
                self._grids_subscription.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Обработка событий Redis
    # ------------------------------------------------------------------
    def _on_grids_change(self, key: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            # Ключ удалён — очистим все гриды.
            with self._lock:
                states = list(self._states.values())
                self._states.clear()
                descriptor_ids = list(self._descriptor_cache)
                self._descriptor_cache.clear()
            for state in states:
                self._detach_grid(state.grid_id)
                self._emit_removed(state)
            return

        self._process_grids_payload(payload)

    def _process_grids_payload(self, payload: Any) -> None:
        grids = self._extract_grids(payload)
        to_attach: List[GridState] = []
        to_update: List[GridState] = []
        to_remove: List[GridState] = []
        to_detach: List[str] = []

        with self._lock:
            seen_ids = set()
            for descriptor in grids:
                grid_id = self._extract_grid_id(descriptor)
                if grid_id is None:
                    continue
                seen_ids.add(grid_id)
                descriptor_copy = dict(descriptor)
                state = self._states.get(grid_id)
                if state is None:
                    state = GridState(self.owner_id, grid_id, descriptor_copy, {})
                    self._states[grid_id] = state
                    self._descriptor_cache[grid_id] = descriptor_copy
                    to_attach.append(state)
                else:
                    previous_descriptor = self._descriptor_cache.get(grid_id, {})
                    if descriptor_copy != previous_descriptor:
                        state.descriptor = descriptor_copy
                        self._descriptor_cache[grid_id] = descriptor_copy
                        to_update.append(state.clone())

            removed_ids = [grid_id for grid_id in list(self._states) if grid_id not in seen_ids]
            for grid_id in removed_ids:
                state = self._states.pop(grid_id)
                self._descriptor_cache.pop(grid_id, None)
                to_remove.append(state)
                to_detach.append(grid_id)

        for state in to_attach:
            self._attach_grid(state.grid_id, state)

        for state in to_update:
            self._emit_updated(state)

        for grid_id in to_detach:
            self._detach_grid(grid_id)

        for state in to_remove:
            self._emit_removed(state)

    def _attach_grid(self, grid_id: str, state: GridState) -> None:
        grid_key = self._grid_key(grid_id)
        info_payload = self.redis.get_json(grid_key)
        if isinstance(info_payload, dict):
            with self._lock:
                state.info = dict(info_payload)
        subscription = self.redis.subscribe_to_key(
            grid_key, lambda key, payload, event, gid=grid_id: self._on_grid_info_change(gid, payload, event)
        )
        with self._lock:
            self._grid_subscriptions[grid_id] = subscription
            snapshot = state.clone()
        self._emit_added(snapshot)

    def _detach_grid(self, grid_id: str) -> None:
        subscription = self._grid_subscriptions.pop(grid_id, None)
        if subscription is not None:
            try:
                subscription.close()
            except Exception:
                pass

    def _on_grid_info_change(self, grid_id: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            state = self._states.pop(grid_id, None)
            if state is None:
                return
            with self._lock:
                self._descriptor_cache.pop(grid_id, None)
            self._detach_grid(grid_id)
            self._emit_removed(state)
            return

        data = self._coerce_dict(payload)
        if data is None:
            return

        with self._lock:
            state = self._states.get(grid_id)
            if state is None:
                state = GridState(self.owner_id, grid_id, {}, data)
                self._states[grid_id] = state
            else:
                state.info = data
            snapshot = state.clone()
        self._emit_updated(snapshot)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------
    def _emit_added(self, state: GridState) -> None:
        callbacks: Iterable[GridCallback]
        with self._lock:
            callbacks = list(self._on_added)
        for callback in callbacks:
            try:
                callback(state.clone())
            except Exception:
                pass

    def _emit_updated(self, state: GridState) -> None:
        callbacks: Iterable[GridCallback]
        with self._lock:
            callbacks = list(self._on_updated)
        for callback in callbacks:
            try:
                callback(state.clone())
            except Exception:
                pass

    def _emit_removed(self, state: GridState) -> None:
        callbacks: Iterable[GridRemovedCallback]
        with self._lock:
            callbacks = list(self._on_removed)
        for callback in callbacks:
            try:
                callback(state.clone())
            except Exception:
                pass

    def _grid_key(self, grid_id: str) -> str:
        return f"se:{self.owner_id}:grid:{grid_id}:gridinfo"

    @staticmethod
    def _extract_grids(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, dict):
            grids = payload.get("grids", [])
        else:
            grids = payload
        if isinstance(grids, list):
            return [grid for grid in grids if isinstance(grid, dict)]
        return []

    @staticmethod
    def _extract_grid_id(descriptor: Dict[str, Any]) -> Optional[str]:
        for key in ("grid_id", "gridId", "id", "GridId", "entity_id", "entityId"):
            value = descriptor.get(key)
            if value is None:
                continue
            return str(value)
        return None

    @staticmethod
    def _coerce_dict(payload: Any) -> Optional[Dict[str, Any]]:
        if payload is None:
            return None
        if isinstance(payload, dict):
            return dict(payload)
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                return None
            return decoded if isinstance(decoded, dict) else None
        return None


__all__ = ["Grids", "GridState"]

