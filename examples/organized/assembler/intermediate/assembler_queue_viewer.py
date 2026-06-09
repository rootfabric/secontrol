"""Просмотр и очистка очереди конструктора.

Использование:
  python examples/organized/assembler/intermediate/assembler_queue_viewer.py --grid farpost0
  python examples/organized/assembler/intermediate/assembler_queue_viewer.py --grid farpost0 --full
  python examples/organized/assembler/intermediate/assembler_queue_viewer.py --grid farpost0 clear
"""

from __future__ import annotations

import argparse
import json

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


def find_assembler(grid) -> AssemblerDevice | None:
    """Найти первый конструктор, принадлежащий самому гриду (исключая subgrid'ы)."""
    target_grid_id = str(getattr(grid, "grid_id", "") or "")
    for device in grid.devices.values():
        if not isinstance(device, AssemblerDevice):
            continue
        if str(getattr(device, "grid_id", "") or "") != target_grid_id:
            continue
        telemetry = getattr(device, "telemetry", None) or {}
        tel_grid = str(telemetry.get("gridId", "") or "")
        if tel_grid and tel_grid != target_grid_id:
            continue
        return device
    return None


def display_queue(assembler: AssemblerDevice) -> None:
    """Отобразить очередь конструктора."""
    queue = assembler.queue()

    if not queue:
        print("Очередь конструктора пуста")
        return

    print(f"Очередь конструктора '{assembler.name}' (ID: {assembler.device_id}):")
    print("=" * 60)

    for i, item in enumerate(queue):
        print(f"Позиция {i}:")
        print(f"  Index: {item.get('index', i)}")
        print(f"  Item ID: {item.get('itemId', 'N/A')}")
        print(f"  Blueprint Type: {item.get('blueprintType', 'N/A')}")
        print(f"  Blueprint Subtype: {item.get('blueprintSubtype', 'N/A')}")
        print(f"  Blueprint ID: {item.get('blueprintId', 'N/A')}")
        print(f"  Amount: {item.get('amount', 'N/A')}")
        print("-" * 40)

    print(f"Всего элементов в очереди: {len(queue)}")


def display_telemetry_queue(assembler: AssemblerDevice) -> None:
    """Отобразить полную телеметрию с очередью."""
    telemetry = assembler.telemetry
    if not telemetry:
        print("Телеметрия недоступна")
        return

    print("Полная телеметрия конструктора:")
    print(json.dumps(telemetry, indent=2, ensure_ascii=False))


def view_queue_mode(grid_name: str, *, full: bool = False) -> int:
    """Режим просмотра очереди."""
    grid = prepare_grid(grid_name)
    try:
        assembler = find_assembler(grid)
        if not assembler:
            print("Конструктор не найден на гриде")
            return 1

        print(f"Грид: {grid.name}")
        print(f"Найден конструктор: {assembler.name} (ID: {assembler.device_id})")
        print()

        try:
            assembler.wait_for_telemetry(timeout=1.0, wait_for_new=True, need_update=True)
        except Exception:
            pass

        assembler.print_queue()
        print()
        display_queue(assembler)

        if full:
            print()
            display_telemetry_queue(assembler)
        return 0
    finally:
        close(grid)


def clear_queue_mode(grid_name: str) -> int:
    """Режим очистки очереди."""
    grid = prepare_grid(grid_name)
    try:
        assembler = find_assembler(grid)
        if not assembler:
            print("Конструктор не найден на гриде")
            return 1

        print(f"Грид: {grid.name}")
        print(f"Найден конструктор: {assembler.name} (ID: {assembler.device_id})")

        print("Текущая очередь перед очисткой:")
        assembler.print_queue()

        print("\nОчистка очереди...")
        ok = assembler.clear_queue_verified(timeout=3.0)

        if ok:
            print("Очередь очищена и подтверждена телеметрией.")
            assembler.print_queue()
            return 0

        print("Не удалось подтвердить очистку очереди")
        return 2
    finally:
        close(grid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Просмотр и очистка очереди конструктора")
    parser.add_argument("command", nargs="?", choices=["view", "clear"], default="view", help="Действие")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--full", action="store_true", help="Показать полную телеметрию")
    args = parser.parse_args()

    if args.command == "clear":
        raise SystemExit(clear_queue_mode(args.grid))
    raise SystemExit(view_queue_mode(args.grid, full=args.full))


if __name__ == "__main__":
    main()
