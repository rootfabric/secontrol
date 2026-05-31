"""Команда для очистки очереди конструктора.

Использование:
  python examples/organized/assembler/intermediate/assembler_queue_clear.py --grid farpost0
"""

from __future__ import annotations

import argparse

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


def find_assembler(grid) -> AssemblerDevice | None:
    """Найти первый доступный конструктор на гриде."""
    for device in grid.devices.values():
        if isinstance(device, AssemblerDevice):
            return device
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Очистить очередь конструктора")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        assembler = find_assembler(grid)
        if not assembler:
            print("Конструктор не найден на гриде")
            raise SystemExit(1)

        print(f"Грид: {grid.name}")
        print(f"Найден конструктор: {assembler.name} (ID: {assembler.device_id})")

        print("Текущая очередь перед очисткой:")
        assembler.print_queue()

        print("\nОчистка очереди...")
        ok = assembler.clear_queue_verified(timeout=3.0)

        if ok:
            print("Очередь очищена и подтверждена телеметрией.")
            assembler.print_queue()
            raise SystemExit(0)

        print("Не удалось подтвердить очистку очереди")
        raise SystemExit(2)
    finally:
        close(grid)


if __name__ == "__main__":
    main()
