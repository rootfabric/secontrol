#!/usr/bin/env python3
"""Производство компонентов, которых не хватает Nanobot BuildAndRepair.

Скрипт читает список недостающих компонентов из телеметрии наносварщика,
считает остаток компонентов во всех контейнерах грида, учитывает уже
существующую очередь конструктора и добавляет в очередь только реальный
недостаток.

Примеры:
    python examples/organized/build_and_repair/produce_missing_components.py --grid farpost0 --dry-run
    python examples/organized/build_and_repair/produce_missing_components.py --grid farpost0 --bar-name BuildAndRepairSystem
    python examples/organized/build_and_repair/produce_missing_components.py --grid farpost0 --assembler-name Assembler
    python examples/organized/build_and_repair/produce_missing_components.py --grid farpost0 --ignore-queue
    python examples/organized/build_and_repair/produce_missing_components.py --grid farpost0 --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from typing import Any

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice
from secontrol.devices.build_and_repair_device import normalize_missing_items
from secontrol.devices.container_device import ContainerDevice
from secontrol.item_types import COMPONENT_ITEMS, ItemType, item_matches

SCRIPT_VERSION = "nanobot-produce-missing-components-v1-2026-06-02"
EPSILON = 1e-6

# inventory component subtype -> assembler blueprint subtype.
# Наносварщик отдаёт инвентарные имена компонентов, а конструктору часто
# нужны blueprint-имена с суффиксом Component.
COMPONENT_TO_BLUEPRINT: dict[str, str] = {
    "SteelPlate": "SteelPlate",
    "InteriorPlate": "InteriorPlate",
    "SmallTube": "SmallTube",
    "LargeTube": "LargeTube",
    "Motor": "MotorComponent",
    "Construction": "ConstructionComponent",
    "MetalGrid": "MetalGrid",
    "PowerCell": "PowerCell",
    "RadioCommunication": "RadioCommunicationComponent",
    "Detector": "DetectorComponent",
    "Medical": "MedicalComponent",
    "Display": "Display",
    "BulletproofGlass": "BulletproofGlass",
    "Computer": "ComputerComponent",
    "Reactor": "ReactorComponent",
    "Thrust": "ThrustComponent",
    "GravityGenerator": "GravityGeneratorComponent",
    "SolarCell": "SolarCell",
    "Superconductor": "Superconductor",
    "Girder": "GirderComponent",
    "Explosives": "ExplosivesComponent",
}


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


def normalize_subtype(value: Any) -> str:
    """Return subtype from 'SteelPlate' or 'MyObjectBuilder_Component/SteelPlate'."""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def blueprint_subtype(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def queue_entry_subtype(entry: dict[str, Any]) -> str:
    """Extract blueprint subtype from one assembler queue entry."""
    for key in ("blueprintSubtype", "subtype"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    for key in ("blueprintId", "blueprint", "id", "itemId"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    return ""


def find_component_type(inventory_subtype: str) -> ItemType | None:
    subtype_lower = inventory_subtype.lower()
    for item in COMPONENT_ITEMS:
        if item.subtype.lower() == subtype_lower:
            return item
    return None


def component_display_name(inventory_subtype: str) -> str:
    item_type = find_component_type(inventory_subtype)
    if item_type and item_type.display_name:
        return item_type.display_name
    return inventory_subtype


def count_in_inventory(grid: Any, item_type: ItemType) -> float:
    """Count component amount in all inventory-capable devices of the grid."""
    total = 0.0
    for device in grid.devices.values():
        if not isinstance(device, ContainerDevice):
            continue
        for item in device.items():
            if item_matches(item, item_type):
                total += float(item.amount)
    return total


def find_assembler(grid: Any, name_filter: str = "") -> AssemblerDevice | None:
    assemblers = [device for device in grid.devices.values() if isinstance(device, AssemblerDevice)]
    if name_filter:
        needle = name_filter.lower()
        assemblers = [device for device in assemblers if needle in str(device.name or "").lower()]

    if not assemblers:
        return None

    for assembler in assemblers:
        telemetry = assembler.telemetry or {}
        enabled = bool(telemetry.get("enabled", telemetry.get("isWorking", True)))
        functional = bool(telemetry.get("isFunctional", True))
        if enabled and functional:
            return assembler
    return assemblers[0]


def refresh_assembler_telemetry(assembler: AssemblerDevice, *, timeout: float = 1.0) -> None:
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        pass


def print_assembler_state(assembler: AssemblerDevice) -> None:
    telemetry = assembler.telemetry or {}
    mode = assembler.mode() or "unknown"
    print(f"Конструктор: {assembler.name} ({assembler.device_id})")
    print(
        f"  enabled={telemetry.get('enabled', 'N/A')} "
        f"functional={telemetry.get('isFunctional', 'N/A')} "
        f"working={telemetry.get('isWorking', 'N/A')} "
        f"mode={mode} "
        f"disassemble={telemetry.get('disassembleEnabled', 'N/A')}"
    )
    print(f"  queue_items={len(assembler.queue())} producing={assembler.is_producing()} progress={assembler.current_progress():.3f}")


def prepare_blueprints(assembler: AssemblerDevice) -> None:
    if assembler.wait_for_blueprints(timeout=2.0):
        print(f"  blueprints={len(assembler.blueprints or [])}")
    else:
        print("  blueprints не получены, буду использовать canonical id вида MyObjectBuilder_BlueprintDefinition/<Subtype>")


def planned_queue_amounts(
    assembler: AssemblerDevice,
    *,
    ignore_queue: bool = False,
    count_queue_in_disassemble_mode: bool = False,
) -> dict[str, float]:
    """Return already queued assembler production amounts by blueprint subtype."""
    if ignore_queue:
        return {}

    telemetry = assembler.telemetry or {}
    disassemble_enabled = bool(telemetry.get("disassembleEnabled", False))
    queue = assembler.queue()

    if disassemble_enabled and not count_queue_in_disassemble_mode:
        if queue:
            print(
                "[!] Конструктор сейчас в режиме разбора; существующую очередь "
                "не считаю как запланированное производство."
            )
            print("    Если точно знаешь, что в очереди сборка, запусти с --count-queue-in-disassemble-mode.")
        return {}

    totals: defaultdict[str, float] = defaultdict(float)
    for entry in queue:
        subtype = queue_entry_subtype(entry)
        if not subtype:
            continue
        amount = safe_float(entry.get("amount"), 0.0)
        if amount > EPSILON:
            totals[subtype.lower()] += amount
    return dict(totals)


def find_build_and_repair_devices(grid: Any, name_filter: str = "") -> list[Any]:
    devices = grid.find_devices_by_type("nanobot_build_and_repair")
    if name_filter:
        needle = name_filter.lower()
        devices = [device for device in devices if needle in str(device.name or "").lower()]
    return devices


def read_missing_requirements(grid: Any, *, bar_name: str = "", wait: float = 2.0) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Read and aggregate missing components from Nanobot BuildAndRepair blocks."""
    devices = find_build_and_repair_devices(grid, bar_name)
    if not devices:
        raise RuntimeError("Nanobot BuildAndRepair не найден на гриде")

    requirements: defaultdict[str, float] = defaultdict(float)
    reports: list[dict[str, Any]] = []

    for device in devices:
        if hasattr(device, "missing_report"):
            report = device.missing_report(wait=wait)
            raw = report.get("raw") if isinstance(report.get("raw"), dict) else dict(device.telemetry or {})
            items = report.get("items") if isinstance(report.get("items"), list) else []
        else:
            raw = dict(device.telemetry or {})
            items = normalize_missing_items(raw)
            report = {
                "device_id": device.device_id,
                "name": device.name,
                "source": raw.get("missingComponentsSource"),
                "items": items,
                "projectors_checked": raw.get("nanobotProjectorsChecked") or [],
                "raw": raw,
            }

        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            subtype = normalize_subtype(item.get("name") or item.get("definition_id") or item.get("definitionId") or item.get("key"))
            amount = safe_float(item.get("amount"), 0.0)
            if not subtype or amount <= EPSILON:
                continue
            requirements[subtype] += amount
            normalized_items.append({
                "name": subtype,
                "display_name": component_display_name(subtype),
                "amount": amount,
            })

        reports.append({
            "device_id": report.get("device_id", getattr(device, "device_id", None)),
            "name": report.get("name", getattr(device, "name", None)),
            "source": report.get("source") or raw.get("missingComponentsSource"),
            "items": normalized_items,
            "projectors_checked": report.get("projectors_checked") or raw.get("nanobotProjectorsChecked") or [],
        })

    return dict(requirements), reports


