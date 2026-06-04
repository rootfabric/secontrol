#!/usr/bin/env python3
"""Shared helpers for multi-assembler production scripts."""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any, Iterable

from secontrol.devices.assembler_device import AssemblerDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.item_types import COMPONENT_ITEMS, INGOT_ITEMS, item_matches

EPSILON = 1e-6

BLUEPRINT_TO_INVENTORY = {
    "SteelPlate": "SteelPlate",
    "InteriorPlate": "InteriorPlate",
    "SmallTube": "SmallTube",
    "LargeTube": "LargeTube",
    "MotorComponent": "Motor",
    "ConstructionComponent": "Construction",
    "MetalGrid": "MetalGrid",
    "PowerCell": "PowerCell",
    "RadioCommunicationComponent": "RadioCommunication",
    "DetectorComponent": "Detector",
    "MedicalComponent": "Medical",
    "Display": "Display",
    "BulletproofGlass": "BulletproofGlass",
    "ComputerComponent": "Computer",
    "ReactorComponent": "Reactor",
    "ThrustComponent": "Thrust",
    "GravityGeneratorComponent": "GravityGenerator",
    "SolarCell": "SolarCell",
    "Superconductor": "Superconductor",
    "GirderComponent": "Girder",
    "ExplosivesComponent": "Explosives",
    "Canvas": "Canvas",
}

