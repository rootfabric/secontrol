"""Команда для очистки очереди команд ассемблера."""

from __future__ import annotations

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


def find_assembler(grid) -> AssemblerDevice | None:
    """Найти первый доступный ассемблер на гриде."""
    for device in grid.devices.values():
        if isinstance(device, AssemblerDevice):
            return device
    return None


def main() -> None:
    """Основная функция для очистки очереди."""
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