def build_actions(
    grid: Any,
    requirements: dict[str, float],
    queue_amounts: dict[str, float],
    *,
    round_up: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Calculate queue additions required after stock and queue are subtracted."""
    actions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for inventory_subtype in sorted(requirements):
        needed = float(requirements[inventory_subtype])
        item_type = find_component_type(inventory_subtype)
        blueprint = COMPONENT_TO_BLUEPRINT.get(inventory_subtype)

        if not item_type:
            rows.append({
                "inventory_subtype": inventory_subtype,
                "display_name": inventory_subtype,
                "needed": needed,
                "stock": 0.0,
                "queued": 0.0,
                "deficit": needed,
                "produce": 0,
                "status": "unknown_component",
            })
            continue

        if not blueprint:
            rows.append({
                "inventory_subtype": inventory_subtype,
                "display_name": item_type.display_name or inventory_subtype,
                "needed": needed,
                "stock": count_in_inventory(grid, item_type),
                "queued": 0.0,
                "deficit": needed,
                "produce": 0,
                "status": "unknown_blueprint",
            })
            continue

        stock = count_in_inventory(grid, item_type)
        queued = queue_amounts.get(blueprint.lower(), 0.0)
        deficit = needed - stock - queued
        produce = int(math.ceil(deficit - EPSILON)) if round_up and deficit > EPSILON else int(deficit) if deficit > EPSILON else 0
        if produce < 0:
            produce = 0

        status = "OK" if produce <= 0 else "produce"
        row = {
            "inventory_subtype": inventory_subtype,
            "blueprint_subtype": blueprint,
            "display_name": item_type.display_name or inventory_subtype,
            "needed": needed,
            "stock": stock,
            "queued": queued,
            "deficit": deficit,
            "produce": produce,
            "status": status,
        }
        rows.append(row)

        if produce > 0:
            actions.append(row)

    return actions, rows


def print_reports(reports: list[dict[str, Any]]) -> None:
    print("Наносварщики:")
    for report in reports:
        print(f"  {report.get('name')} ({report.get('device_id')})")
        if report.get("source"):
            print(f"    source: {report.get('source')}")
        projectors = report.get("projectors_checked") or []
        for projector in projectors:
            if not isinstance(projector, dict):
                continue
            print(
                "    projector: "
                f"{projector.get('name') or projector.get('id')} | "
                f"projecting={projector.get('isProjecting')} | "
                f"remaining={projector.get('remainingBlocks')} | "
                f"buildable={projector.get('buildableBlocks')}"
            )


def print_plan(rows: list[dict[str, Any]]) -> None:
    print("=" * 80)
    print("Расчёт: требуется по наностройке - склад - очередь конструктора")
    print("=" * 80)
    for row in rows:
        display_name = row["display_name"]
        inventory_subtype = row["inventory_subtype"]
        needed = format_amount(row["needed"])
        stock = format_amount(row["stock"])
        queued = format_amount(row["queued"])
        produce = format_amount(row["produce"])
        status = row["status"]

        if status == "unknown_component":
            print(f"[!] {inventory_subtype}: неизвестный компонент в item_types.py, пропускаю")
            continue
        if status == "unknown_blueprint":
            print(f"[!] {display_name} ({inventory_subtype}): нет маппинга на blueprint конструктора, пропускаю")
            continue

        if row["produce"] > 0:
            suffix = f"добавить {produce}"
        else:
            suffix = "OK"

        print(f"  {display_name} ({inventory_subtype}): нужно {needed}, склад {stock}, очередь {queued} — {suffix}")


def add_actions_to_queue(
    assembler: AssemblerDevice,
    actions: list[dict[str, Any]],
    *,
    dry_run: bool,
    verify: bool,
    verify_timeout: float,
    delay: float,
) -> int:
    if not actions:
        print("\nС учётом склада и очереди компонентов для наностройки хватает.")
        return 0

    print(f"\nТребуется добавить в очередь конструктора: {len(actions)} позиций")

    if not dry_run:
        print("\nПереключаю конструктор в режим сборки (DisassembleEnabled=False)...")
        if verify:
            if assembler.set_disassemble_verified(False, timeout=verify_timeout):
                print("  режим сборки подтверждён")
            else:
                print("  [!] не удалось подтвердить режим сборки; задачи могут попасть в режим разбора")
        else:
            assembler.set_disassemble(False)

    failed: list[tuple[str, int]] = []
    for action in actions:
        blueprint_subtype = str(action["blueprint_subtype"])
        amount = int(action["produce"])
        blueprint_id = assembler.resolve_blueprint_id(blueprint_subtype, request=False)

        if dry_run:
            print(f"  [dry-run] {blueprint_subtype} -> {blueprint_id} x{amount}")
            continue

        print(f"  [>] {blueprint_subtype} -> {blueprint_id} x{amount}")
        if verify:
            ok = assembler.add_queue_item_verified(blueprint_id, amount, timeout=verify_timeout)
            if ok:
                print("      подтверждено телеметрией очереди")
            else:
                print("      НЕ подтверждено: команда ушла, но очередь в телеметрии не изменилась")
                failed.append((blueprint_subtype, amount))
        else:
            sent = assembler.add_queue_item(blueprint_id, amount)
            if sent <= 0:
                failed.append((blueprint_subtype, amount))

        if delay > 0:
            time.sleep(delay)

    if dry_run:
        print("\n[dry-run] Команды не отправлены. Убери --dry-run для запуска.")
        return 0

    print("\nИтоговая очередь конструктора:")
    refresh_assembler_telemetry(assembler, timeout=1.0)
    assembler.print_queue()

    if failed:
        print("\nНе удалось подтвердить добавление задач:")
        for blueprint_subtype, amount in failed:
            print(f"  - {blueprint_subtype} x{amount}")
        return 2

    print("\nЗадачи подтверждённо добавлены в очередь конструктора.")
    return 0


def run(args: argparse.Namespace) -> int:
    grid = prepare_grid(args.grid, auto_wake=True)
    try:
        grid.refresh_devices()

        assembler = find_assembler(grid, args.assembler_name)
        if not assembler:
            if args.assembler_name:
                print(f"Конструктор не найден на гриде по фильтру: {args.assembler_name}")
            else:
                print("Конструктор не найден на гриде")
            return 1

        refresh_assembler_telemetry(assembler, timeout=1.0)

        print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
        print(f"Грид: {grid.name} ({grid.grid_id})")
        print_assembler_state(assembler)
        prepare_blueprints(assembler)

        requirements, reports = read_missing_requirements(grid, bar_name=args.bar_name, wait=args.wait)
        print_reports(reports)

        if not requirements:
            print("\nНаносварщик не сообщает недостающие компоненты. Производство не требуется.")
            return 0

        queue_amounts = planned_queue_amounts(
            assembler,
            ignore_queue=args.ignore_queue,
            count_queue_in_disassemble_mode=args.count_queue_in_disassemble_mode,
        )
        if args.ignore_queue:
            print("  очередь конструктора не учитывается (--ignore-queue)")
        else:
            print(f"  учитываю очередь сборки: {format_amount(sum(queue_amounts.values()))} шт. по известным blueprint-ам")

        actions, rows = build_actions(grid, requirements, queue_amounts)
        print_plan(rows)

        if args.json:
            payload = {
                "grid": {"name": grid.name, "id": grid.grid_id},
                "assembler": {"name": assembler.name, "id": assembler.device_id},
                "nanobots": reports,
                "rows": rows,
                "actions": actions,
            }
            print("\nJSON:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        return add_actions_to_queue(
            assembler,
            actions,
            dry_run=args.dry_run,
            verify=not args.no_verify,
            verify_timeout=args.verify_timeout,
            delay=args.delay,
        )
    finally:
        close(grid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Доделать компоненты, которых не хватает Nanobot BuildAndRepair")
    parser.add_argument("--grid", required=True, help="Имя или ID грида базы")
    parser.add_argument("--bar-name", "--name", default="", help="Фильтр по имени Nanobot BuildAndRepair")
    parser.add_argument("--assembler-name", default="", help="Фильтр по имени конструктора")
    parser.add_argument("--wait", type=float, default=2.0, help="Сколько секунд ждать свежую телеметрию наносварщика")
    parser.add_argument("--dry-run", action="store_true", help="Показать расчёт, но не отправлять команды")
    parser.add_argument("--json", action="store_true", help="Показать JSON с расчётом")
    parser.add_argument("--no-verify", action="store_true", help="Не ждать подтверждения очереди из телеметрии")
    parser.add_argument("--verify-timeout", type=float, default=3.0, help="Сколько секунд ждать изменение очереди после каждой команды")
    parser.add_argument("--delay", type=float, default=0.2, help="Пауза между командами добавления в очередь")
    parser.add_argument("--ignore-queue", action="store_true", help="Не учитывать существующую очередь конструктора")
    parser.add_argument(
        "--count-queue-in-disassemble-mode",
        action="store_true",
        help="Учитывать существующую очередь даже если сейчас включён режим разбора",
    )
    args = parser.parse_args()

    try:
        code = run(args)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
        code = 130
    except Exception as exc:
        print(f"Ошибка: {exc}")
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
