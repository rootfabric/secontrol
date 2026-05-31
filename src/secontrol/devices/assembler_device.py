"""Assembler device wrapper with queue management helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional

from secontrol.base_device import DEVICE_TYPE_MAP, DeviceMetadata
from secontrol.devices.container_device import ContainerDevice
from secontrol.inventory import InventorySnapshot
from secontrol.grids import Grid
from secontrol.item_types import Item


def _blueprint_subtype(blueprint_id: Any) -> str:
    """Return the subtype part of a Space Engineers blueprint id."""
    text = str(blueprint_id or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _canonical_blueprint_id(blueprint_id: Any) -> str:
    """Build a safe MyDefinitionId-like blueprint id when only a subtype is known."""
    text = str(blueprint_id or "").strip()
    if not text:
        return ""
    if "/" in text:
        return text
    return f"MyObjectBuilder_BlueprintDefinition/{text}"


def _normalize_queue_item(item: Any, amount: Optional[float] = None) -> Dict[str, Any]:
    if isinstance(item, dict):
        payload = dict(item)
        if "blueprintId" not in payload:
            for alias in ("blueprint", "blueprintSubtype", "subtype", "id"):
                value = payload.get(alias)
                if value:
                    payload["blueprintId"] = value
                    break
        if amount is None and "amount" in payload:
            amount = payload.get("amount")
    elif isinstance(item, str):
        payload = {"blueprintId": item}
    elif isinstance(item, (tuple, list)) and item:
        payload = {"blueprintId": item[0]}
        if len(item) > 1 and amount is None:
            amount = item[1]
    else:
        raise ValueError("Unsupported queue item format: {!r}".format(item))

    blueprint_id = str(payload.get("blueprintId") or "").strip()
    if not blueprint_id:
        raise ValueError("queue item must contain a non-empty blueprintId")
    payload["blueprintId"] = blueprint_id

    if amount is not None:
        payload["amount"] = float(amount)
    elif "amount" not in payload:
        payload["amount"] = 1.0
    else:
        payload["amount"] = float(payload["amount"])

    return payload


def _queue_entry_blueprint(entry: Dict[str, Any]) -> str:
    blueprint_id = str(entry.get("blueprintId") or entry.get("blueprint") or "").strip()
    if blueprint_id:
        return blueprint_id

    subtype = str(entry.get("blueprintSubtype") or entry.get("subtype") or "").strip()
    if subtype:
        return _canonical_blueprint_id(subtype)

    return str(entry.get("itemId") or "").strip()


def _queue_signature(queue: List[Dict[str, Any]]) -> tuple[tuple[int, str, float], ...]:
    signature: list[tuple[int, str, float]] = []
    for fallback_index, entry in enumerate(queue):
        try:
            index = int(entry.get("index", fallback_index))
        except (TypeError, ValueError):
            index = fallback_index

        blueprint = _queue_entry_blueprint(entry)
        try:
            amount = float(entry.get("amount", 0.0))
        except (TypeError, ValueError):
            amount = 0.0
        signature.append((index, _blueprint_subtype(blueprint), amount))
    return tuple(signature)


def _queue_total_amount(queue: List[Dict[str, Any]], blueprint: Any) -> float:
    requested_subtype = _blueprint_subtype(blueprint).lower()
    total = 0.0
    for entry in queue:
        entry_subtype = _blueprint_subtype(_queue_entry_blueprint(entry)).lower()
        if entry_subtype != requested_subtype:
            continue
        try:
            total += float(entry.get("amount", 0.0))
        except (TypeError, ValueError):
            pass
    return total


def _float_close(a: float, b: float, *, tolerance: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tolerance


class AssemblerDevice(ContainerDevice):
    """Inventory-enabled wrapper for assemblers."""

    device_type = "assembler"

    def __init__(self, grid: Grid, metadata: DeviceMetadata) -> None:
        super().__init__(grid, metadata)
        self._raw_blueprints: Optional[List[Dict[str, Any]]] = None
        self._blueprints: Optional[List[Dict[str, Any]]] = None

    # ----------------------- Telemetry helpers -----------------------
    def use_conveyor(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def is_producing(self) -> bool:
        return bool((self.telemetry or {}).get("isProducing", False))

    def is_queue_empty(self) -> bool:
        return bool((self.telemetry or {}).get("isQueueEmpty", True))

    def current_progress(self) -> float:
        return float((self.telemetry or {}).get("currentProgress", 0.0))

    def mode(self) -> str:
        telemetry = self.telemetry or {}
        return str(telemetry.get("mode") or telemetry.get("Mode") or "").strip()

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
            index = item.get("index", i)
            item_id = item.get("itemId", "N/A")
            blueprint_type = item.get("blueprintType", "N/A")
            blueprint_subtype = item.get("blueprintSubtype") or _blueprint_subtype(item.get("blueprintId")) or "N/A"
            amount = item.get("amount", "N/A")

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

    def use_conveyor_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def disassemble_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("disassembleEnabled", False))

    def repeat_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("repeatEnabled", False))

    def cooperative_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("cooperativeMode", False))

    def _send_bool_command(self, command_name: str, enabled: bool | None, *value_keys: str) -> int:
        command: Dict[str, Any] = {"cmd": command_name}
        if enabled is not None:
            value = bool(enabled)
            state = {"value": value}
            for key in value_keys:
                state[key] = value
            command.update(state)
            command["state"] = dict(state)
        return self.send_command(command)

    def set_use_conveyor(self, enabled: bool | None = None) -> int:
        # Plugin AssemblerDevice accepts command names: conveyor, conveyor_toggle.
        result = self._send_bool_command("conveyor", enabled, "useConveyor")
        print(f"Assembler {self.name} ({self.device_id}): set_use_conveyor({enabled}) -> sent {result} messages")
        return result

    def set_disassemble(self, enabled: bool | None = None) -> int:
        # In Space Engineers disassembly is a mode of the production block.
        # queue_add adds to the current mode, so production scripts must force False,
        # and disassembly scripts must force True before adding queue items.
        result = self._send_bool_command("disassemble", enabled, "DisassembleEnabled", "disassembleEnabled")
        print(f"Assembler {self.name} ({self.device_id}): set_disassemble({enabled}) -> sent {result} messages")
        return result

    def set_repeat(self, enabled: bool | None = None) -> int:
        result = self._send_bool_command("repeat", enabled, "RepeatEnabled", "repeatEnabled")
        print(f"Assembler {self.name} ({self.device_id}): set_repeat({enabled}) -> sent {result} messages")
        return result

    def set_cooperative(self, enabled: bool | None = None) -> int:
        result = self._send_bool_command("cooperative", enabled, "CooperativeMode", "cooperativeMode")
        print(f"Assembler {self.name} ({self.device_id}): set_cooperative({enabled}) -> sent {result} messages")
        return result

    def _wait_until(self, predicate, *, timeout: float = 3.0, poll: float = 0.15) -> bool:
        deadline = time.time() + max(0.0, float(timeout))
        attempt = 0
        while time.time() <= deadline:
            try:
                if predicate():
                    return True
            except Exception:
                pass

            # The plugin publishes fresh telemetry immediately after a handled command.
            # Do not spam cmd=update on every poll: RedisTransport has a per-device
            # command limiter, and update commands count too. Force an update only
            # occasionally as a fallback if the event was missed.
            attempt += 1
            force_update = attempt % 4 == 0
            try:
                self.wait_for_telemetry(
                    timeout=min(0.5, max(0.05, deadline - time.time())),
                    wait_for_new=True,
                    need_update=force_update,
                )
            except Exception:
                pass
            try:
                if predicate():
                    return True
            except Exception:
                pass
            time.sleep(max(0.01, float(poll)))

        try:
            self.wait_for_telemetry(timeout=0.5, wait_for_new=False, need_update=True)
        except Exception:
            pass
        try:
            return bool(predicate())
        except Exception:
            return False

    def set_disassemble_verified(self, enabled: bool, *, timeout: float = 3.0) -> bool:
        if self.telemetry is not None and self.disassemble_enabled() == bool(enabled):
            return True
        sent = self.set_disassemble(bool(enabled))
        if sent <= 0:
            return False
        return self._wait_until(lambda: self.disassemble_enabled() == bool(enabled), timeout=timeout)

    def set_use_conveyor_verified(self, enabled: bool, *, timeout: float = 3.0) -> bool:
        if self.telemetry is not None and self.use_conveyor_enabled() == bool(enabled):
            return True
        sent = self.set_use_conveyor(bool(enabled))
        if sent <= 0:
            return False
        return self._wait_until(lambda: self.use_conveyor_enabled() == bool(enabled), timeout=timeout)

    def clear_queue(self) -> int:
        result = self.send_command({"cmd": "queue_clear"})
        print(f"Assembler {self.name} ({self.device_id}): clear_queue() -> sent {result} messages")
        return result

    def clear_queue_verified(self, *, timeout: float = 3.0) -> bool:
        if self.telemetry is not None and not self.queue():
            return True
        sent = self.clear_queue()
        if sent <= 0:
            return False
        return self._wait_until(lambda: len(self.queue()) == 0, timeout=timeout)

    def remove_queue_item(self, index: int, amount: Optional[float] = None) -> int:
        state: Dict[str, Any] = {"index": int(index)}
        if amount is not None:
            state["amount"] = float(amount)
        command = {"cmd": "queue_remove"}
        command.update(state)
        command["state"] = dict(state)
        result = self.send_command(command)
        print(f"Assembler {self.name} ({self.device_id}): remove_queue_item({index}, {amount}) -> sent {result} messages")
        return result

    def remove_queue_item_verified(self, index: int, amount: Optional[float] = None, *, timeout: float = 3.0) -> bool:
        before_queue = self.queue()
        before_signature = _queue_signature(before_queue)
        try:
            before_item = next((entry for entry in before_queue if int(entry.get("index", -1)) == int(index)), None)
        except Exception:
            before_item = None
        if before_item is None:
            return False

        sent = self.remove_queue_item(index, amount)
        if sent <= 0:
            return False

        def changed() -> bool:
            after_queue = self.queue()
            after_signature = _queue_signature(after_queue)
            if after_signature != before_signature:
                return True

            if amount is None:
                return not any(int(entry.get("index", -1)) == int(index) for entry in after_queue)

            try:
                before_amount = float(before_item.get("amount", 0.0))
            except (TypeError, ValueError):
                before_amount = 0.0
            after_item = next((entry for entry in after_queue if int(entry.get("index", -1)) == int(index)), None)
            if after_item is None:
                return True
            try:
                after_amount = float(after_item.get("amount", 0.0))
            except (TypeError, ValueError):
                after_amount = before_amount
            return after_amount < before_amount - 1e-6

        return self._wait_until(changed, timeout=timeout)

    def add_queue_item(self, blueprint: Any, amount: Optional[float] = None, *, disassemble: bool | None = None) -> int:
        if disassemble is not None:
            self.set_disassemble(bool(disassemble))

        item = _normalize_queue_item(blueprint, amount)
        blueprint_id = self.resolve_blueprint_id(item["blueprintId"], request=True)
        blueprint_subtype = _blueprint_subtype(blueprint_id)
        amount_value = float(item["amount"])

        # Keep data both at top level and inside state. The uploaded plugin parses
        # queue_add from the original JObject in AssemblerDevice.TryAddQueueItem,
        # while other commands read the flattened CommandPayload.Data.
        state = {
            "blueprintId": blueprint_id,
            "blueprintSubtype": blueprint_subtype,
            "subtype": blueprint_subtype,
            "blueprint": blueprint_id,
            "amount": amount_value,
        }
        command = {"cmd": "queue_add"}
        command.update(state)
        command["state"] = dict(state)

        result = self.send_command(command)
        print(
            f"Assembler {self.name} ({self.device_id}): add_queue_item({blueprint}, {amount}, disassemble={disassemble}) "
            f"-> sent {result} messages, payload: {command}"
        )
        return result

    def add_queue_item_verified(
        self,
        blueprint: Any,
        amount: Optional[float] = None,
        *,
        timeout: float = 3.0,
        disassemble: bool | None = None,
    ) -> bool:
        """Add a queue item and wait until telemetry confirms a queue change."""
        if disassemble is not None and not self.set_disassemble_verified(bool(disassemble), timeout=timeout):
            return False

        item = _normalize_queue_item(blueprint, amount)
        blueprint_id = self.resolve_blueprint_id(item["blueprintId"], request=True)
        amount_value = float(item["amount"])

        before_queue = self.queue()
        before_signature = _queue_signature(before_queue)
        before_total = _queue_total_amount(before_queue, blueprint_id)

        sent = self.add_queue_item(blueprint_id, amount_value, disassemble=None)
        if sent <= 0:
            return False

        def changed() -> bool:
            after_queue = self.queue()
            after_signature = _queue_signature(after_queue)
            if after_signature != before_signature:
                return True
            after_total = _queue_total_amount(after_queue, blueprint_id)
            return after_total > before_total + 1e-6

        return self._wait_until(changed, timeout=timeout)

    def add_disassemble_item(self, blueprint: Any, amount: Optional[float] = None) -> int:
        return self.add_queue_item(blueprint, amount, disassemble=True)

    def add_disassemble_item_verified(self, blueprint: Any, amount: Optional[float] = None, *, timeout: float = 3.0) -> bool:
        return self.add_queue_item_verified(blueprint, amount, timeout=timeout, disassemble=True)

    def add_queue_items(self, items: Iterable[Any]) -> int:
        entries = list(items)
        sent = 0
        for entry in entries:
            sent += self.add_queue_item(entry)
        print(f"Assembler {self.name} ({self.device_id}): add_queue_items({len(entries)}) -> sent {sent} messages total")
        return sent

    def request_blueprints(self) -> int:
        """Request blueprint information from the assembler."""
        result = self.send_command({"cmd": "blueprints"})
        print(f"Assembler {self.name} ({self.device_id}): request_blueprints() -> sent {result} messages")
        return result

    def wait_for_blueprints(self, timeout: float = 2.0) -> bool:
        if self.blueprints:
            return True
        self.request_blueprints()
        deadline = time.time() + max(0.0, float(timeout))
        while time.time() <= deadline:
            if self.blueprints:
                return True
            try:
                self.wait_for_telemetry(timeout=0.3, wait_for_new=True, need_update=False)
            except Exception:
                pass
            time.sleep(0.1)
        return bool(self.blueprints)

    def resolve_blueprint_id(self, blueprint: Any, *, request: bool = False) -> str:
        """Resolve a short subtype to the exact available blueprint id if possible."""
        requested = str(blueprint or "").strip()
        if not requested:
            raise ValueError("blueprint must be a non-empty value")

        if request and not self.blueprints:
            self.wait_for_blueprints(timeout=2.0)

        requested_lower = requested.lower()
        requested_subtype = _blueprint_subtype(requested).lower()

        for bp in self.blueprints or []:
            bp_id = str(bp.get("blueprintId") or "").strip()
            if not bp_id:
                continue
            bp_subtype = _blueprint_subtype(bp_id).lower()
            display_name = str(bp.get("displayName") or "").strip().lower()

            if requested_lower in {bp_id.lower(), bp_subtype, display_name}:
                return bp_id
            if requested_subtype and requested_subtype == bp_subtype:
                return bp_id

            for result in bp.get("results", []) if isinstance(bp.get("results"), list) else []:
                if not isinstance(result, dict):
                    continue
                result_subtype = str(result.get("subtype") or "").strip().lower()
                if result_subtype and requested_subtype == result_subtype:
                    return bp_id

        return _canonical_blueprint_id(requested)

    def handle_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Handle telemetry update and extract blueprint data."""
        super().handle_telemetry(telemetry)

        if not hasattr(self, "_raw_blueprints"):
            self._raw_blueprints = None
        if not hasattr(self, "_blueprints"):
            self._blueprints = None

        available_blueprints = telemetry.get("availableBlueprints")
        if available_blueprints and isinstance(available_blueprints, list):
            try:
                previous_count = len(self._raw_blueprints or [])
                self._raw_blueprints = available_blueprints
                self._blueprints = self._process_blueprints(available_blueprints)
                if len(available_blueprints) != previous_count:
                    print(f"Assembler {self.name} ({self.device_id}): received {len(available_blueprints)} blueprints")
            except Exception as exc:
                print(exc)

    def _process_blueprints(self, raw_blueprints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process raw blueprint data into structured format with ItemType objects."""
        processed = []
        for bp in raw_blueprints:
            processed_bp = dict(bp)

            if "results" in bp and isinstance(bp["results"], list):
                processed_results = []
                for result in bp["results"]:
                    if isinstance(result, dict) and "type" in result and "subtype" in result:
                        item_type = getattr(Item, result["subtype"], None)
                        if item_type:
                            processed_result = dict(result)
                            processed_result["item_type"] = item_type
                            processed_results.append(processed_result)
                        else:
                            processed_results.append(result)
                    else:
                        processed_results.append(result)
                processed_bp["results"] = processed_results

            if "prerequisites" in bp and isinstance(bp["prerequisites"], list):
                processed_prereqs = []
                for prereq in bp["prerequisites"]:
                    if isinstance(prereq, dict) and "type" in prereq and "subtype" in prereq:
                        item_type = getattr(Item, prereq["subtype"], None)
                        if item_type:
                            processed_prereq = dict(prereq)
                            processed_prereq["item_type"] = item_type
                            processed_prereqs.append(processed_prereq)
                        else:
                            processed_prereqs.append(prereq)
                    else:
                        processed_prereqs.append(prereq)
                processed_bp["prerequisites"] = processed_prereqs

            processed.append(processed_bp)

        return processed

    @property
    def raw_blueprints(self) -> Optional[List[Dict[str, Any]]]:
        """Get raw blueprint data from telemetry."""
        return self._raw_blueprints

    @property
    def blueprints(self) -> Optional[List[Dict[str, Any]]]:
        """Get processed blueprint data with ItemType objects."""
        return self._blueprints

    def send_command(self, command: Dict[str, Any]) -> int:
        print(f"Assembler {self.name} ({self.device_id}): sending command: {command}")
        result = super().send_command(command)
        print(f"Assembler {self.name} ({self.device_id}): command sent, result: {result}")
        return result


DEVICE_TYPE_MAP[AssemblerDevice.device_type] = AssemblerDevice
