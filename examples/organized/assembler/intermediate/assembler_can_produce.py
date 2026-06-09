"""Проверить, может ли конструктор произвести или разобрать предмет.

Примеры:
  python examples/organized/assembler/intermediate/assembler_can_produce.py --grid farpost0 SteelPlate 10
  python examples/organized/assembler/intermediate/assembler_can_produce.py --grid farpost0 InteriorPlate 100 --grid-inventory
  python examples/organized/assembler/intermediate/assembler_can_produce.py --grid farpost0 SteelPlate 5 --disassemble
  python examples/organized/assembler/intermediate/assembler_can_produce.py --grid farpost0 Motor 20 --require-queue-enabled
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice, ProductionCapabilityCheck


def find_assemblers(grid: Any) -> list[AssemblerDevice]:
    target_grid_id = str(getattr(grid, "grid_id", "") or "")
    result: list[AssemblerDevice] = []
    for device in grid.devices.values():
        if not isinstance(device, AssemblerDevice):
            continue
        if str(getattr(device, "grid_id", "") or "") != target_grid_id:
            continue
        telemetry = getattr(device, "telemetry", None) or {}
        tel_grid = str(telemetry.get("gridId", "") or "")
        if tel_grid and tel_grid != target_grid_id:
            continue
        result.append(device)
    return result


def choose_assembler(grid: Any, assembler_id: str | None = None, name: str | None = None) -> AssemblerDevice | None:
    assemblers = find_assemblers(grid)
    if not assemblers:
        return None

    if assembler_id:
        wanted = str(assembler_id).strip()
        return next((assembler for assembler in assemblers if str(assembler.device_id) == wanted), None)

    if name:
        wanted_name = name.strip().lower()
        return next((assembler for assembler in assemblers if wanted_name in str(assembler.name or "").lower()), None)

    for assembler in assemblers:
        telemetry = assembler.telemetry or {}
        enabled = bool(telemetry.get("enabled", True))
        functional = bool(telemetry.get("isFunctional", True))
        if enabled and functional:
            return assembler
    return assemblers[0]


def refresh(assembler: AssemblerDevice, timeout: float = 1.0) -> None:
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        pass


def print_check(check: ProductionCapabilityCheck) -> None:
    action = "разбор" if check.mode == "disassemble" else "сборка"
    print(f"Режим: {action}")
    print(f"Чертёж: {check.blueprint_subtype} ({check.blueprint_id})")
    print(f"Количество: {check.amount:g}")
    print(f"Итог: {'можно' if check.can_produce else 'нельзя'} ({check.reason})")
    print(f"queueEnabled={check.queue_enabled} disassembleEnabled={check.disassemble_enabled}")

    if not check.materials:
        print("Материалы: нет данных")
        return

    print("\nМатериалы:")
    for line in check.materials:
        status = "OK" if line.ok else "MISS"
        print(
            f"  [{status}] {line.type}/{line.subtype}: "
            f"required={line.required:.3f}, available={line.available:.3f}, missing={line.missing:.3f}"
        )


def run(args: argparse.Namespace) -> int:
    grid = prepare_grid(args.grid)
    try:
        assembler = choose_assembler(grid, args.assembler_id, args.name)
        if assembler is None:
            print("Конструктор не найден на гриде")
            return 1

        refresh(assembler, timeout=args.timeout)
        print(f"Грид: {grid.name}")
        print(f"Конструктор: {assembler.name} ({assembler.device_id})")

        if args.disassemble:
            check = assembler.disassembly_check(
                args.blueprint,
                args.amount,
                include_grid_inventory=args.grid_inventory,
                request_blueprints=True,
            )
        else:
            check = assembler.production_check(
                args.blueprint,
                args.amount,
                include_grid_inventory=args.grid_inventory,
                require_queue_enabled=args.require_queue_enabled,
                request_blueprints=True,
            )

        if args.json:
            print(json.dumps(check.to_dict(), indent=2, ensure_ascii=False))
        else:
            print_check(check)

        if check.reason == "blueprint_not_found":
            return 3
        return 0 if check.can_produce else 2
    finally:
        close(grid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверить доступность сборки/разбора в конструкторе")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--assembler-id", help="ID конкретного конструктора")
    parser.add_argument("--name", help="Часть имени конструктора")
    parser.add_argument("--timeout", type=float, default=3.0, help="Сколько секунд ждать телеметрию")
    parser.add_argument("--grid-inventory", action="store_true", help="Считать материалы во всех видимых инвентарях грида, а не только во входе конструктора")
    parser.add_argument("--require-queue-enabled", action="store_true", help="Считать queueEnabled=false блокирующим фактором")
    parser.add_argument("--disassemble", action="store_true", help="Проверять наличие предметов для разбора")
    parser.add_argument("--json", action="store_true", help="Вывести результат JSON")
    parser.add_argument("blueprint", help="Subtype или полный blueprintId, например SteelPlate")
    parser.add_argument("amount", type=float, nargs="?", default=1.0, help="Количество")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
