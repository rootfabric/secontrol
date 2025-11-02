"""Пример просмотра и управления очередью команд ассемблера из телеметрии.

Использование:
  python assembler_queue_viewer.py        # Просмотр очереди
  python assembler_queue_viewer.py clear  # Очистка очереди
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from secontrol.base_device import BaseDevice
from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


def find_assembler(grid) -> AssemblerDevice | None:
    """Найти первый доступный ассемблер на гриде."""
    for device in grid.devices.values():
        if isinstance(device, AssemblerDevice):
            return device
    return None


def display_queue(assembler: AssemblerDevice) -> None:
    """Отобразить очередь команд ассемблера."""
    queue = assembler.queue()

    if not queue:
        print("Очередь команд пуста")
        return

    print(f"Очередь команд ассемблера '{assembler.name}' (ID: {assembler.device_id}):")
    print("=" * 60)

    for i, item in enumerate(queue):
        print(f"Позиция {i}:")
        print(f"  Index: {item.get('index', 'N/A')}")
        print(f"  Item ID: {item.get('itemId', 'N/A')}")
        print(f"  Blueprint Type: {item.get('blueprintType', 'N/A')}")
        print(f"  Blueprint Subtype: {item.get('blueprintSubtype', 'N/A')}")
        print(f"  Amount: {item.get('amount', 'N/A')}")
        print("-" * 40)

    print(f"Всего элементов в очереди: {len(queue)}")


def display_telemetry_queue(assembler: AssemblerDevice) -> None:
    """Отобразить полную телеметрию с очередью."""
    telemetry = assembler.telemetry
    if not telemetry:
        print("Телеметрия недоступна")
        return

    print("Полная телеметрия ассемблера:")
    print(json.dumps(telemetry, indent=2, ensure_ascii=False))


def main() -> None:
    """Основная функция."""
    # Проверить аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1].lower() == "clear":
        clear_queue_mode()
        return

    # Режим просмотра очереди
    view_queue_mode()


def view_queue_mode() -> None:
    """Режим просмотра очереди."""
    grid = prepare_grid()
    try:
        assembler = find_assembler(grid)
        if not assembler:
            print("Ассемблер не найден на гриде")
            return

        print(f"Найден ассемблер: {assembler.name} (ID: {assembler.device_id})")
        print()

        # Показать очередь через встроенный метод print_queue()
        assembler.print_queue()
        print()

        # Показать очередь через метод queue() с дополнительной информацией
        display_queue(assembler)
        print()

        # Показать полную телеметрию
        display_telemetry_queue(assembler)

    finally:
        close(grid)


def clear_queue_mode() -> None:
    """Режим очистки очереди."""
    grid = prepare_grid()
    try:
        assembler = find_assembler(grid)
        if not assembler:
            print("Ассемблер не найден на гриде")
            return

        print(f"Найден ассемблер: {assembler.name} (ID: {assembler.device_id})")

        # Показать текущую очередь перед очисткой
        print("Текущая очередь перед очисткой:")
        assembler.print_queue()

        # Очистить очередь
        print("\nОчистка очереди...")
        result = assembler.clear_queue()

        if result > 0:
            print(f"Команда очистки отправлена успешно ({result} сообщений)")
            print("Очередь должна быть очищена")
        else:
            print("Не удалось отправить команду очистки")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
