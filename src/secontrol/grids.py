"""Управление списком гридов Space Engineers.

Модуль предоставляет класс :class:`Grids`, который следит за ключами Redis
``se:<owner>:grids`` и ``se:<owner>:grid:<grid_id>:gridinfo``.  Он автоматически
обновляет состояние при появлении новых гридов, изменении уже существующих и
удалении устаревших.  Пользователь может подписываться на события «добавлен»
``(added)``, «обновлён`` (``updated``) и «удалён`` (``removed``).
"""

from __future__ import annotations

import json
import re
import threading
import time
import colorsys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Type

from .base_device import (
    BaseDevice,
    BlockInfo,
    DamageDetails,
    DamageSource,
    DeviceMetadata,
    GenericDevice,
    DEVICE_TYPE_MAP,
    create_device,
    normalize_device_type,
    _approx_equal,
    _coerce_bool,
    _safe_float,
    _safe_int,
    _prepare_color_payload,
    DEVICE_REGISTRY
)
from .redis_client import RedisEventClient

GridCallback = Callable[["GridState"], None]
GridRemovedCallback = Callable[["GridState"], None]


def _normalize_identity_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _extract_identity_tag(value: Any, kind: str) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    pattern = rf"\[\s*se:{re.escape(kind)}:([^\]]+)\]"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    tag = match.group(1).strip().lower()
    return tag or None


def _read_grid_candidate_id(candidate: Dict[str, Any]) -> Optional[str]:
    raw_id = (
        candidate.get("id")
        or candidate.get("gridId")
        or candidate.get("grid_id")
        or candidate.get("entityId")
        or candidate.get("gridEntityId")
    )
    if raw_id in (None, ""):
        return None
    return str(raw_id)


def _read_grid_candidate_name(candidate: Dict[str, Any]) -> Optional[str]:
    raw_name = candidate.get("name") or candidate.get("gridName") or candidate.get("displayName")
    if raw_name in (None, ""):
        return None
    return str(raw_name)


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


@dataclass
class DamageEvent:
    """Событие нанесения урона по блоку грида."""

    timestamp: str
    grid_id: Optional[int]
    grid_name: Optional[str]
    grid_is_static: Optional[bool]
    owner_id: Optional[int]
    attacker_id: Optional[int]
    block: Optional[BlockInfo]
    damage: DamageDetails
    attacker: DamageSource
    raw: Dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "DamageEvent":
        if not isinstance(payload, dict):
            raise TypeError("Damage event payload must be a dictionary")

        timestamp_raw = payload.get("timestamp") or payload.get("time")
        timestamp = str(timestamp_raw) if timestamp_raw is not None else ""

        grid_id = _safe_int(payload.get("gridId"))
        owner_id = _safe_int(payload.get("ownerId"))
        attacker_id = _safe_int(payload.get("attackerId"))

        grid_name = payload.get("gridName")
        grid_is_static_raw = payload.get("gridIsStatic")
        grid_is_static = (
            None if grid_is_static_raw is None else _coerce_bool(grid_is_static_raw)
        )

        block_payload = payload.get("block")
        block: Optional[BlockInfo] = None
        if isinstance(block_payload, dict):
            try:
                block = BlockInfo.from_payload(block_payload)
            except Exception:
                block = None

        damage_details = DamageDetails.from_payload(payload.get("damage"))
        attacker = DamageSource.from_payload(payload.get("attacker"))

        if attacker_id is None and attacker.entity_id is not None:
            attacker_id = attacker.entity_id

        raw_copy = dict(payload)

        return cls(
            timestamp=timestamp,
            grid_id=grid_id,
            grid_name=str(grid_name) if isinstance(grid_name, str) and grid_name.strip() else None,
            grid_is_static=grid_is_static,
            owner_id=owner_id,
            attacker_id=attacker_id,
            block=block,
            damage=damage_details,
            attacker=attacker,
            raw=raw_copy,
        )


@dataclass
class RemovedDeviceInfo:
    """Сведения об устройстве, удалённом из состава грида."""

    device_id: str
    device_type: Optional[str]
    name: Optional[str]


@dataclass
class GridDevicesEvent:
    """Набор изменений в составе устройств грида."""

    added: List["BaseDevice"]
    removed: List[RemovedDeviceInfo]


@dataclass
class GridIntegrityChange:
    """Изменение целостности отдельного блока."""

    block_id: int
    block: BlockInfo
    name: Optional[str]
    block_type: str
    subtype: Optional[str]
    previous_integrity: Optional[float]
    current_integrity: Optional[float]
    previous_max_integrity: Optional[float]
    current_max_integrity: Optional[float]
    was_damaged: bool
    is_damaged: bool


