"""
Container device implementation for Space Engineers grid control.

This module provides functionality to interact with cargo containers on SE grids,
including transferring items between containers.
"""

from __future__ import annotations

import json
from typing import Set

from sepy.base_device import BaseDevice, DEVICE_TYPE_MAP


class ContainerDevice(BaseDevice):
    """
    Обёртка для контейнеров (Cargo Container).
    Позволяет переносить предметы между инвентарями по entityId блоков.
    Совместима с C# ContainerDevice.ProcessCommandAsync(...) из DedicatedPlugin.
    """
    # Можно назвать "container" или "cargo_container". Главное — согласованная нормализация.
    device_type = "container"

    # --------------------- Телеметрия (удобные геттеры) -----------------------
    def items(self) -> list[dict]:
        """
        Возвращает список предметов из текущей телеметрии:
        [{type, subtype, amount, displayName?}, ...]
        """
        if not self.telemetry:
            return []
        items = self.telemetry.get("items")
        if isinstance(items, list):
            # нормализуем ключи/типы
            out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                out.append({
                    "type": it.get("type") or it.get("Type") or "",
                    "subtype": it.get("subtype") or it.get("subType") or it.get("name") or "",
                    "amount": float(it.get("amount", 0.0)),
                    **({"displayName": it["displayName"]} if "displayName" in it and it["displayName"] else {}),
                })
            return out
        return []

    def capacity(self) -> dict:
        """
        Возвращает сводку по объёму/массе/заполнению из телеметрии.
        """
        t = self.telemetry or {}
        return {
            "currentVolume": float(t.get("currentVolume", 0.0)),
            "maxVolume": float(t.get("maxVolume", 0.0)),
            "currentMass": float(t.get("currentMass", 0.0)),
            "fillRatio": float(t.get("fillRatio", 0.0)),
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