INVENTORY_TO_BLUEPRINT = {value.lower(): key for key, value in BLUEPRINT_TO_INVENTORY.items()}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_amount(value: float) -> str:
    value = float(value)
    if math.isclose(value, round(value), abs_tol=EPSILON):
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def blueprint_subtype(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def queue_entry_subtype(entry: dict[str, Any]) -> str:
    for key in ("blueprintSubtype", "subtype"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    for key in ("blueprintId", "blueprint", "id", "itemId"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    return ""


def find_item_type(inventory_subtype: str):
    for item in COMPONENT_ITEMS:
        if item.subtype == inventory_subtype:
            return item
    for item in INGOT_ITEMS:
        if item.subtype == inventory_subtype:
            return item
    return None


def count_in_inventory(grid: Any, item_type: Any) -> float:
    total = 0.0
    for device in grid.devices.values():
        if not isinstance(device, ContainerDevice):
            continue
        for item in device.items():
            if item_matches(item, item_type):
                total += float(item.amount)
    return total


def find_assemblers(grid: Any, *, name_filter: str = "", only_ready: bool = True) -> list[AssemblerDevice]:
    assemblers = [device for device in grid.devices.values() if isinstance(device, AssemblerDevice)]
    if name_filter:
        needle = name_filter.lower()
        assemblers = [a for a in assemblers if needle in str(a.name or "").lower()]

    if not only_ready:
        return assemblers

    ready: list[AssemblerDevice] = []
    for assembler in assemblers:
        telemetry = assembler.telemetry or {}
        enabled = bool(telemetry.get("enabled", telemetry.get("isWorking", True)))
        functional = bool(telemetry.get("isFunctional", True))
        if enabled and functional:
            ready.append(assembler)
    return ready or assemblers


def refresh_assembler_telemetry(assembler: AssemblerDevice, *, timeout: float = 1.0) -> None:
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        pass


def refresh_assemblers(assemblers: Iterable[AssemblerDevice], *, timeout: float = 1.0) -> None:
    for assembler in assemblers:
        refresh_assembler_telemetry(assembler, timeout=timeout)


def print_assembler_state(assembler: AssemblerDevice) -> None:
    telemetry = assembler.telemetry or {}
    mode = assembler.mode() or "unknown"
    print(
        f"  {assembler.name} ({assembler.device_id}): "
        f"enabled={telemetry.get('enabled', 'N/A')} "
        f"functional={telemetry.get('isFunctional', 'N/A')} "
        f"working={telemetry.get('isWorking', 'N/A')} "
        f"mode={mode} "
        f"disassemble={telemetry.get('disassembleEnabled', 'N/A')} "
        f"queue={len(assembler.queue())}"
    )


def planned_queue_amounts_for_assembler(
    assembler: AssemblerDevice,
    *,
    ignore_queue: bool = False,
    count_queue_in_disassemble_mode: bool = False,
) -> dict[str, float]:
    if ignore_queue:
        return {}

    telemetry = assembler.telemetry or {}
    if bool(telemetry.get("disassembleEnabled", False)) and not count_queue_in_disassemble_mode:
        return {}

    totals: defaultdict[str, float] = defaultdict(float)
    for entry in assembler.queue():
        subtype = queue_entry_subtype(entry)
        if not subtype:
            continue
        amount = safe_float(entry.get("amount"), 0.0)
        if amount > EPSILON:
            totals[subtype.lower()] += amount
    return dict(totals)


def planned_queue_amounts_all(
    assemblers: Iterable[AssemblerDevice],
    *,
    ignore_queue: bool = False,
    count_queue_in_disassemble_mode: bool = False,
) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for assembler in assemblers:
        for subtype, amount in planned_queue_amounts_for_assembler(
            assembler,
            ignore_queue=ignore_queue,
            count_queue_in_disassemble_mode=count_queue_in_disassemble_mode,
        ).items():
            totals[subtype] += amount
    return dict(totals)


def component_to_blueprint_subtype(component_subtype: str) -> str:
    text = str(component_subtype or "").strip()
    if not text:
        return ""
    mapped = INVENTORY_TO_BLUEPRINT.get(text.lower())
    if mapped:
        return mapped
    if text.endswith("Component"):
        return text
    candidate = f"{text}Component"
    if candidate in BLUEPRINT_TO_INVENTORY:
        return candidate
    return text


def blueprint_to_inventory_subtype(blueprint_subtype: str) -> str:
    text = str(blueprint_subtype or "").strip()
    return BLUEPRINT_TO_INVENTORY.get(text, text)


def prepare_assemblers_for_build(
    assemblers: Iterable[AssemblerDevice],
    *,
    verify: bool = True,
    verify_timeout: float = 3.0,
    enable_conveyor: bool = True,
) -> None:
    for assembler in assemblers:
        if verify:
            ok = assembler.set_disassemble_verified(False, timeout=verify_timeout)
            print(f"  {assembler.name}: режим сборки {'OK' if ok else 'НЕ подтвержден'}")
            if enable_conveyor:
                conveyor_ok = assembler.set_use_conveyor_verified(True, timeout=verify_timeout)
                print(f"  {assembler.name}: конвейер {'OK' if conveyor_ok else 'НЕ подтвержден'}")
        else:
            assembler.set_disassemble(False)
            if enable_conveyor:
                assembler.set_use_conveyor(True)


def build_balanced_plan(
    assemblers: list[AssemblerDevice],
    actions: Iterable[tuple[str, int]],
) -> list[tuple[AssemblerDevice, str, int]]:
    if not assemblers:
        return []

    planned_load: dict[str, float] = {}
    for assembler in assemblers:
        planned_load[assembler.device_id] = sum(
            safe_float(entry.get("amount"), 0.0) for entry in assembler.queue()
        )

    plan: list[tuple[AssemblerDevice, str, int]] = []
    for bp_subtype, raw_amount in actions:
        amount = int(math.ceil(float(raw_amount) - EPSILON))
        if amount <= 0:
            continue

        remaining = amount
        while remaining > 0:
            assembler = min(assemblers, key=lambda a: planned_load.get(a.device_id, 0.0))
            chunk = max(1, int(math.ceil(remaining / len(assemblers))))
            if chunk > remaining:
                chunk = remaining
            plan.append((assembler, bp_subtype, chunk))
            planned_load[assembler.device_id] = planned_load.get(assembler.device_id, 0.0) + chunk
            remaining -= chunk
    return plan


def add_plan_to_assemblers(
    plan: Iterable[tuple[AssemblerDevice, str, int]],
    *,
    verify: bool = True,
    verify_timeout: float = 3.0,
    delay: float = 0.15,
) -> list[tuple[str, str, int]]:
    failed: list[tuple[str, str, int]] = []
    for assembler, bp_subtype, amount in plan:
        blueprint_id = assembler.resolve_blueprint_id(bp_subtype, request=True)
        print(f"  [>] {assembler.name}: {bp_subtype} -> {blueprint_id} x{amount}")
        if verify:
            ok = assembler.add_queue_item_verified(blueprint_id, amount, timeout=verify_timeout)
            if not ok:
                print("      НЕ подтверждено телеметрией")
                failed.append((assembler.name or assembler.device_id, bp_subtype, amount))
            else:
                print("      подтверждено")
        else:
            sent = assembler.add_queue_item(blueprint_id, amount)
            if sent <= 0:
                failed.append((assembler.name or assembler.device_id, bp_subtype, amount))
        if delay > 0:
            time.sleep(delay)
    return failed
