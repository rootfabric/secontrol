"""Assembler device wrapper with queue management helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from secontrol.base_device import DEVICE_TYPE_MAP
from secontrol.devices.container_device import ContainerDevice
from secontrol.inventory import InventorySnapshot


def _normalize_queue_item(item: Any, amount: Optional[float] = None) -> Dict[str, Any]:
    if isinstance(item, dict):
        payload = dict(item)
    elif isinstance(item, str):
        payload = {"blueprintId": item}
    elif isinstance(item, (tuple, list)) and item:
        payload = {"blueprintId": item[0]}
        if len(item) > 1 and amount is None:
            amount = item[1]
    else:
        raise ValueError("Unsupported queue item format: {!r}".format(item))

    if amount is not None:
        payload.setdefault("amount", float(amount))
    return payload


class AssemblerDevice(ContainerDevice):
    """Inventory-enabled wrapper for assemblers."""

    device_type = "assembler"

    # ----------------------- Telemetry helpers -----------------------
    def use_conveyor(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def is_producing(self) -> bool:
        return bool((self.telemetry or {}).get("isProducing", False))

    def is_queue_empty(self) -> bool:
        return bool((self.telemetry or {}).get("isQueueEmpty", True))

    def current_progress(self) -> float:
        return float((self.telemetry or {}).get("currentProgress", 0.0))

    def input_inventory(self) -> InventorySnapshot | None:
        return self.get_inventory("inputInventory") or self.get_inventory(0)

    def output_inventory(self) -> InventorySnapshot | None:
        return self.get_inventory("outputInventory") or self.get_inventory(1)

    def queue(self) -> List[Dict[str, Any]]:
        entries = (self.telemetry or {}).get("queue")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
        return []

    def print_queue(self) -> None:
        """Print the current production queue in a readable format."""
        queue = self.queue()

        if not queue:
            print(f"Assembler {self.name} ({self.device_id}): Queue is empty")
            return

        print(f"Assembler {self.name} ({self.device_id}): Production Queue ({len(queue)} items):")
        print("-" * 70)

        for i, item in enumerate(queue):
            index = item.get('index', i)
            item_id = item.get('itemId', 'N/A')
            blueprint_type = item.get('blueprintType', 'N/A')
            blueprint_subtype = item.get('blueprintSubtype', 'N/A')
            amount = item.get('amount', 'N/A')

            print(f"[{index}] {blueprint_subtype} (ID: {item_id}) - Amount: {amount}")
            print(f"     Type: {blueprint_type}")

        print("-" * 70)

    # -------------------------- Commands ----------------------------
    def set_enabled(self, enabled: bool) -> int:
        result = self.send_command({"cmd": "enable" if enabled else "disable"})
        print(f"Assembler {self.name} ({self.device_id}): set_enabled({enabled}) -> sent {result} messages")
        return result

    def toggle_enabled(self) -> int:
        result = self.send_command({"cmd": "toggle"})
        print(f"Assembler {self.name} ({self.device_id}): toggle_enabled() -> sent {result} messages")
        return result

    def set_use_conveyor(self, enabled: bool | None = None) -> int:
        state: Dict[str, Any] = {}
        if enabled is not None:
            state["useConveyor"] = bool(enabled)
        result = self.send_command({"cmd": "use_conveyor", "state": state})
        print(f"Assembler {self.name} ({self.device_id}): set_use_conveyor({enabled}) -> sent {result} messages")
        return result

    def clear_queue(self) -> int:
        result = self.send_command({"cmd": "queue_clear"})
        print(f"Assembler {self.name} ({self.device_id}): clear_queue() -> sent {result} messages")
        return result

    def remove_queue_item(self, index: int, amount: Optional[float] = None) -> int:
        state: Dict[str, Any] = {"index": int(index)}
        if amount is not None:
            state["amount"] = float(amount)
        result = self.send_command({"cmd": "queue_remove", "state": state})
        print(f"Assembler {self.name} ({self.device_id}): remove_queue_item({index}, {amount}) -> sent {result} messages")
        return result

    def add_queue_item(self, blueprint: Any, amount: Optional[float] = None) -> int:
        item = _normalize_queue_item(blueprint, amount)
        command = {"cmd": "queue_add"}
        command.update(item)
        result = self.send_command(command)
        print(f"Assembler {self.name} ({self.device_id}): add_queue_item({blueprint}, {amount}) -> sent {result} messages, payload: {command}")
        return result

    def add_queue_items(self, items: Iterable[Any]) -> int:
        sent = 0
        for entry in items:
            sent += self.add_queue_item(entry)
        print(f"Assembler {self.name} ({self.device_id}): add_queue_items({len(list(items))}) -> sent {sent} messages total")
        return sent

    # Override send_command to add logging
    def send_command(self, command: Dict[str, Any]) -> int:
        print(f"Assembler {self.name} ({self.device_id}): sending command: {command}")
        result = super().send_command(command)
        print(f"Assembler {self.name} ({self.device_id}): command sent, result: {result}")
        return result


DEVICE_TYPE_MAP[AssemblerDevice.device_type] = AssemblerDevice