class Grid:
    """Representation of a Space Engineers grid."""

    def __init__(
        self,
        redis_client,
        owner_id: str,
        grid_id: str,
        player_id: str,
        name: str = None,
        auto_wake: bool = True,
    ) -> None:
        self.redis = redis_client
        self.owner_id = owner_id
        self.grid_id = grid_id
        self.player_id = player_id
        self.name = name or f"Grid_{grid_id}"
        self.stable_grid_tag = _extract_identity_tag(self.name, "grid")
        self.grid_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
        self.metadata: Optional[Dict[str, Any]] = None
        self.is_subgrid: bool = False
        self.devices: Dict[str, BaseDevice] = {}
        # NEW: индекс по числовому id
        self.devices_by_num: Dict[int, BaseDevice] = {}
        self.devices_by_stable_key: Dict[str, BaseDevice] = {}
        self.device_aliases: Dict[str, str] = {}
        self.grid_aliases: set[str] = {str(grid_id)}
        self.blocks: Dict[int, BlockInfo] = {}
        self._damage_channel = f"se:{owner_id}:grid:{grid_id}:damage"
        self._damage_subscriptions: list[Any] = []
        self.identity_suspect = False
        self.identity_suspect_reason: Optional[str] = None
        self.identity_generation = 0
        self.last_gridinfo_at = time.monotonic()
        self.last_rebind_at = 0.0
        self.rebind_cooldown_s = 1.0
        self._identity_lock = threading.RLock()

        self._runtime_boot_key = f"se:{owner_id}:runtime:server_boot"
        self._runtime_restart_key = f"se:{owner_id}:runtime:server_restart"
        self._runtime_restart_channel = f"se.{owner_id}.runtime.server_restart"
        self._runtime_boot_id = self._read_runtime_boot_id()
        self._runtime_last_check_at = 0.0
        self._runtime_check_interval_s = 2.0
        self._runtime_subscription = None
        self._runtime_channel_subscription = None
        try:
            self._runtime_subscription = self.redis.subscribe_to_key(
                self._runtime_restart_key, self._on_runtime_restart
            )
        except Exception:
            self._runtime_subscription = None
        try:
            self._runtime_channel_subscription = self.redis.subscribe_to_channel(
                self._runtime_restart_channel, self._on_runtime_restart
            )
        except Exception:
            self._runtime_channel_subscription = None

        # Event listeners: event name -> list of callbacks
        # Callback signature: (grid: Grid, payload: Any, source_event: str) -> None
        self._listeners: dict[str, list[Callable[["Grid", Any, str], None]]] = {}


        self._subscription = self.redis.subscribe_to_key(
            self.grid_key, self._on_grid_change
        )
        initial = self.redis.get_json(self.grid_key)
        if initial is not None:
            self._on_grid_change(self.grid_key, initial, "initial")

        # Aggregate devices from subgrids
        self._aggregate_devices_from_subgrids()

        if auto_wake:
            self.wake()

    def wake(self, timeout: float = 3.0, poll_interval: float = 0.1) -> bool:
        """Send a no-op activation command and wait briefly for richer telemetry."""

        self.send_grid_command("wake")
        return self.wait_until_ready(timeout=timeout, poll_interval=poll_interval)

    def wait_until_ready(self, timeout: float = 3.0, poll_interval: float = 0.1) -> bool:
        """Wait until grid metadata switches from summary to a fuller payload."""

        deadline = time.time() + max(0.0, float(timeout))
        interval = max(0.01, float(poll_interval))

        while time.time() <= deadline:
            metadata = self.metadata if isinstance(self.metadata, dict) else {}
            detail_level = str(metadata.get("detailLevel", "")).strip().lower()
            comp = metadata.get("comp")
            devices = comp.get("devices", []) if isinstance(comp, dict) else []
            blocks = metadata.get("blocks", [])

            if detail_level and detail_level != "summary":
                return True
            if self.devices:
                return True
            if isinstance(devices, list) and devices:
                return True
            if isinstance(blocks, list) and blocks:
                return True

            time.sleep(interval)

        return False

    def _on_runtime_restart(self, key: str, payload: Optional[Any], event: str) -> None:
        boot_id = self._extract_boot_id(payload)
        if boot_id and boot_id != self._runtime_boot_id:
            self._runtime_boot_id = boot_id
        self.mark_identity_suspect("server runtime restart event")

    def _read_runtime_boot_id(self) -> Optional[str]:
        try:
            return self._extract_boot_id(self.redis.get_json(self._runtime_boot_key))
        except Exception:
            return None

    @staticmethod
    def _extract_boot_id(payload: Optional[Any]) -> Optional[str]:
        if isinstance(payload, dict):
            value = payload.get("bootId") or payload.get("boot_id")
            if value not in (None, ""):
                return str(value)
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except Exception:
                return None
            if isinstance(parsed, dict):
                value = parsed.get("bootId") or parsed.get("boot_id")
                if value not in (None, ""):
                    return str(value)
        return None

    def mark_identity_suspect(self, reason: str) -> None:
        self.identity_suspect = True
        self.identity_suspect_reason = reason
        self.identity_generation += 1

    def _runtime_boot_changed(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self._runtime_last_check_at < self._runtime_check_interval_s:
            return False
        self._runtime_last_check_at = now
        boot_id = self._read_runtime_boot_id()
        if boot_id and boot_id != self._runtime_boot_id:
            self._runtime_boot_id = boot_id
            self.mark_identity_suspect("server boot id changed")
            return True
        return False

    def before_command(self) -> None:
        self._runtime_boot_changed()
        if self.identity_suspect:
            self.ensure_current_binding(force=True)

    def ensure_current_binding(self, *, force: bool = False) -> bool:
        with self._identity_lock:
            self._runtime_boot_changed(force=force)
            if not force and not self.identity_suspect:
                return True

            now = time.monotonic()
            if force and now - self.last_rebind_at < self.rebind_cooldown_s:
                return True
            self.last_rebind_at = now

            try:
                candidates = self.redis.list_grids(self.owner_id)
            except Exception:
                candidates = []

            match = self._find_matching_grid(candidates)
            if match is None:
                try:
                    current = self.redis.get_json(self.grid_key)
                except Exception:
                    current = None
                if isinstance(current, dict):
                    self._on_grid_change(self.grid_key, current, "identity-check")
                    return True
                return False

            new_grid_id = _read_grid_candidate_id(match)
            if not new_grid_id:
                return False

            new_name = _read_grid_candidate_name(match)
            if str(new_grid_id) != str(self.grid_id):
                self._rebind_grid_id(str(new_grid_id), new_name)
            else:
                payload = self.redis.get_json(self.grid_key)
                if isinstance(payload, dict):
                    self._on_grid_change(self.grid_key, payload, "identity-check")

            self.identity_suspect = False
            self.identity_suspect_reason = None
            return True

    def _find_matching_grid(self, candidates: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        current_name = _normalize_identity_text(self.name)
        current_tag = self.stable_grid_tag
        current_id = str(self.grid_id)
        exact_id = None
        exact_name = None
        tag_match = None

        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            candidate_id = _read_grid_candidate_id(candidate)
            candidate_name = _read_grid_candidate_name(candidate)
            candidate_name_norm = _normalize_identity_text(candidate_name)
            candidate_tag = _extract_identity_tag(candidate_name, "grid")

            if candidate_id and str(candidate_id) == current_id:
                exact_id = candidate
            if current_tag and candidate_tag and candidate_tag == current_tag:
                tag_match = candidate
            elif current_name and candidate_name_norm and candidate_name_norm == current_name:
                exact_name = candidate

        return tag_match or exact_name or exact_id

    def _rebind_grid_id(self, new_grid_id: str, new_name: Optional[str] = None) -> None:
        old_grid_id = str(self.grid_id)
        self.grid_aliases.add(old_grid_id)
        self.grid_id = str(new_grid_id)
        if new_name:
            self.name = str(new_name)
            tag = _extract_identity_tag(self.name, "grid")
            if tag:
                self.stable_grid_tag = tag
        self.grid_key = f"se:{self.owner_id}:grid:{self.grid_id}:gridinfo"

        try:
            self._subscription.close()
        except Exception:
            pass

        self._subscription = self.redis.subscribe_to_key(self.grid_key, self._on_grid_change)
        payload = self.redis.get_json(self.grid_key)
        if isinstance(payload, dict):
            self._on_grid_change(self.grid_key, payload, "rebind")

    def ensure_device_current(self, device: "BaseDevice", *, force: bool = False) -> bool:
        if device is None:
            return False

        if not force and not self.identity_suspect and self.devices.get(str(device.device_id)) is device:
            return True

        self.ensure_current_binding(force=force)
        stable_key = self._device_stable_key(device.metadata)
        if not stable_key:
            return self.devices.get(str(device.device_id)) is device

        current = self.devices_by_stable_key.get(stable_key)
        if current is device:
            return True

        if current is not None:
            old_id = str(device.device_id)
            metadata = current.metadata
            try:
                current.close()
            except Exception:
                pass
            device.rebind(metadata)
            self.device_aliases[old_id] = str(device.device_id)
            self.devices[str(device.device_id)] = device
            try:
                self.devices_by_num[int(device.device_id)] = device
            except Exception:
                pass
            self.devices_by_stable_key[stable_key] = device
            return True

        return False

    def _device_stable_key(self, metadata: DeviceMetadata) -> str:
        if metadata is None:
            return ""
        extra = metadata.extra if isinstance(metadata.extra, dict) else {}
        name = metadata.name or extra.get("customName") or extra.get("name") or extra.get("displayName") or extra.get("displayNameText")
        tag = _extract_identity_tag(name, "device")
        if tag:
            return f"tag:{tag}"
        subtype = extra.get("subtype") or extra.get("subType") or extra.get("Subtype") or ""
        position = extra.get("position") or extra.get("localPosition") or extra.get("min") or extra.get("gridPosition") or ""
        name_key = _normalize_identity_text(name)
        if name_key:
            return f"type:{metadata.device_type}|subtype:{_normalize_identity_text(subtype)}|name:{name_key}"
        if position:
            return f"type:{metadata.device_type}|subtype:{_normalize_identity_text(subtype)}|pos:{_normalize_identity_text(position)}"
        return ""

    @staticmethod
    def from_name(
        name: str,
        redis_client: Optional[RedisEventClient] = None,
        owner_id: Optional[str] = None,
        player_id: Optional[str] = None,
        *,
        auto_wake: bool = True,
        wake_timeout: float = 3.0,
    ) -> 'Grid':
        """Создать объект Grid по имени, используя поиск через Grids."""
        from .common import resolve_owner_id, resolve_player_id
        if redis_client is None:
            redis_client = RedisEventClient()
        if owner_id is None:
            owner_id = resolve_owner_id()
        if player_id is None:
            player_id = resolve_player_id(owner_id)
        grids = Grids(redis_client, owner_id, player_id)
        results = grids.search(name)
        if not results:
            raise ValueError(f"Grid with name '{name}' not found")
        grid_id = results[0].grid_id
        grid_name = results[0].name or f"Grid_{grid_id}"
        print(f"Resolved grid '{name}' to: {grid_id} ({grid_name})")
        grid = Grid(redis_client, owner_id, grid_id, player_id, name, auto_wake=False)
        if auto_wake:
            grid.wake(timeout=wake_timeout)
        return grid

    # ------------------------------------------------------------------
    def on(
        self,
        event: str,
        callback: Callable[["Grid", Any, str], None],
    ) -> None:
        """Регистрирует обработчик событий грида."""

        if not isinstance(event, str) or not event:
            raise ValueError("event must be a non-empty string")
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._listeners.setdefault(event, []).append(callback)

    # ------------------------------------------------------------------
    def off(
        self,
        event: str,
        callback: Callable[["Grid", Any, str], None],
    ) -> None:
        """Удаляет обработчик событий грида."""

        listeners = self._listeners.get(event)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            return
        if not listeners:
            self._listeners.pop(event, None)

    def __str__(self) -> str:
        return f"{self.name}: {len(self.devices)} device(s)"


    # ------------------------------------------------------------------
    def _emit(self, event: str, payload: Any, source_event: str) -> None:
        listeners = list(self._listeners.get(event, []))
        if not listeners:
            return
        for callback in listeners:
            try:
                callback(self, payload, source_event)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _on_grid_change(self, key: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            return
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return
        self.last_gridinfo_at = time.monotonic()
        # При наличии имени грида в payload — обновим локальное имя
        try:
            payload_id = payload.get("id") or payload.get("gridId") or payload.get("gridEntityId")
            if payload_id not in (None, "") and str(payload_id) != str(self.grid_id):
                self.grid_aliases.add(str(self.grid_id))
                self.grid_id = str(payload_id)
                self.grid_key = f"se:{self.owner_id}:grid:{self.grid_id}:gridinfo"

            new_name = (
                payload.get("name")
                or payload.get("gridName")
                or payload.get("displayName")
                or payload.get("DisplayName")
            )
            if isinstance(new_name, str) and new_name.strip():
                self.name = new_name
                tag = _extract_identity_tag(self.name, "grid")
                if tag:
                    self.stable_grid_tag = tag
        except Exception:
            pass

        previous_blocks = dict(self.blocks)

        self.metadata = payload
        from .common import _is_subgrid
        self.is_subgrid = _is_subgrid(self.metadata)
        device_metadata = list(self._extract_devices(payload))
        # Add devices from subgrids
        for sub_id in payload.get("subGridIds", []):
            if sub_id:
                sub_id_str = str(sub_id)
                sub_key = f"se:{self.owner_id}:grid:{sub_id_str}:gridinfo"
                subpayload = self.redis.get_json(sub_key)
                if subpayload:
                    device_metadata.extend(self._extract_devices_for_payload(subpayload, sub_id_str))
        metadata_ids = {meta.device_id for meta in device_metadata}

        added_devices: List[BaseDevice] = []
        removed_devices: List[RemovedDeviceInfo] = []
        old_by_stable: Dict[str, BaseDevice] = {}
        reused_object_ids: set[int] = set()
        for old_device in self.devices.values():
            stable_key = self._device_stable_key(getattr(old_device, "metadata", None))
            if stable_key:
                old_by_stable.setdefault(stable_key, old_device)
        self.devices_by_stable_key = {}

        # добавление/обновление устройств
        for metadata in device_metadata:
            device = self.devices.get(metadata.device_id)
            stable_key = self._device_stable_key(metadata)
            if device is None and stable_key:
                device = old_by_stable.get(stable_key)
                if device is not None:
                    self.device_aliases[str(device.device_id)] = str(metadata.device_id)
                    device.rebind(metadata)
            if device is None:
                device = create_device(self, metadata)
                self.devices[metadata.device_id] = device
                added_devices.append(device)
            else:
                # check if device class needs to be updated (e.g., upgrade from GenericDevice)
                if (device.__class__.__name__ == 'GenericDevice' and
                    metadata.device_type != 'generic' and
                    DEVICE_TYPE_MAP.get(metadata.device_type.lower())):
                    # replace with correct device class
                    self.devices[metadata.device_id] = None  # temp
                    old_device = device
                    device = create_device(self, metadata)
                    self.devices[metadata.device_id] = device
                    removed_devices.append(
                        RemovedDeviceInfo(
                            device_id=metadata.device_id,
                            device_type='generic',
                            name=getattr(old_device, "name", None),
                        )
                    )
                    added_devices.append(device)
                    old_device.close()
                else:
                    device.update_metadata(metadata)

            self.devices[metadata.device_id] = device
            reused_object_ids.add(id(device))
            try:
                did_int = int(metadata.device_id)
            except Exception:
                pass
            else:
                self.devices_by_num[did_int] = device
            if stable_key:
                self.devices_by_stable_key[stable_key] = device

        # удаление исчезнувших устройств
        for device_id in list(self.devices):
            if device_id in metadata_ids:
                continue
            device = self.devices.pop(device_id)
            if id(device) in reused_object_ids:
                continue
            removed_devices.append(
                RemovedDeviceInfo(
                    device_id=device_id,
                    device_type=getattr(device, "device_type", None),
                    name=getattr(device, "name", None),
                )
            )
            try:
                self.devices_by_num.pop(int(device_id), None)
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass

        # Upgrade GenericDevice to specific class if available
        for device in list(self.devices.values()):
            if (device.__class__.__name__ == 'GenericDevice' and
                getattr(device, 'device_type', '').lower() != 'generic'):
                cls_to_use = DEVICE_TYPE_MAP.get(getattr(device, 'device_type', '').lower())
                if cls_to_use and cls_to_use != GenericDevice:
                    new_device = create_device(self, device.metadata)
                    self.devices[device.metadata.device_id] = new_device
                    try:
                        num_id = int(device.metadata.device_id)
                        self.devices_by_num[num_id] = new_device
                    except ValueError:
                        pass
                    removed_devices.append(
                        RemovedDeviceInfo(
                            device_id=device.metadata.device_id,
                            device_type='generic',
                            name=getattr(device, 'name', None),
                        )
                    )
                    added_devices.append(new_device)
                    device.close()

        if added_devices or removed_devices:
            self._emit(
                "devices",
                GridDevicesEvent(added=added_devices, removed=removed_devices),
                event,
            )

        block_entries = list(self._extract_blocks(payload))
        # Add blocks from subgrids
        for sub_id in payload.get("subGridIds", []):
            if sub_id:
                sub_id_str = str(sub_id)
                sub_key = f"se:{self.owner_id}:grid:{sub_id_str}:gridinfo"
                subpayload = self.redis.get_json(sub_key)
                if subpayload:
                    block_entries.extend(self._extract_blocks(subpayload))
        new_blocks = {block.block_id: block for block in block_entries}
        if block_entries or self.blocks:
            integrity_changes = self._detect_integrity_changes(previous_blocks, new_blocks)
            self.blocks = new_blocks
            if integrity_changes:
                self._emit("integrity", {"changes": integrity_changes}, event)

    # ------------------------------------------------------------------
    def _detect_integrity_changes(
        self,
        previous_blocks: Dict[int, BlockInfo],
        current_blocks: Dict[int, BlockInfo],
    ) -> List[GridIntegrityChange]:
        changes: List[GridIntegrityChange] = []
        for block_id, current in current_blocks.items():
            previous = previous_blocks.get(block_id)
            if previous is None:
                continue

            prev_state = previous.state if isinstance(previous.state, dict) else {}
            curr_state = current.state if isinstance(current.state, dict) else {}

            prev_integrity = _safe_float(prev_state.get("integrity"))
            curr_integrity = _safe_float(curr_state.get("integrity"))
            prev_max = _safe_float(prev_state.get("maxIntegrity"))
            curr_max = _safe_float(curr_state.get("maxIntegrity"))

            was_damaged = previous.is_damaged
            is_damaged = current.is_damaged

            if (
                _approx_equal(prev_integrity, curr_integrity)
                and _approx_equal(prev_max, curr_max)
                and was_damaged == is_damaged
            ):
                continue

            changes.append(
                GridIntegrityChange(
                    block_id=block_id,
                    block=current,
                    name=current.name,
                    block_type=current.block_type,
                    subtype=current.subtype,
                    previous_integrity=prev_integrity,
                    current_integrity=curr_integrity,
                    previous_max_integrity=prev_max,
                    current_max_integrity=curr_max,
                    was_damaged=was_damaged,
                    is_damaged=is_damaged,
                )
            )

        return changes

    # ------------------------------------------------------------------
    def get_device(self, device_id: str) -> Optional["BaseDevice"]:
        return self.devices.get(str(device_id))

    # NEW: поиск по числовому идентификатору
    def get_device_num(self, device_id: int) -> Optional["BaseDevice"]:
        """Вернёт устройство по числовому device/entity ID или None, если не найдено."""

        return self.devices_by_num.get(int(device_id))

    # NEW: универсальный помощник — принимает и str, и int
    def get_device_any(self, device_id: int | str) -> Optional["BaseDevice"]:
        """
        Если пришёл int — ищем через devices_by_num.
        Если str — сначала точное совпадение, затем пробуем int(device_id).
        """

        if isinstance(device_id, int):
            return self.devices_by_num.get(device_id)
        dev = self.devices.get(device_id)
        if dev:
            return dev
        try:
            return self.devices_by_num.get(int(device_id))
        except Exception:
            return None

    # NEW: поиск устройств по типу
    def find_devices_by_type(self, device_type: str | Type[BaseDevice]) -> list["BaseDevice"]:
        """
        Возвращает список устройств указанного типа.

        Принимает как нормализованные типы (например, "battery", "projector"),
        как исходные имена из Space Engineers (например, "MyObjectBuilder_BatteryBlock"),
        так и классы устройств (например, DisplayDevice).
        Тип приводится к нормализованному виду через ``normalize_device_type``.
        """

        if isinstance(device_type, type):
            # if passed a class like DisplayDevice
            normalized = getattr(device_type, "device_type", "generic").lower()
        else:
            try:
                normalized = normalize_device_type(device_type)
            except Exception:
                normalized = str(device_type).lower()

        return [d for d in self.devices.values() if getattr(d, "device_type", "").lower() == normalized]

    def find_devices_by_name(self, name_pattern: str) -> list["BaseDevice"]:
        """
        Возвращает список устройств, чьи имена совпадают с паттерном (регистр не чувствителен).
        Поддерживает подстроки (contains) и регулярные выражения, если паттерн начинается/заканчивается '/' или содержит '.*'.
        """

        if not name_pattern:
            return []
        pattern_lower = name_pattern.lower()

        devices: list["BaseDevice"] = []
        for device in self.devices.values():
            device_name = (device.name or "").lower()
            # Проверяем на regex, если паттерн выглядит как regex
            if name_pattern.startswith("^") or name_pattern.endswith("$") or ".*" in name_pattern or "[^" in name_pattern:
                try:
                    if re.search(name_pattern, device_name, re.IGNORECASE):
                        devices.append(device)
                except re.error:
                    # Если regex неправильный, fallback на contains
                    if pattern_lower in device_name:
                        devices.append(device)
            else:
                # Иначе contains
                if pattern_lower in device_name:
                    devices.append(device)
        return devices

    def get_first_device(
        self,
        device_type: str | Type[BaseDevice],
        name: Optional[str] = None,
    ) -> Optional["BaseDevice"]:
        """
        Возвращает первое устройство указанного типа.

        Если указано name, возвращает первое устройство с указанным именем среди устройств этого типа.

        Принимает как нормализованные типы (например, "battery", "projector"),
        исходные имена из Space Engineers (например, "MyObjectBuilder_BatteryBlock"),
        так и классы устройств (например, DisplayDevice).

        Если устройств нет, возвращает None.
        """
        devices = self.find_devices_by_type(device_type)
        if name is None:
            return devices[0] if devices else None
        else:
            for dev in devices:
                if dev.name == name:
                    return dev
            return None

    def aggregate_device_load(self) -> Dict[str, float | int]:
        """Агрегирует показатели нагрузки всех устройств на гриде."""

        totals: Dict[str, float | int] = {
            "devices": 0,
            "spentMs": 0.0,
            "totalAvgMs": 0.0,
            "totalPeakMs": 0.0,
            "updateAvgMs": 0.0,
            "updatePeakMs": 0.0,
            "commandsAvgMs": 0.0,
            "commandsPeakMs": 0.0,
        }

        def _add(key: str, value: Any) -> None:
            if value is None:
                return
            try:
                totals[key] = float(totals[key]) + float(value)
            except (TypeError, ValueError):
                pass

        for device in self.devices.values():
            metrics = device.load_metrics()
            if not metrics:
                continue

            totals["devices"] = int(totals["devices"]) + 1

            _add("spentMs", metrics.get("spentMs"))

            total_bucket = metrics.get("total")
            if isinstance(total_bucket, dict):
                _add("totalAvgMs", total_bucket.get("avgMs"))
                _add("totalPeakMs", total_bucket.get("peakMs"))

            update_bucket = metrics.get("update")
            if isinstance(update_bucket, dict):
                _add("updateAvgMs", update_bucket.get("avgMs"))
                _add("updatePeakMs", update_bucket.get("peakMs"))

            commands_bucket = metrics.get("commands")
            if isinstance(commands_bucket, dict):
                _add("commandsAvgMs", commands_bucket.get("avgMs"))
                _add("commandsPeakMs", commands_bucket.get("peakMs"))

        if totals["devices"]:
            totals["avgSpentMsPerDevice"] = float(totals["spentMs"]) / int(totals["devices"])
        else:
            totals["avgSpentMsPerDevice"] = 0.0

        return totals

    def find_enabled_devices(self, device_type: Optional[str] = None) -> list["BaseDevice"]:
        """
        Возвращает список включенных устройств, опционально фильтруя по типу.
        Если device_type=None, возвращает все включенные устройства.
        """

        enabled: list["BaseDevice"] = []
        if device_type is not None:
            type_devices = self.find_devices_by_type(device_type)
        else:
            type_devices = self.devices.values()

        for device in type_devices:
            if device.is_enabled():
                enabled.append(device)
        return enabled

    def find_damaged_blocks(self) -> list[BlockInfo]:
        """
        Возвращает список поврежденных блоков, где integrity < maxIntegrity или damaged=True.
        """
        return [block for block in self.blocks.values() if block.is_damaged]

    def find_devices_containers(self) -> list["BaseDevice"]:
        """
        Возвращает список устройств, которые могут содержать предметы (имеют инвентари).
        """
        return [d for d in self.devices.values() if getattr(d, "is_container", False)]

    def get_all_grid_items(self) -> list[dict]:
        """
        Возвращает список всех предметов на гриде с информацией о расположении.

        Каждый элемент содержит:
        - device_id: ID устройства
        - device_name: имя устройства
        - device_type: тип устройства
        - inventory_name: имя внутреннего инвентаря
        - item_type: тип предмета
        - item_subtype: подтип предмета
        - amount: количество
        - display_name: отображаемое имя предмета
        """
        items = []
        for device in self.find_devices_containers():
            for inventory in device.inventories():
                for item in inventory.items:
                    items.append({
                        "device_id": device.device_id,
                        "device_name": device.name,
                        "device_type": device.device_type,
                        "inventory_name": inventory.name,
                        "item_type": item.type,
                        "item_subtype": item.subtype,
                        "amount": item.amount,
                        "display_name": item.display_name,
                    })
        return items

    def find_items_by_type(self, item_type: str) -> list[dict]:
        """
        Возвращает все предметы указанного типа на гриде.

        Args:
            item_type: Тип предмета (например, "MyObjectBuilder_Ore")

        Returns:
            Список словарей с информацией о предметах
        """
        return [item for item in self.get_all_grid_items() if item["item_type"] == item_type]

    def find_items_by_subtype(self, subtype: str) -> list[dict]:
        """
        Возвращает все предметы указанного подтипа на гриде.

        Args:
            subtype: Подтип предмета (например, "SteelPlate")

        Returns:
            Список словарей с информацией о предметах
        """
        return [item for item in self.get_all_grid_items() if item["item_subtype"] == subtype]

    def find_items_by_display_name(self, display_name: str) -> list[dict]:
        """
        Возвращает все предметы с указанным отображаемым именем на гриде.

        Args:
            display_name: Отображаемое имя предмета

        Returns:
            Список словарей с информацией о предметах
        """
        return [item for item in self.get_all_grid_items() if item["display_name"] == display_name]

    def get_total_amount(self, subtype: str) -> float:
        """
        Возвращает общее количество предмета указанного подтипа на гриде.

        Args:
            subtype: Подтип предмета

        Returns:
            Общее количество
        """
        items = self.find_items_by_subtype(subtype)
        return sum(item["amount"] for item in items)

    def find_containers_with_tag(self, tag: str) -> list["BaseDevice"]:
        """
        Возвращает все контейнеры с указанным тегом.

        Args:
            tag: Тег для поиска

        Returns:
            Список контейнеров
        """
        containers = []
        for device in self.find_devices_containers():
            if hasattr(device, 'has_tag') and device.has_tag(tag):
                containers.append(device)
        return containers

    def find_tagged_containers(self) -> list[tuple["BaseDevice", set[str]]]:
        """
        Возвращает все контейнеры с их тегами.

        Returns:
            Список кортежей (контейнер, теги)
        """
        result = []
        for device in self.find_devices_containers():
            if hasattr(device, 'tags'):
                tags = device.tags
                if tags:
                    result.append((device, tags))
        return result

    # ------------------------------------------------------------------
    def get_block(self, block_id: int | str) -> Optional[BlockInfo]:
        """Возвращает блок по его ``EntityId``."""

        try:
            resolved = int(block_id)
        except (TypeError, ValueError):
            return None
        return self.blocks.get(resolved)

    def iter_blocks(self) -> Iterable[BlockInfo]:
        """Итерируется по всем известным блокам грида."""

        return self.blocks.values()

    def find_blocks_by_type(self, block_type: str) -> list[BlockInfo]:
        """Возвращает блоки указанного типа или подтипа."""

        normalized = str(block_type or "").strip().lower()
        if not normalized:
            return []
        return [block for block in self.blocks.values() if block.normalized_type == normalized]

    def _normalize_block_id(self, block: int | str | BlockInfo) -> int:
        if isinstance(block, BlockInfo):
            block_id = block.block_id
        else:
            block_id = _safe_int(block)

        if block_id is None or block_id <= 0:
            raise ValueError("block identifier must be a positive integer")

        return block_id

    # ------------------------------------------------------------------
    def _grid_command_channel(self) -> str:
        return f"se.{self.player_id}.commands.grid.{self.grid_id}"

    # ------------------------------------------------------------------
    def send_grid_command(
        self,
        command: str,
        *,
        state: Any | None = None,
        payload: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> int:
        """Публикует команду на уровень грида."""

        if not command:
            raise ValueError("command must be a non-empty string")

        self.before_command()

        message: Dict[str, Any] = {}
        if payload:
            for key, value in payload.items():
                if value is not None:
                    message[key] = value

        for key, value in extra.items():
            if value is not None and key not in message:
                message[key] = value

        if state is not None:
            message.setdefault("state", state)

        now_ms = int(time.time() * 1000)
        message.setdefault("cmd", command)
        message.setdefault("seq", now_ms)
        message.setdefault("ts", now_ms)
        message.setdefault("targetType", "grid")

        grid_int = _safe_int(self.grid_id)
        if grid_int is not None:
            message.setdefault("gridId", grid_int)
            message.setdefault("gridEntityId", grid_int)
            message.setdefault("grid_id", grid_int)
            message.setdefault("targetId", grid_int)
            message.setdefault("target_id", grid_int)

        owner_int = _safe_int(self.owner_id)
        if owner_int is not None:
            message.setdefault("ownerId", owner_int)
            message.setdefault("owner_id", owner_int)

        player_int = _safe_int(self.player_id)
        if player_int is not None:
            message.setdefault("playerId", player_int)
            message.setdefault("player_id", player_int)
            message.setdefault("userId", player_int)

        meta = message.get("meta")
        if isinstance(meta, dict):
            meta.setdefault("user", "grid-wrapper")
        else:
            message["meta"] = {"user": "grid-wrapper"}

        channel = self._grid_command_channel()
        return self.redis.publish(channel, message)

    # ------------------------------------------------------------------
    def rename(self, new_name: str) -> int:
        """Изменяет отображаемое имя грида."""

        if not new_name or not new_name.strip():
            raise ValueError("new_name must be a non-empty string")

        trimmed = new_name.strip()
        return self.send_grid_command(
            "set_name",
            state=trimmed,
            payload={"name": trimmed, "gridName": trimmed},
        )

    # ------------------------------------------------------------------
    def set_owner(
        self,
        owner_id: int | str,
        *,
        share_mode: Optional[str] = None,
        share_with_all: Optional[bool] = None,
        share_with_faction: Optional[bool] = None,
    ) -> int:
        """Передаёт владение гридом выбранному игроку."""

        owner_int = _safe_int(owner_id)
        if owner_int is None or owner_int <= 0:
            raise ValueError("owner_id must be a positive integer")

        payload: Dict[str, Any] = {"ownerId": owner_int}
        if share_mode is not None:
            payload["shareMode"] = str(share_mode).strip()
        if share_with_all is not None:
            payload["shareWithAll"] = bool(share_with_all)
        if share_with_faction is not None:
            payload["shareWithFaction"] = bool(share_with_faction)

        return self.send_grid_command("set_owner", payload=payload)

    # ------------------------------------------------------------------
    def convert_to_ship(self) -> int:
        """Переводит грид в режим корабля."""

        return self.send_grid_command("convert_to_ship")

    # ------------------------------------------------------------------
    def convert_to_station(self) -> int:
        """Переводит грид в режим станции."""

        return self.send_grid_command("convert_to_station")

    # ------------------------------------------------------------------
    def paint_block(
        self,
        block_id: int | str | BlockInfo,
        *,
        color: Any = None,
        hsv: Sequence[Any] | None = None,
        rgb: Sequence[Any] | None = None,
        space: str | None = None,
        play_sound: bool | None = None,
    ) -> int:
        """Меняет цвет одного блока по его ``EntityId``."""

        block_int = self._normalize_block_id(block_id)

        color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)

        payload: Dict[str, Any] = {"blockId": block_int}
        payload.update(color_payload)

        if play_sound is not None:
            payload["playSound"] = bool(play_sound)

        return self.send_grid_command("paint_block", payload=payload)

    # ------------------------------------------------------------------
    def paint_blocks(
        self,
        blocks: Iterable[int | str | BlockInfo],
        *,
        color: Any = None,
        hsv: Sequence[Any] | None = None,
        rgb: Sequence[Any] | None = None,
        space: str | None = None,
        play_sound: bool | None = None,
    ) -> int:
        """Меняет цвет нескольких блоков одним запросом."""

        if isinstance(blocks, (BlockInfo, int, str)):
            candidates = [blocks]
        else:
            candidates = list(blocks)

        block_ids: list[int] = []
        for item in candidates:
            block_ids.append(self._normalize_block_id(item))

        if not block_ids:
            raise ValueError("blocks must contain at least one block identifier")

        # сохраняем порядок и убираем дубликаты
        unique_ids = list(dict.fromkeys(block_ids))

        color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)

        payload: Dict[str, Any] = {
            **color_payload,
            "blocks": [{"blockId": block_id} for block_id in unique_ids],
        }

        if play_sound is not None:
            payload["playSound"] = bool(play_sound)

        return self.send_grid_command("paint_blocks", payload=payload)

    # ------------------------------------------------------------------
    def create_gps_marker(
        self,
        name: str | None = None,
        *,
        gps: str | None = None,
        coordinates: Sequence[Any] | str | None = None,
        position: Sequence[Any] | str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        description: str | None = None,
        color: Any = None,
        rgb: Sequence[Any] | None = None,
        hsv: Sequence[Any] | None = None,
        space: str | None = None,
        show_on_hud: bool | None = None,
        show_on_terminal: bool | None = None,
        show_on_map: bool | None = None,
        temporary: bool | None = None,
        always_visible: bool | None = None,
        entity_id: int | str | None = None,
    ) -> int:
        """Создаёт GPS-метку для владельца грида.

        Если координаты не указаны, серверная часть использует текущую позицию
        грида. Можно передать готовую GPS-строку Space Engineers (`gps`),
        текстовые или числовые координаты (`coordinates`/`position`) либо три
        значения `x`, `y`, `z`.
        """

        payload: Dict[str, Any] = {}

        if name:
            payload["name"] = name.strip()
        if description:
            payload["description"] = description

        if gps:
            gps_text = gps.strip()
            if gps_text:
                payload["gps"] = gps_text

        def _normalize_vector(value: Sequence[Any] | str | None) -> Optional[tuple[float, float, float]]:
            if value is None:
                return None
            if isinstance(value, str):
                parts = [p for p in re.split(r"[;,\s]+", value.strip()) if p]
                if len(parts) < 3:
                    raise ValueError("coordinates string must contain three numbers")
                try:
                    vector = (float(parts[0]), float(parts[1]), float(parts[2]))
                except ValueError as exc:
                    raise ValueError("failed to parse coordinates from string") from exc
                return vector

            if isinstance(value, Sequence):
                if len(value) < 3:
                    raise ValueError("coordinate sequence must contain at least three values")
                try:
                    vector = (float(value[0]), float(value[1]), float(value[2]))
                except (TypeError, ValueError) as exc:
                    raise ValueError("failed to convert coordinates to float") from exc
                return vector

            raise TypeError("coordinates must be a string or a sequence of three numbers")

        vector = None
        for candidate in (coordinates, position):
            vector = _normalize_vector(candidate)
            if vector is not None:
                break

        if vector is None and any(v is not None for v in (x, y, z)):
            missing = [axis for axis, value in (("x", x), ("y", y), ("z", z)) if value is None]
            if missing:
                raise ValueError(f"coordinates require all three components (missing: {', '.join(missing)})")
            vector = (float(x), float(y), float(z))

        if vector is not None:
            payload["position"] = {"x": vector[0], "y": vector[1], "z": vector[2]}

        if show_on_hud is not None:
            payload["showOnHud"] = bool(show_on_hud)
        if show_on_terminal is not None:
            payload["showOnTerminal"] = bool(show_on_terminal)
        if show_on_map is not None:
            payload["showOnMap"] = bool(show_on_map)
        if temporary is not None:
            payload["temporary"] = bool(temporary)
        if always_visible is not None:
            payload["alwaysVisible"] = bool(always_visible)

        if entity_id is not None:
            entity_int = _safe_int(entity_id)
            if entity_int is None or entity_int <= 0:
                raise ValueError("entity_id must be a positive integer")
            payload["entityId"] = entity_int

        if color is not None or rgb is not None or hsv is not None:
            color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)
            if "hsv" in color_payload:
                hsv_values = color_payload["hsv"]
                h = float(hsv_values.get("h", 0.0))
                s = float(hsv_values.get("s", 0.0))
                v = float(hsv_values.get("v", 0.0))
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                color_payload = {
                    "rgb": {
                        "r": max(0, min(255, int(round(r * 255.0)))),
                        "g": max(0, min(255, int(round(g * 255.0)))),
                        "b": max(0, min(255, int(round(b * 255.0)))),
                    }
                }
            payload.update(color_payload)

        return self.send_grid_command("create_gps", payload=payload)

    # ------------------------------------------------------------------
    def list_gps_markers(
        self,
        *,
        show_on_hud: bool | None = None,
        show_on_map: bool | None = None,
        always_visible: bool | None = None,
        request_id: str | None = None,
    ) -> int:
        """Запрашивает у сервера список GPS-меток игрока."""

        payload: Dict[str, Any] = {}

        if show_on_hud is not None:
            payload["showOnHud"] = bool(show_on_hud)
        if show_on_map is not None:
            payload["showOnMap"] = bool(show_on_map)
        if always_visible is not None:
            payload["alwaysVisible"] = bool(always_visible)
        if request_id:
            payload["requestId"] = str(request_id)

        effective_payload = payload if payload else None
        return self.send_grid_command("list_gps", payload=effective_payload)

    # ------------------------------------------------------------------
    def park(
        self,
        enabled: bool,
        brake_wheels: bool,
        shutdown_thrusters: bool,
        lock_connectors: bool,
    ) -> int:
        """Активирует или деактивирует режим парковки грида."""

        payload: Dict[str, Any] = {
            "enabled": bool(enabled),
            "brakeWheels": bool(brake_wheels),
            "shutdownThrusters": bool(shutdown_thrusters),
            "lockConnectors": bool(lock_connectors),
        }
        return self.send_grid_command("park", payload=payload)

    def park_on(self):
        self.park(
            enabled=True,
            brake_wheels=True,
            shutdown_thrusters=True,
            lock_connectors=True
        )

    def park_off(self):
        self.park(
            enabled=False,
            brake_wheels=False,
            shutdown_thrusters=False,
            lock_connectors=False
        )

    # ------------------------------------------------------------------
    def power(self, mode: str) -> int:
        """Изменяет режим питания грида."""

        valid_modes = {"on", "soft_off", "hard_off"}
        if mode not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}, got {mode!r}")

        payload: Dict[str, Any] = {"mode": mode}
        return self.send_grid_command("power", payload=payload)

    def power_on(self):
        self.power("on")

    def power_off(self):
        self.power("soft_off")

    # ------------------------------------------------------------------
    def _extract_devices(self, payload: Dict[str, Any]) -> Iterable[DeviceMetadata]:
        """Extract devices from main grid's payload."""
        yield from self._extract_devices_for_payload(payload, self.grid_id)

    def _extract_devices_for_payload(self, payload: Dict[str, Any], grid_id: str) -> Iterable[DeviceMetadata]:
        # собираем кандидатов из новых мест: payload['blocks']
        candidates: list[Dict[str, Any]] = []

        # 1) devices из blocks (новый формат)
        blocks_entries = payload.get("blocks")
        if isinstance(blocks_entries, list):
            candidates.extend([b for b in blocks_entries if isinstance(b, dict)])

        if not candidates:
            return

        for entry in candidates:
            # Проверяем, является ли блок устройством
            if not entry.get("isDevice", False):
                continue

            # из вашего JSON: поля называются id/type/subtype/name
            raw_type = (
                entry.get("type")
                or entry.get("deviceType")
                or entry.get("subtype")
                or "generic"
            )
            subtype = entry.get("subtype") or entry.get("SubtypeName")
            device_type = normalize_device_type(raw_type)

            # id может быть int — приводим к строке
            raw_id = (
                entry.get("deviceId")
                or entry.get("entityId")
                or entry.get("id")
                or ""
            )
            if raw_id in ("", None):
                continue
            device_id = str(raw_id)

            # telemetryKey в вашем примере нет — синтезируем по нашей схеме
            telemetry_key = entry.get("telemetryKey") or entry.get("key")
            if not telemetry_key:
                telemetry_key = self.build_device_key(device_type, device_id)

            custom_name = entry.get("customName") or entry.get("CustomName")
            display_name = (
                entry.get("displayName")
                or entry.get("displayNameText")
                or entry.get("DisplayName")
                or entry.get("DisplayNameText")
            )
            raw_name = entry.get("name") or entry.get("Name")
            name = custom_name or display_name or raw_name
            extra = dict(entry)
            # Приоритезация имен
            if custom_name is not None:
                extra["customName"] = custom_name
            if raw_name is not None:
                extra["name"] = raw_name
            if display_name is not None:
                extra["displayName"] = display_name

            yield DeviceMetadata(
                device_type=device_type,
                device_id=device_id,
                telemetry_key=str(telemetry_key),
                grid_id=grid_id,
                name=name,
                extra=extra,
            )

    def _extract_blocks(self, payload: Dict[str, Any]) -> Iterable[BlockInfo]:
        candidates: list[Dict[str, Any]] = []

        root_blocks = payload.get("blocks")
        if isinstance(root_blocks, dict):
            candidates.extend([b for b in root_blocks.values() if isinstance(b, dict)])
        elif isinstance(root_blocks, list):
            candidates.extend([b for b in root_blocks if isinstance(b, dict)])

        comp = payload.get("comp")
        if isinstance(comp, dict):
            comp_blocks = comp.get("blocks")
            if isinstance(comp_blocks, dict):
                candidates.extend([b for b in comp_blocks.values() if isinstance(b, dict)])
            elif isinstance(comp_blocks, list):
                candidates.extend([b for b in comp_blocks if isinstance(b, dict)])

        seen: Dict[int, BlockInfo] = {}
        for entry in candidates:
            try:
                block = BlockInfo.from_payload(entry)
            except Exception:
                continue
            seen[block.block_id] = block

        return seen.values()

    # ------------------------------------------------------------------
    def _discover_devices_from_telemetry_keys(self) -> None:
        """
        Scans for existing telemetry keys and adds devices that are not already known.
        This helps discover devices that exist in telemetry but not listed in gridinfo (e.g., for rovers).
        """
        pattern = f"se:{self.owner_id}:grid:{self.grid_id}:*:*:telemetry"
        existing_device_ids = set(self.devices.keys())

        try:
            keys_found = []
            for key in self.redis.client.scan_iter(match=pattern, count=100):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")

                # Parse key: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
                parts = key.split(":")
                if len(parts) != 7 or parts[6] != "telemetry":
                    continue

                device_type_raw = parts[4]
                device_id = parts[5]

                if device_id in existing_device_ids:
                    continue
                keys_found.append(key)

                device_type_normalized = normalize_device_type(device_type_raw)
                telemetry_key = key

                # Fetch snapshot to get name and potentially correct device type for AI blocks
                snapshot = self.redis.get_json(telemetry_key)
                name = None
                if isinstance(snapshot, dict):
                    for name_key in ("name", "customName", "displayName", "CustomName"):
                        if snapshot.get(name_key):
                            name = str(snapshot[name_key])
                            break

                    # Special handling for AI blocks
                    ai_role = snapshot.get("aiRole")
                    ai_subtype = snapshot.get("aiSubtype")
                    if ai_role:
                        if ai_role == "Mission" and ai_subtype == "FlightAutopilot":
                            device_type_normalized = "ai_flight_autopilot"
                        elif ai_role == "Behavior":
                            device_type_normalized = "ai_behavior"
                        elif ai_role == "Task":
                            if ai_subtype == "Defensive":
                                device_type_normalized = "ai_defensive"
                            elif ai_subtype == "Offensive":
                                device_type_normalized = "ai_offensive"
                        elif ai_role == "Recorder":
                            device_type_normalized = "ai_recorder"

                metadata = DeviceMetadata(
                    device_type=device_type_normalized,
                    device_id=device_id,
                    telemetry_key=telemetry_key,
                    grid_id=self.grid_id,
                    name=name or f"{device_type_normalized}:{device_id}",
                    extra={},
                )

                device = create_device(self, metadata)
                self.devices[device_id] = device
                try:
                    num_id = int(device_id)
                    self.devices_by_num[num_id] = device
                except ValueError:
                    pass

            pass

        except Exception:
            # Ignore errors during discovery to avoid breaking initialization
            pass

    def _aggregate_devices_from_subgrids(self) -> None:
        """
        Scans telemetry keys for subgrids and creates devices for them.
        """
        if not self.metadata:
            return
        subGridIds = self.metadata.get("subGridIds") or []
        if not isinstance(subGridIds, list):
            return
        for sub_id in subGridIds:
            sub_id_str = str(sub_id)
            # Discover for this subgrid
            self._discover_devices_from_telemetry_keys_for_grid(sub_id_str)

    def _discover_devices_from_telemetry_keys_for_grid(self, sub_grid_id: str) -> None:
        """
        Scans for existing telemetry keys for a specific subgrid and adds devices that are not already known.
        """
        # se:{owner}:grid:{sub_grid_id}:*:*:telemetry but wait, no:
        # For subgrids, if they have their own keys, the pattern is grid:{sub_grid_id}
        pattern = f"se:{self.owner_id}:grid:{sub_grid_id}:*:*:telemetry"
        existing_device_ids = set(self.devices.keys())

        try:
            keys_found = []
            for key in self.redis.client.scan_iter(match=pattern, count=100):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")

                # Parse key: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
                parts = key.split(":")
                if len(parts) != 7 or parts[6] != "telemetry":
                    continue

                device_type_raw = parts[4]
                device_id = parts[5]

                if device_id in existing_device_ids:
                    continue
                keys_found.append(key)

                device_type_normalized = normalize_device_type(device_type_raw)
                telemetry_key = key

                # Fetch snapshot to get name
                snapshot = self.redis.get_json(telemetry_key)
                name = None
                if isinstance(snapshot, dict):
                    for name_key in ("name", "customName", "displayName", "CustomName"):
                        if snapshot.get(name_key):
                            name = str(snapshot[name_key])
                            break

                metadata = DeviceMetadata(
                    device_type=device_type_normalized,
                    device_id=device_id,
                    telemetry_key=telemetry_key,
                    grid_id=sub_grid_id,  # use subgrid id as metadata.grid_id
                    name=name or f"{device_type_normalized}:{device_id}",
                    extra={},
                )

                device = create_device(self, metadata)  # grid=self, so commands will use self.grid_id, but for subgrids it might be wrong, but perhaps okay if using device.grid_id
                self.devices[device_id] = device
                try:
                    num_id = int(device_id)
                    self.devices_by_num[num_id] = device
                except ValueError:
                    pass

            # print(f"Subgrid {sub_grid_id} keys found: {keys_found}")

        except Exception:
            # Ignore errors
            pass

    # ------------------------------------------------------------------
    def build_device_key(self, device_type: str, device_id: str) -> str:
        # Normalize type to the snake_case form used in telemetry keys
        type_key = self._normalize_type_for_telemetry(str(device_type))
        return f"se:{self.owner_id}:grid:{self.grid_id}:{type_key}:{device_id}:telemetry"

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._subscription.close()
        except Exception:
            pass
        for subscription in (self._runtime_subscription, self._runtime_channel_subscription):
            try:
                if subscription is not None:
                    subscription.close()
            except Exception:
                pass
        for damage_subscription in list(self._damage_subscriptions):
            try:
                damage_subscription.close()
            except Exception:
                pass
        self._damage_subscriptions.clear()
        for device in list(self.devices.values()):
            device.close()
        self.devices.clear()
        self.devices_by_num.clear()
        self.blocks.clear()

    def get_device_by_id(self, device_id: int) -> BaseDevice | None:
        """Быстрый поиск устройства по числовому ID."""

        return self.devices_by_num.get(int(device_id))

    def refresh_devices(self) -> int:
        """
        Перечитывает gridinfo и обновляет self.devices.
        Возвращает число обнаруженных (актуализированных) устройств.
        """

        info_key = f"se:{self.owner_id}:grid:{self.grid_id}:gridinfo"
        payload = self.redis.get_json(info_key) or {}

        # Нормализуем секцию с устройствами:
        devices_section = None
        if isinstance(payload, dict):
            if "devices" in payload:
                devices_section = payload["devices"]
            elif isinstance(payload.get("comp"), dict) and "devices" in payload["comp"]:
                devices_section = payload["comp"]["devices"]

        if not devices_section:
            # Нет устройств в gridinfo — ничего не делаем
            return 0

        # Преобразуем devices_section к списку словарей устройств
        dev_items: list[dict] = []
        if isinstance(devices_section, list):
            dev_items = [d for d in devices_section if isinstance(d, dict)]
        elif isinstance(devices_section, dict):
            # варианты: { "Projector": [ {...}, ... ], "Battery": [ ... ] } ИЛИ { "8788": {...}, ... }
            if devices_section and all(
                isinstance(k, str) and k.isdigit() for k in devices_section.keys()
            ):
                dev_items = [v for v in devices_section.values() if isinstance(v, dict)]
            else:
                for v in devices_section.values():
                    if isinstance(v, list):
                        dev_items.extend([d for d in v if isinstance(d, dict)])
                    elif isinstance(v, dict):
                        dev_items.append(v)

        updated = 0
        for d in dev_items:
            try:
                dev_id = int(d.get("id"))
            except Exception:
                continue

            dev_type = d.get("type") or d.get("blockType") or ""
            dev_subtype = d.get("subtype") or d.get("subType") or ""
            dev_name = d.get("name") or f"{dev_type}:{dev_id}"

            device = self.devices_by_num.get(dev_id)
            if device is None:
                # Подбираем класс
                device_cls_or_name = DEVICE_REGISTRY.get(dev_type, None)
                if device_cls_or_name is None:
                    # Используем DEVICE_TYPE_MAP для разрешения по типу
                    cls = DEVICE_TYPE_MAP.get(normalize_device_type(dev_type, dev_subtype), BaseDevice)
                else:
                    # Если в DEVICE_REGISTRY есть запись, проверим, является ли она строкой (именем типа)
                    if isinstance(device_cls_or_name, str):
                        cls = DEVICE_TYPE_MAP.get(device_cls_or_name, BaseDevice)
                    else:
                        # иначе это уже сам класс устройства
                        cls = device_cls_or_name

                # Конструктор BaseDevice/наследников может отличаться — приведи под свой
                # Создаем DeviceMetadata для передачи в конструктор
                telemetry_key = self.build_device_key(
                    normalize_device_type(dev_type, dev_subtype), str(dev_id)
                )
                metadata = DeviceMetadata(
                    device_type=normalize_device_type(dev_type, dev_subtype),
                    device_id=str(dev_id),
                    telemetry_key=telemetry_key,
                    grid_id=self.grid_id,
                    name=dev_name,
                    extra={
                        "type": dev_type,
                        "subtype": dev_subtype,
                    },
                )
                device = cls(
                    grid=self,
                    metadata=metadata,
                )
                self.devices[str(dev_id)] = device
                self.devices_by_num[dev_id] = device
            else:
                # Обновим имя/типы, если поменялись
                setattr(device, "name", dev_name)
                setattr(device, "type", dev_type)
                setattr(device, "subtype", dev_subtype)

            # Пробуем подтянуть снимок телеметрии
            self._refresh_device_telemetry(device, dev_type, dev_id)
            updated += 1

        return updated

    # ------------------------------------------------------------------
    def subscribe_to_damage(
        self, callback: Callable[[DamageEvent | Dict[str, Any] | str], None]
    ):
        """Подписывается на события урона по текущему гриду.

        Callback получает экземпляр :class:`DamageEvent` при успешном разборе
        сообщения. Если полезную нагрузку не удалось разобрать, в callback
        передаются исходные данные (dict или строка).
        """

        if not callable(callback):
            raise TypeError("callback must be callable")

        def _handle_damage(_channel: str, payload: Any, event_name: str) -> None:
            message = payload if payload is not None else event_name
            if message is None:
                return

            if isinstance(message, dict):
                data = message
            elif isinstance(message, str):
                text = message.strip()
                if not text:
                    return
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    callback(text)
                    return
            else:
                callback(message)
                return

            try:
                damage_event = DamageEvent.from_payload(data)
            except Exception:
                callback(data)
                return

            callback(damage_event)

        subscription = self.redis.subscribe_to_key(self._damage_channel, _handle_damage)
        self._damage_subscriptions.append(subscription)
        return subscription

    def _refresh_device_telemetry(
        self, device: BaseDevice, dev_type: str, dev_id: int
    ) -> None:
        """
        Заполняет последнюю известную телеметрию устройства, если ключ существует.
        Ключ: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
        """

        # dev_type в телеметрии обычно «чистый» (например, battery_block, projector и т.п.).
        # Если у тебя в Redis тип — уже нормализован, замапь тут при необходимости.
        if getattr(device, "device_type", "") == "nanobot_build_and_repair":
            type_key = "nanobot_build_and_repair"
        else:
            type_key = self._normalize_type_for_telemetry(dev_type)
        tkey = f"se:{self.owner_id}:grid:{self.grid_id}:{type_key}:{dev_id}:telemetry"
        snap = self.redis.get_json(tkey)
        if isinstance(snap, dict):
            # под свою модель: device.telemetry / device.state / device.cache …
            setattr(device, "telemetry", snap)
            # Обновляем ключ с expire=180
            try:
                self.redis.set_json(tkey, snap, expire=180)
            except Exception:
                pass

    def _normalize_type_for_telemetry(self, dev_type: str) -> str:
        """
        Приведение типа к сегменту ключа телеметрии.
        Пример: 'MyObjectBuilder_Xxx' -> 'xxx'.

        Также учитывает различия между нормализованным типом устройства и
        фактическим сегментом ключа телеметрии. Например, для контейнеров
        нормализованный тип — 'container', а в ключе используется 'cargo_container'.
        """

        # Частные соответствия "тип устройства" -> "тип в ключе"
        special: dict[str, str] = {
            # Cargo containers публикуют телеметрию как 'cargo_container'
            "container": "cargo_container",
            # Connectors публикуют телеметрию как 'ship_connector'
            "connector": "ship_connector",
            "gas_tank": "oxygen_tank",
            # Text panels (LCD) используют сегмент 'text_panel'
            "textpanel": "text_panel",
            # Wheels публикуют телеметрию как 'motor_suspension'
            "wheel": "motor_suspension",
            # Nanobot drill systems публикуют телеметрию как 'drill'
            "nanobot_drill_system": "drill",
        }

        key = dev_type
        if key in special:
            return special[key]

        if key.startswith("MyObjectBuilder_"):
            key = key.removeprefix("MyObjectBuilder_")
        # Простейшая snake_case нормализация
        return "".join([("_" + c.lower() if c.isupper() else c) for c in key]).lstrip("_")



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

    def search(self, query: str) -> List[GridState]:
        """Найти гриды по части имени или идентификатора."""

        if not query:
            return []

        normalized_query = query.lower()
        with self._lock:
            states = list(self._states.values())

        matches: List[GridState] = []
        for state in states:
            if normalized_query in str(state.grid_id).lower():
                matches.append(state.clone())
                continue

            candidate_names: list[str] = []
            if state.name:
                candidate_names.append(state.name)

            for source in (state.info, state.descriptor):
                if not isinstance(source, dict):
                    continue
                for key in ("name", "gridName", "displayName", "DisplayName"):
                    value = source.get(key)
                    if isinstance(value, str) and value.strip():
                        candidate_names.append(value)
                descriptor_id = source.get("id")
                if descriptor_id is not None:
                    candidate_names.append(str(descriptor_id))

            if any(normalized_query in name.lower() for name in candidate_names):
                matches.append(state.clone())

        return matches

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
