#!/usr/bin/env python3
"""Простой скрипт для вывода имен всех чертежей ассемблера."""

from secontrol.common import close, prepare_grid

def main() -> None:
    """Основная функция."""
    grid = prepare_grid()

    try:
        # Найти ассемблер
        assemblers = []
        for device in grid.devices.values():
            if hasattr(device, 'device_type') and device.device_type == 'assembler':
                assemblers.append(device)

        if not assemblers:
            print("Ассемблеры не найдены")
            return

        assembler = assemblers[0]  # Берем первый найденный

        # Запросить чертежи
        print(f"Запрашиваю чертежи у {assembler.name}...")
        assembler.request_blueprints()

        # Подождать немного
        import time
        time.sleep(5)

        # Вывести имена чертежей
        if assembler.blueprints:
            print(f"\nНайдено {len(assembler.blueprints)} чертежей:")
            print("-" * 50)

            for i, bp in enumerate(assembler.blueprints, 1):
                name = bp.get('displayName', bp.get('blueprintId', 'Unknown'))
                print(f"{i:4d}. {name}")
        else:
            print("Чертежи не загружены")

    finally:
        close(grid)

if __name__ == "__main__":
    main()
