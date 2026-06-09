"""Assembler device wrapper with queue management helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from secontrol.base_device import DEVICE_TYPE_MAP, DeviceMetadata
from secontrol.devices.container_device import ContainerDevice
from secontrol.inventory import InventoryItem, InventorySnapshot
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


def _split_definition_id(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return ("", "")
    if "/" in text:
        type_id, subtype = text.rsplit("/", 1)
        return (type_id.strip(), subtype.strip())
    return ("", text)


def _material_key(payload: Any) -> tuple[str, str]:
    """Return a stable (type, subtype) key for inventory/blueprint material payloads."""
    if isinstance(payload, InventoryItem):
        return (str(payload.type or ""), str(payload.subtype or ""))
    if not isinstance(payload, dict):
        return ("", "")

    definition_id = (
        payload.get("id")
        or payload.get("itemId")
        or payload.get("definitionId")
        or payload.get("contentId")
    )
    definition_type, definition_subtype = _split_definition_id(definition_id)

    type_id = (
        payload.get("type")
        or payload.get("Type")
        or payload.get("typeId")
        or payload.get("itemType")
        or payload.get("contentType")
        or definition_type
        or ""
    )
    subtype = (
        payload.get("subtype")
        or payload.get("subType")
        or payload.get("SubtypeName")
        or payload.get("name")
        or payload.get("itemSubtype")
        or definition_subtype
        or ""
    )

    parsed_type, parsed_subtype = _split_definition_id(type_id)
    if parsed_type and not definition_type:
        type_id = parsed_type
        if not subtype:
            subtype = parsed_subtype
    return (str(type_id), str(subtype))


def _material_amount(payload: Any) -> float:
    if isinstance(payload, InventoryItem):
        return float(payload.amount or 0.0)
    if not isinstance(payload, dict):
        return 0.0
    try:
        return float(payload.get("amount", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _merge_material_amounts(target: Dict[tuple[str, str], float], items: Iterable[Any], *, multiplier: float = 1.0) -> None:
    for item in items:
        key = _material_key(item)
        if not key[0] and not key[1]:
            continue
        target[key] = target.get(key, 0.0) + _material_amount(item) * float(multiplier)


def _material_label(key: tuple[str, str]) -> str:
    item_type, subtype = key
    if item_type and subtype:
        return f"{item_type}/{subtype}"
    return subtype or item_type or "?"


@dataclass(frozen=True)
class ProductionMaterialLine:
    """One material line from an assembler production/disassembly check."""

    type: str
    subtype: str
    required: float
    available: float

    @property
    def missing(self) -> float:
        return max(0.0, self.required - self.available)

    @property
    def ok(self) -> bool:
        return self.missing <= 1e-6

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "subtype": self.subtype,
            "required": self.required,
            "available": self.available,
            "missing": self.missing,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ProductionCapabilityCheck:
    """Detailed answer to: can this assembler currently produce/disassemble an item?"""

    blueprint_id: str
    blueprint_subtype: str
    amount: float
    mode: str
    can_produce: bool
    reason: str
    materials: List[ProductionMaterialLine]
    queue_enabled: Optional[bool] = None
    disassemble_enabled: Optional[bool] = None
    blueprint: Optional[Dict[str, Any]] = None

    @property
    def missing(self) -> List[ProductionMaterialLine]:
        return [line for line in self.materials if not line.ok]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blueprintId": self.blueprint_id,
            "blueprintSubtype": self.blueprint_subtype,
            "amount": self.amount,
            "mode": self.mode,
            "canProduce": self.can_produce,
            "reason": self.reason,
            "queueEnabled": self.queue_enabled,
            "disassembleEnabled": self.disassemble_enabled,
            "materials": [line.to_dict() for line in self.materials],
        }


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


    # -------------------- Blueprint/material checks --------------------
    def queue_enabled(self) -> bool | None:
        telemetry = self.telemetry or {}
        if "queueEnabled" not in telemetry:
            return None
        return bool(telemetry.get("queueEnabled"))

    def set_queue_enabled(self, enabled: bool | None = None) -> int:
        """Set/toggle Space Engineers 'Use Production Queue'.

        This requires server-side plugin support for cmd='queue_enabled'. Older
        plugins will accept the Redis message but will not change telemetry, so
        use :meth:`set_queue_enabled_verified` when you need confirmation.
        """
        result = self._send_bool_command("queue_enabled", enabled, "QueueEnabled", "queueEnabled")
        print(f"Assembler {self.name} ({self.device_id}): set_queue_enabled({enabled}) -> sent {result} messages")
        return result

    def set_queue_enabled_verified(self, enabled: bool, *, timeout: float = 3.0) -> bool:
        current = self.queue_enabled()
        if current is not None and current == bool(enabled):
            return True
        sent = self.set_queue_enabled(bool(enabled))
        if sent <= 0:
            return False
        return self._wait_until(lambda: self.queue_enabled() == bool(enabled), timeout=timeout)

    def get_blueprint(self, blueprint: Any, *, request: bool = False) -> Optional[Dict[str, Any]]:
        """Find a blueprint by full id, blueprint subtype, display name or result subtype."""
        blueprint_id = self.resolve_blueprint_id(blueprint, request=request)
        wanted = str(blueprint or "").strip().lower()
        wanted_subtype = _blueprint_subtype(blueprint_id).lower()

        for entry in self.blueprints or []:
            bp_id = str(entry.get("blueprintId") or "").strip()
            bp_subtype = _blueprint_subtype(bp_id).lower()
            display_name = str(entry.get("displayName") or "").strip().lower()
            if wanted in {bp_id.lower(), bp_subtype, display_name} or wanted_subtype == bp_subtype:
                return dict(entry)

            results = entry.get("results") if isinstance(entry.get("results"), list) else []
            for result in results:
                if not isinstance(result, dict):
                    continue
                result_key = _material_key(result)
                result_subtype = result_key[1].lower()
                if wanted and wanted == result_subtype:
                    return dict(entry)
                if wanted_subtype and wanted_subtype == result_subtype:
                    return dict(entry)
        return None

    def blueprint_output_amount(self, blueprint: Any, *, request: bool = False) -> float:
        entry = self.get_blueprint(blueprint, request=request)
        if not entry:
            return 1.0
        requested = str(blueprint or "").strip().lower()
        requested_subtype = _blueprint_subtype(requested).lower()
        results = entry.get("results") if isinstance(entry.get("results"), list) else []
        fallback = 1.0
        for result in results:
            if not isinstance(result, dict):
                continue
            amount = _material_amount(result)
            if amount > 0.0 and fallback == 1.0:
                fallback = amount
            result_subtype = _material_key(result)[1].lower()
            if requested_subtype and result_subtype == requested_subtype:
                return amount if amount > 0.0 else 1.0
            if requested and result_subtype == requested:
                return amount if amount > 0.0 else 1.0
        return fallback if fallback > 0.0 else 1.0

    def blueprint_requirements(self, blueprint: Any, amount: float = 1.0, *, request: bool = False) -> Dict[tuple[str, str], float]:
        """Return required prerequisite materials for the requested output amount."""
        entry = self.get_blueprint(blueprint, request=request)
        if not entry:
            return {}
        output_amount = self.blueprint_output_amount(blueprint, request=False)
        scale = float(amount) / output_amount if output_amount > 0 else float(amount)
        requirements: Dict[tuple[str, str], float] = {}
        prerequisites = entry.get("prerequisites") if isinstance(entry.get("prerequisites"), list) else []
        _merge_material_amounts(requirements, prerequisites, multiplier=scale)
        return requirements

    def blueprint_results(self, blueprint: Any, amount: float = 1.0, *, request: bool = False) -> Dict[tuple[str, str], float]:
        """Return resulting items for the requested blueprint amount."""
        entry = self.get_blueprint(blueprint, request=request)
        if not entry:
            return {}
        output_amount = self.blueprint_output_amount(blueprint, request=False)
        scale = float(amount) / output_amount if output_amount > 0 else float(amount)
        results: Dict[tuple[str, str], float] = {}
        raw_results = entry.get("results") if isinstance(entry.get("results"), list) else []
        _merge_material_amounts(results, raw_results, multiplier=scale)
        return results

    def _iter_source_items(
        self,
        source: Any = None,
        *,
        source_inventory: str | int | InventorySnapshot | None = None,
        include_grid_inventory: bool = False,
    ) -> List[InventoryItem]:
        if source is None:
            if include_grid_inventory:
                result: List[InventoryItem] = []
                for device in getattr(self.grid, "devices", {}).values():
                    if device is self:
                        input_inventory = self.input_inventory()
                        if input_inventory:
                            result.extend(input_inventory.items)
                        continue
                    if not hasattr(device, "inventory_items"):
                        continue
                    try:
                        result.extend(device.inventory_items())
                    except Exception:
                        pass
                return [InventoryItem(item.type, item.subtype, item.amount, item.display_name) for item in result]

            input_inventory = self.input_inventory()
            if input_inventory:
                return [InventoryItem(item.type, item.subtype, item.amount, item.display_name) for item in input_inventory.items]
            return self.inventory_items()

        if isinstance(source, InventorySnapshot):
            return [InventoryItem(item.type, item.subtype, item.amount, item.display_name) for item in source.items]

        if isinstance(source, InventoryItem):
            return [InventoryItem(source.type, source.subtype, source.amount, source.display_name)]

        if isinstance(source, dict):
            return [InventoryItem.from_payload(source)]

        if hasattr(source, "inventory_items"):
            try:
                return list(source.inventory_items(source_inventory))
            except TypeError:
                return list(source.inventory_items())

        if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
            result: List[InventoryItem] = []
            for entry in source:
                result.extend(self._iter_source_items(entry, source_inventory=source_inventory))
            return result

        raise ValueError(f"Unsupported material source: {source!r}")

    def available_materials(
        self,
        source: Any = None,
        *,
        source_inventory: str | int | InventorySnapshot | None = None,
        include_grid_inventory: bool = False,
    ) -> Dict[tuple[str, str], float]:
        """Aggregate materials by (type, subtype) for production checks.

        By default this uses the assembler input inventory, which matches the
        production-screen idea of stored materials. With include_grid_inventory=True
        it aggregates visible inventories on the loaded grid; that is useful for a
        rough logistics check, but it does not prove conveyor reachability.
        """
        result: Dict[tuple[str, str], float] = {}
        _merge_material_amounts(
            result,
            self._iter_source_items(
                source,
                source_inventory=source_inventory,
                include_grid_inventory=include_grid_inventory,
            ),
        )
        return result

    def production_check(
        self,
        blueprint: Any,
        amount: float = 1.0,
        *,
        source: Any = None,
        source_inventory: str | int | InventorySnapshot | None = None,
        include_grid_inventory: bool = False,
        require_queue_enabled: bool = False,
        request_blueprints: bool = True,
    ) -> ProductionCapabilityCheck:
        """Return the same useful information as red/normal blueprint coloring.

        can_produce=True means all blueprint prerequisites are present in the
        selected material source. It does not guarantee that conveyors are routed
        correctly unless the selected source is exactly the assembler input.
        """
        try:
            blueprint_id = self.resolve_blueprint_id(blueprint, request=request_blueprints)
        except Exception:
            blueprint_id = _canonical_blueprint_id(blueprint)
        bp = self.get_blueprint(blueprint_id, request=request_blueprints)
        if not bp:
            return ProductionCapabilityCheck(
                blueprint_id=blueprint_id,
                blueprint_subtype=_blueprint_subtype(blueprint_id),
                amount=float(amount),
                mode="assemble",
                can_produce=False,
                reason="blueprint_not_found",
                materials=[],
                queue_enabled=self.queue_enabled(),
                disassemble_enabled=self.disassemble_enabled(),
                blueprint=None,
            )

        required = self.blueprint_requirements(blueprint_id, amount, request=False)
        available = self.available_materials(
            source,
            source_inventory=source_inventory,
            include_grid_inventory=include_grid_inventory,
        )
        lines = [
            ProductionMaterialLine(
                type=key[0],
                subtype=key[1],
                required=needed,
                available=available.get(key, 0.0),
            )
            for key, needed in sorted(required.items(), key=lambda pair: _material_label(pair[0]))
        ]
        materials_ok = all(line.ok for line in lines)
        queue_ok = (not require_queue_enabled) or (self.queue_enabled() is not False)
        can_produce = bool(materials_ok and queue_ok)
        if not materials_ok:
            reason = "missing_materials"
        elif not queue_ok:
            reason = "queue_disabled"
        else:
            reason = "ok"
        return ProductionCapabilityCheck(
            blueprint_id=blueprint_id,
            blueprint_subtype=_blueprint_subtype(blueprint_id),
            amount=float(amount),
            mode="assemble",
            can_produce=can_produce,
            reason=reason,
            materials=lines,
            queue_enabled=self.queue_enabled(),
            disassemble_enabled=self.disassemble_enabled(),
            blueprint=bp,
        )

    def can_produce(self, blueprint: Any, amount: float = 1.0, **kwargs: Any) -> bool:
        return self.production_check(blueprint, amount, **kwargs).can_produce

    def disassembly_check(
        self,
        blueprint: Any,
        amount: float = 1.0,
        *,
        source: Any = None,
        source_inventory: str | int | InventorySnapshot | None = None,
        include_grid_inventory: bool = False,
        request_blueprints: bool = True,
    ) -> ProductionCapabilityCheck:
        """Check whether the selected source contains items that can be disassembled."""
        try:
            blueprint_id = self.resolve_blueprint_id(blueprint, request=request_blueprints)
        except Exception:
            blueprint_id = _canonical_blueprint_id(blueprint)
        bp = self.get_blueprint(blueprint_id, request=request_blueprints)
        if not bp:
            return ProductionCapabilityCheck(
                blueprint_id=blueprint_id,
                blueprint_subtype=_blueprint_subtype(blueprint_id),
                amount=float(amount),
                mode="disassemble",
                can_produce=False,
                reason="blueprint_not_found",
                materials=[],
                queue_enabled=self.queue_enabled(),
                disassemble_enabled=self.disassemble_enabled(),
                blueprint=None,
            )

        results = self.blueprint_results(blueprint_id, amount, request=False)
        available = self.available_materials(
            source,
            source_inventory=source_inventory,
            include_grid_inventory=include_grid_inventory,
        )
        lines = [
            ProductionMaterialLine(
                type=key[0],
                subtype=key[1],
                required=needed,
                available=available.get(key, 0.0),
            )
            for key, needed in sorted(results.items(), key=lambda pair: _material_label(pair[0]))
        ]
        can_disassemble = all(line.ok for line in lines)
        return ProductionCapabilityCheck(
            blueprint_id=blueprint_id,
            blueprint_subtype=_blueprint_subtype(blueprint_id),
            amount=float(amount),
            mode="disassemble",
            can_produce=can_disassemble,
            reason="ok" if can_disassemble else "missing_items_to_disassemble",
            materials=lines,
            queue_enabled=self.queue_enabled(),
            disassemble_enabled=self.disassemble_enabled(),
            blueprint=bp,
        )

    def can_disassemble(self, blueprint: Any, amount: float = 1.0, **kwargs: Any) -> bool:
        return self.disassembly_check(blueprint, amount, **kwargs).can_produce

    def assemble(self, blueprint: Any, amount: Optional[float] = None, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        """High-level helper: force assembly mode and add an item to the queue."""
        if verify:
            return self.add_queue_item_verified(blueprint, amount, timeout=timeout, disassemble=False)
        return self.add_queue_item(blueprint, amount, disassemble=False)

    def disassemble(self, blueprint: Any, amount: Optional[float] = None, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        """High-level helper: force disassembly mode and add an item to the queue."""
        if verify:
            return self.add_queue_item_verified(blueprint, amount, timeout=timeout, disassemble=True)
        return self.add_queue_item(blueprint, amount, disassemble=True)

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
