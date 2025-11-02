"""
Container device implementation for Space Engineers grid control.

This module provides functionality to interact with cargo containers on SE grids,
including transferring items between containers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Set, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class Item:
    """
    Represents an item in the container.
    """
    def __init__(self, type: str, subtype: str, amount: float, display_name: str | None = None):
        self.type = type
        self.subtype = subtype
        self.amount = amount
        self.display_name = display_name

    @classmethod
    def from_dict(cls, data: dict) -> Item:
        return cls(
            type=data.get("type", ""),
            subtype=data.get("subtype", ""),
            amount=data.get("amount", 0.0),
            display_name=data.get("displayName")
        )

    def to_dict(self) -> dict:
        d = {
            "type": self.type,
            "subtype": self.subtype,
            "amount": self.amount
        }
        if self.display_name:
            d["displayName"] = self.display_name
        return d


class ContainerDevice(BaseDevice):
    """
    Обёртка для контейнеров (Cargo Container).
    Позволяет переносить предметы между инвентарями по entityId блоков.
    Совместима с C# ContainerDevice.ProcessCommandAsync(...) из DedicatedPlugin.
    """
    # Можно назвать "container" или "cargo_container". Главное — согласованная нормализация.
    device_type = "container"

    # Кэш для разобранных полей телеметрии
    _items_cache: list[Item] | None = None
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
        normalized: list[Item] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                item_dict = {
                    "type": it.get("type") or it.get("Type") or "",
                    "subtype": it.get("subtype")
                    or it.get("subType")
                    or it.get("name")
                    or "",
                    "amount": float(it.get("amount", 0.0)),
                }
                if it.get("displayName"):
                    item_dict["displayName"] = it["displayName"]
                normalized.append(Item.from_dict(item_dict))
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
    def items(self) -> list[Item]:
        """
        Возвращает список предметов из текущей телеметрии как объекты Item.
        """
        # отдаём из кэша, если уже приходила телеметрия
        if isinstance(self._items_cache, list):
            return list(self._items_cache)

        # если кэша нет, попробуем взять напрямую из сырых данных (одноразово)
        telemetry = self.telemetry or {}
        items = telemetry.get("items") if isinstance(telemetry, dict) else None
        if not isinstance(items, list):
            return []
        normalized: list[Item] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            item_dict = {
                "type": it.get("type") or it.get("Type") or "",
                "subtype": it.get("subtype") or it.get("subType") or it.get("name") or "",
                "amount": float(it.get("amount", 0.0)),
            }
            if it.get("displayName"):
                item_dict["displayName"] = it["displayName"]
            normalized.append(Item.from_dict(item_dict))
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
    def _send_transfer(self, *, from_id: int | str, to_id: int | str, items: list[Item] | list[dict], cmd: str = "transfer_items") -> int:
        """
        Низкоуровневый отправитель команды переноса.
        ВАЖНО: payload/state должен быть именно JSON-строкой — так ожидает C#.
        """
        # Нормализация полей items
        norm_items: list[dict] = []
        for it in items:
            if isinstance(it, Item):
                it_dict = it.to_dict()
            elif isinstance(it, dict):
                it_dict = it
            else:
                continue
            subtype = it_dict.get("subtype") or it_dict.get("subType") or it_dict.get("name")
            if not subtype:
                # без сабтайпа переносить нечего
                continue
            entry = {"subtype": str(subtype)}
            # type — опционален (wildcard по типу в C# коде)
            if it_dict.get("type"):
                entry["type"] = str(it_dict["type"])
            # amount — опционален, отсутствие == перенести стек целиком
            if it_dict.get("amount") is not None:
                entry["amount"] = float(it_dict["amount"])
            # targetSlotId — опционален для указания целевого слота
            target_slot_id = it_dict.get("targetSlotId")
            if target_slot_id is None:
                target_slot_id = it_dict.get("slotId")
            if target_slot_id is None:
                target_slot_id = it_dict.get("targetSlot")
            if target_slot_id is not None:
                entry["targetSlotId"] = int(target_slot_id)
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

    def move_items(self, destination: int | str, items: list[Item] | list[dict]) -> int:
        """
        Перенести список предметов по сабтайпу (и при желании type/amount) в другой контейнер.

        items: [{ "subtype": "IronIngot", "type": "MyObjectBuilder_Ingot", "amount": 50 }, ...] или [Item(...), ...]
        - type     (опционально): точный TypeId (как в телеметрии/SE), можно не указывать.
        - amount   (опционально): если не задан — будет перенесён весь стек найденного айтема.
        """
        return self._send_transfer(from_id=self.device_id, to_id=destination, items=items, cmd="transfer_items")

    def move_subtype(self, destination: int | str, subtype: str, *, amount: float | None = None, type_id: str | None = None, target_slot_id: int | None = None) -> int:
        """
        Удобный синоним для переноса одного сабтайпа.
        """
        it = {"subtype": subtype}
        if type_id:
            it["type"] = type_id
        if amount is not None:
            it["amount"] = float(amount)
        if target_slot_id is not None:
            it["targetSlotId"] = int(target_slot_id)
        return self.move_items(destination, [it])

    def move_items_to_slot(self, destination: int | str, items: list[Item] | list[dict], target_slot_id: int) -> int:
        """
        Перенести список предметов в указанный слот контейнера.

        items: [{ "subtype": "IronIngot", "type": "MyObjectBuilder_Ingot", "amount": 50 }, ...] или [Item(...), ...]
        target_slot_id: номер слота для размещения предметов (0 = первый слот)
        """
        # Добавляем targetSlotId к каждому элементу
        modified_items = []
        for it in items:
            if isinstance(it, Item):
                it_dict = it.to_dict()
            elif isinstance(it, dict):
                it_dict = dict(it)
            else:
                continue
            it_dict["targetSlotId"] = int(target_slot_id)
            modified_items.append(it_dict)

        return self.move_items(destination, modified_items)

    def move_all(self, destination: int | str, *, blacklist: Set[str] | None = None) -> int:
        """
        Перенести ВСЁ содержимое контейнера (по текущей телеметрии) в другой контейнер.
        Можно задать чёрный список сабтайпов (например, оставить лед у источника).
        """
        bl = {s.lower() for s in (blacklist or set())}
        batch = []
        for it in self.items():
            sb = it.subtype.lower()
            if not sb or sb in bl:
                continue
            # amount опускаем — на стороне плагина это значит "весь стек"
            batch.append({"subtype": it.subtype})
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

    # --------------------- Поиск предметов -----------------------------------

    def find_items_by_type(self, item_type: str) -> list[Item]:
        """
        Найти предметы по типу (type).
        """
        return [it for it in self.items() if it.type == item_type]

    def find_items_by_subtype(self, subtype: str) -> list[Item]:
        """
        Найти предметы по сабтайпу (subtype).
        """
        return [it for it in self.items() if it.subtype == subtype]

    def find_items_by_display_name(self, display_name: str) -> list[Item]:
        """
        Найти предметы по отображаемому имени (displayName).
        """
        return [it for it in self.items() if it.display_name == display_name]

    @staticmethod
    def _normalize_items(payload: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append(
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
        return out

    @staticmethod
    def _items_signature(items: List[Any]) -> Tuple[Tuple[str, float], ...]:
        # Stable signature to detect changes without noisy formatting differences
        sig: List[Tuple[str, float]] = []
        for it in items:
            if hasattr(it, 'display_name'):  # Item object
                name = str(it.display_name or it.subtype or "").strip()
                amount = it.amount
            else:  # dict
                name = str(it.get("displayName") or it.get("subtype") or "").strip()
                amount = float(it.get("amount") or 0.0)
            sig.append((name, amount))
        return tuple(sig)

    @staticmethod
    def _format_items(items: List[Any]) -> str:
        if not items:
            return "[]"
        parts = []
        for it in items:
            if hasattr(it, 'display_name'):  # Item object
                name = it.display_name or it.subtype or "?"
                amount = it.amount
            else:  # dict
                name = it.get("displayName") or it.get("subtype") or "?"
                amount = it.get("amount")
            parts.append(f"{amount} x {name}")
        return "[" + ", ".join(parts) + "]"


DEVICE_TYPE_MAP[ContainerDevice.device_type] = ContainerDevice
