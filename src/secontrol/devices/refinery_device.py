"""Refinery device wrapper with queue management helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from secontrol.base_device import DEVICE_TYPE_MAP
from secontrol.devices.container_device import ContainerDevice


def _parse_inventory(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"currentVolume": 0.0, "maxVolume": 0.0, "currentMass": 0.0, "items": []}
    items = [item for item in data.get("items", []) if isinstance(item, dict)]
    return {
        "currentVolume": float(data.get("currentVolume", 0.0)),
        "maxVolume": float(data.get("maxVolume", 0.0)),
        "currentMass": float(data.get("currentMass", 0.0)),
        "items": items,
    }


def _normalize_queue_item(item: Any, amount: Optional[float] = None) -> Dict[str, Any]:
    if isinstance(item, dict):
        payload = dict(item)
    elif isinstance(item, str):
        payload = {"blueprint": item}
    elif isinstance(item, (tuple, list)) and item:
        payload = {"blueprint": item[0]}
        if len(item) > 1 and amount is None:
            amount = item[1]
    else:
        raise ValueError("Unsupported queue item format: {!r}".format(item))

    if amount is not None:
        payload.setdefault("amount", float(amount))
    return payload


class RefineryDevice(ContainerDevice):
    """Inventory-enabled wrapper for refineries."""

    device_type = "refinery"

    # ----------------------- Telemetry helpers -----------------------
    def use_conveyor(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def is_producing(self) -> bool:
        return bool((self.telemetry or {}).get("isProducing", False))

    def is_queue_empty(self) -> bool:
        return bool((self.telemetry or {}).get("isQueueEmpty", True))

    def current_progress(self) -> float:
        return float((self.telemetry or {}).get("currentProgress", 0.0))

    def input_inventory(self) -> Dict[str, Any]:
        data = self.telemetry or {}
        return _parse_inventory(data.get("inputInventory"))

    def output_inventory(self) -> Dict[str, Any]:
        data = self.telemetry or {}
        return _parse_inventory(data.get("outputInventory"))

    def queue(self) -> List[Dict[str, Any]]:
        entries = (self.telemetry or {}).get("queue")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
        return []

    # -------------------------- Commands ----------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({"cmd": "enable" if enabled else "disable"})

    def toggle_enabled(self) -> int:
        return self.send_command({"cmd": "toggle"})

    def set_use_conveyor(self, enabled: bool | None = None) -> int:
        state: Dict[str, Any] = {}
        if enabled is not None:
            state["useConveyor"] = bool(enabled)
        return self.send_command({"cmd": "use_conveyor", "state": state})

    def clear_queue(self) -> int:
        return self.send_command({"cmd": "queue_clear"})

    def remove_queue_item(self, index: int, amount: Optional[float] = None) -> int:
        state: Dict[str, Any] = {"index": int(index)}
        if amount is not None:
            state["amount"] = float(amount)
        return self.send_command({"cmd": "queue_remove", "state": state})

    def add_queue_item(self, blueprint: Any, amount: Optional[float] = None) -> int:
        item = _normalize_queue_item(blueprint, amount)
        command = {"cmd": "queue_add"}
        command.update(item)
        return self.send_command(command)

    def add_queue_items(self, items: Iterable[Any]) -> int:
        sent = 0
        for entry in items:
            sent += self.add_queue_item(entry)
        return sent


DEVICE_TYPE_MAP[RefineryDevice.device_type] = RefineryDevice
