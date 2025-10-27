"""
Container device implementation for Space Engineers grid control.

This module provides functionality to interact with cargo containers on SE grids,
including transferring items between containers.
"""

from __future__ import annotations

import json
from typing import Set

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class ContainerDevice(BaseDevice):
    """
    Обёртка для контейнеров (Cargo Container).
    Позволяет переносить предметы между инвентарями по entityId блоков.
    Совместима с C# ContainerDevice.ProcessCommandAsync(...) из DedicatedPlugin.
    """
    # Можно назвать "container" или "cargo_container". Главное — согласованная нормализация.
    device_type = "container"

    # Кэш для разобранных полей телеметрии
    _items_cache: list[dict] | None = None
    _current_volume: float | None = None
    _max_volume: float | None = None
    _current_mass: float | None = None
    _fill_ratio: float | None = None

    # --------------------- Телеметрия (удобные геттеры) -----------------------
    def handle_telemetry(self, telemetry: dict) -> None:  # noqa: D401 - sync cache
        """
        Подписка на телеметрию устройства: обновляет кэш предметов и ёмкости.

        Ожидаемый формат (пример):
        {
            "currentVolume": 0.008,
            "maxVolume": 15.625,
            "currentMass": 5,
            "fillRatio": 0.000512,
            "items": [{"type": "…", "subtype": "…", "amount": 1, "displayName": "…"}],
            ...
        }
        """
        # сохраним снапшот в родителе (BaseDevice уже сделал это, но продублируем для ясности)
        self.telemetry = telemetry

        # Кэш предметов
        items = telemetry.get("items") if isinstance(telemetry, dict) else None
        normalized: list[dict] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                normalized.append(
                    {
                        "type": it.get("type") or it.get("Type") or "",
                        "subtype": it.get("subtype")
                        or it.get("subType")
                        or it.get("name")
                        or "",
                        "amount": float(it.get("amount", 0.0)),
                        **(
                            {"displayName": it["displayName"]}
                            if it.get("displayName")
                            else {}
                        ),
                    }
                )
        self._items_cache = normalized

        # Кэш ёмкости/массы
        try:
            self._current_volume = float(telemetry.get("currentVolume", 0.0))
        except Exception:
            self._current_volume = None
        try:
            self._max_volume = float(telemetry.get("maxVolume", 0.0))
        except Exception:
            self._max_volume = None
        try:
            self._current_mass = float(telemetry.get("currentMass", 0.0))
        except Exception:
            self._current_mass = None
        try:
            self._fill_ratio = float(telemetry.get("fillRatio", 0.0))
        except Exception:
            self._fill_ratio = None
    def items(self) -> list[dict]:
        """
        Возвращает список предметов из текущей телеметрии:
        [{type, subtype, amount, displayName?}, ...]
        """
        # отдаём из кэша, если уже приходила телеметрия
        if isinstance(self._items_cache, list):
            return list(self._items_cache)

        # если кэша нет, попробуем взять напрямую из сырых данных (одноразово)
        telemetry = self.telemetry or {}
        items = telemetry.get("items") if isinstance(telemetry, dict) else None
        if not isinstance(items, list):
            return []
        normalized: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            normalized.append(
                {
                    "type": it.get("type") or it.get("Type") or "",
                    "subtype": it.get("subtype") or it.get("subType") or it.get("name") or "",
                    "amount": float(it.get("amount", 0.0)),
                    **(
                        {"displayName": it["displayName"]}
                        if it.get("displayName")
                        else {}
                    ),
                }
            )
        self._items_cache = normalized
        return list(normalized)

    def capacity(self) -> dict:
        """
        Возвращает сводку по объёму/массе/заполнению из телеметрии.
        """
        if self._current_volume is not None or self._max_volume is not None or self._current_mass is not None or self._fill_ratio is not None:
            return {
                "currentVolume": float(self._current_volume or 0.0),
                "maxVolume": float(self._max_volume or 0.0),
                "currentMass": float(self._current_mass or 0.0),
                "fillRatio": float(self._fill_ratio or 0.0),
            }

        t = self.telemetry or {}
        try:
            current_volume = float(t.get("currentVolume", 0.0))
        except Exception:
            current_volume = 0.0
        try:
            max_volume = float(t.get("maxVolume", 0.0))
        except Exception:
            max_volume = 0.0
        try:
            current_mass = float(t.get("currentMass", 0.0))
        except Exception:
            current_mass = 0.0
        try:
            fill_ratio = float(t.get("fillRatio", 0.0))
        except Exception:
            fill_ratio = 0.0
        # заполним кэш, чтобы последующие вызовы были быстрыми
        self._current_volume = current_volume
        self._max_volume = max_volume
        self._current_mass = current_mass
        self._fill_ratio = fill_ratio
        return {
            "currentVolume": current_volume,
            "maxVolume": max_volume,
            "currentMass": current_mass,
            "fillRatio": fill_ratio,
        }

    # --------------------- Команды переноса -----------------------------------
    def _send_transfer(self, *, from_id: int | str, to_id: int | str, items: list[dict], cmd: str = "transfer_items") -> int:
        """
        Низкоуровневый отправитель команды переноса.
        ВАЖНО: payload/state должен быть именно JSON-строкой — так ожидает C#.
        """
        # Нормализация полей items
        norm_items: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            subtype = it.get("subtype") or it.get("subType") or it.get("name")
            if not subtype:
                # без сабтайпа переносить нечего
                continue
            entry = {"subtype": str(subtype)}
            # type — опционален (wildcard по типу в C# коде)
            if it.get("type"):
                entry["type"] = str(it["type"])
            # amount — опционален, отсутствие == перенести стек целиком
            if it.get("amount") is not None:
                entry["amount"] = float(it["amount"])
            norm_items.append(entry)

        if not norm_items:
            return 0

        payload_obj = {
            "fromId": int(from_id),
            "toId": int(to_id),
            "items": norm_items,
        }

        # В state кладём СТРОКУ JSON
        state_str = json.dumps(payload_obj, ensure_ascii=False)

        return self.send_command({
            "cmd": cmd,
            "state": state_str,
        })

    def move_items(self, destination: int | str, items: list[dict]) -> int:
        """
        Перенести список предметов по сабтайпу (и при желании type/amount) в другой контейнер.

        items: [{ "subtype": "IronIngot", "type": "MyObjectBuilder_Ingot", "amount": 50 }, ...]
        - type     (опционально): точный TypeId (как в телеметрии/SE), можно не указывать.
        - amount   (опционально): если не задан — будет перенесён весь стек найденного айтема.
        """
        return self._send_transfer(from_id=self.device_id, to_id=destination, items=items, cmd="transfer_items")

    def move_subtype(self, destination: int | str, subtype: str, *, amount: float | None = None, type_id: str | None = None) -> int:
        """
        Удобный синоним для переноса одного сабтайпа.
        """
        it = {"subtype": subtype}
        if type_id:
            it["type"] = type_id
        if amount is not None:
            it["amount"] = float(amount)
        return self.move_items(destination, [it])

    def move_all(self, destination: int | str, *, blacklist: Set[str] | None = None) -> int:
        """
        Перенести ВСЁ содержимое контейнера (по текущей телеметрии) в другой контейнер.
        Можно задать чёрный список сабтайпов (например, оставить лед у источника).
        """
        bl = {s.lower() for s in (blacklist or set())}
        batch = []
        for it in self.items():
            sb = (it.get("subtype") or "").lower()
            if not sb or sb in bl:
                continue
            # amount опускаем — на стороне плагина это значит "весь стек"
            batch.append({"subtype": it["subtype"]})
        if not batch:
            return 0
        return self.move_items(destination, batch)

    def drain_to(self, destination: int | str, subtypes: list[str]) -> int:
        """
        Перенести перечисленные сабтайпы ЦЕЛИКОМ в другой контейнер.
        """
        batch = [{"subtype": s} for s in subtypes if s]
        if not batch:
            return 0
        return self.move_items(destination, batch)


DEVICE_TYPE_MAP[ContainerDevice.device_type] = ContainerDevice
