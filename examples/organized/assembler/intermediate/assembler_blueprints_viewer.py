"""Пример просмотра доступных чертежей на всех конструкторах грида."""

from __future__ import annotations

import time
from typing import List

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


def print_blueprint_info(assembler: AssemblerDevice) -> None:
    """Вывести информацию о чертежах конструктора."""
    print(f"\n=== Assembler: {assembler.name} ({assembler.device_id}) ===")

    if assembler.blueprints is None:
        print("Чертежи не загружены")
        return

    print(f"Всего чертежей: {len(assembler.blueprints)}")

    for i, bp in enumerate(assembler.blueprints[:5000]):  # Показать первые 5
        print(f"\n[{i+1}] {bp.get('displayName', bp.get('blueprintId', 'Unknown'))}")
        print(f"   ID: {bp.get('blueprintId', 'N/A')}")

        # Результаты
        results = bp.get('results', [])
        if results:
            print("   Результаты:")
            for result in results:
                amount = result.get('amount', 1)
                if 'item_type' in result:
                    item_type = result['item_type']
                    print(f"     - {item_type.display_name} x{amount}")
                else:
                    subtype = result.get('subtype', 'Unknown')
                    print(f"     - {subtype} x{amount}")

        # Требования
        prereqs = bp.get('prerequisites', [])
        if prereqs:
            print("   Требования:")
            for prereq in prereqs:
                amount = prereq.get('amount', 1)
                if 'item_type' in prereq:
                    item_type = prereq['item_type']
                    print(f"     - {item_type.display_name} x{amount}")
                else:
                    subtype = prereq.get('subtype', 'Unknown')
                    print(f"     - {subtype} x{amount}")

    if len(assembler.blueprints) > 5000:
        print(f"\n... и еще {len(assembler.blueprints) - 5} чертежей")


def main() -> None:
    """Основная функция."""
    grid = prepare_grid()

    try:
        # Найти все конструкторы
        assemblers: List[AssemblerDevice] = []
        finder = getattr(grid, "find_devices_by_type", None)
        if callable(finder):
            assemblers = [
                device
                for device in finder("assembler")
                if isinstance(device, AssemblerDevice)
            ]
        else:
            assemblers = [
                device
                for device in grid.devices.values()
                if isinstance(device, AssemblerDevice)
            ]

        if not assemblers:
            print("Конструкторы не найдены на гриде")
            return

        print(f"Найдено конструкторов: {len(assemblers)}")

        # Запросить чертежи у всех конструкторов
        print("\nЗапрашиваю чертежи...")
        for assembler in assemblers:
            assembler.request_blueprints()

        # Подождать немного для получения телеметрии
        print("Жду получения данных...")
        time.sleep(1)

        # Вывести информацию о чертежах
        for assembler in assemblers:
            print_blueprint_info(assembler)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
