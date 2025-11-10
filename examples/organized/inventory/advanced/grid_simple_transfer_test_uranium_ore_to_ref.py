#!/usr/bin/env python3
"""
Тестовый скрипт для поиска урана на гриде и перемещения его в refinery.
Скрипт находит уран в контейнерах и перемещает его в очистительный завод для обработки.
"""

from __future__ import annotations

import time
from typing import List, Optional

from secontrol.common import prepare_grid, close
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice


def find_containers_with_uranium_ore(grid) -> List[ContainerDevice]:
    """Найти все контейнеры, содержащие уран РУДУ (не слитки)."""
    containers_with_uranium_ore = []

    # Получить все контейнеры на гриде
    all_containers = grid.find_devices_containers()

    print(f"Проверяем {len(all_containers)} контейнеров на наличие уран руды...")

    for container in all_containers:
        items = container.items()
        uranium_ore_amount = 0

        for item in items:
            # Ищем только руду Uranium, а не слитки UraniumIngot
            if item.subtype == "Uranium" and item.subtype != "UraniumIngot":
                # Дополнительная проверка по display_name, если доступно
                display_name = (item.display_name or "").lower()
                if "ore" in display_name or "руда" in display_name or not display_name:
                    uranium_ore_amount += item.amount
                    print(f"  Найдена уран руда: {item.display_name or item.subtype}, количество: {item.amount}")

        if uranium_ore_amount > 0:
            containers_with_uranium_ore.append(container)
            print(f"Найдена уран руда в контейнере '{container.name}' (ID: {container.device_id}): {uranium_ore_amount} ед.")

    print(f"Всего контейнеров с уран рудой: {len(containers_with_uranium_ore)}")
    return containers_with_uranium_ore


def find_refinery(grid) -> Optional[RefineryDevice]:
    """Найти первый доступный refinery на гриде."""
    for device in grid.devices.values():
        if isinstance(device, RefineryDevice):
            print(f"Найден refinery: '{device.name}' (ID: {device.device_id})")
            return device
    return None


def transfer_uranium_to_refinery(containers: List[ContainerDevice], refinery: RefineryDevice) -> int:
    """Переместить уран из контейнеров в refinery."""
    total_transferred = 0

    for container in containers:
        items = container.items()
        for item in items:
            if item.subtype == "Uranium" and item.amount > 0:
                print(f"Перемещаем {item.amount} урана из '{container.name}' в refinery '{refinery.name}'")

                # Перемещаем уран в input inventory refinery
                result = container.move_subtype(refinery.device_id, "Uranium", amount=item.amount)

                if result > 0:
                    print(f"✅ Успешно перемещено {item.amount} урана")
                    total_transferred += item.amount
                else:
                    print(f"❌ Ошибка перемещения урана из '{container.name}'")

                # Небольшая задержка между операциями
                time.sleep(0.5)

    return total_transferred


def add_uranium_to_refinery_queue(refinery: RefineryDevice, amount: int) -> bool:
    """Добавить обработку урана в очередь refinery."""
    if amount <= 0:
        print("Нет урана для добавления в очередь")
        return False

    print(f"Добавляем {amount} урана в очередь refinery для обработки UraniumOreToIngot")

    # Очищаем текущую очередь
    refinery.clear_queue()
    time.sleep(0.5)

    # Добавляем UraniumOreToIngot в очередь
    result = refinery.add_queue_item("UraniumOreToIngot", amount)

    if result > 0:
        print("✅ Успешно добавлено в очередь refinery")
        return True
    else:
        print("❌ Ошибка добавления в очередь refinery")
        return False


def main() -> None:
    """Основная функция скрипта."""
    print("Запуск тестового скрипта перемещения урана...")

    grid = None
    try:
        # Подключаемся к гриду
        grid = prepare_grid()
        print(f"Подключено к гриду: {grid.name} (ID: {grid.grid_id})")

        # Шаг 1: Находим контейнеры с ураном
        containers_with_uranium = find_containers_with_uranium_ore(grid)

        if not containers_with_uranium:
            print("Уран не найден на гриде. Завершение.")
            return

        # Шаг 2: Находим refinery
        refinery = find_refinery(grid)

        if not refinery:
            print("Refinery не найден на гриде. Завершение.")
            return

        # Шаг 3: Перемещаем уран в refinery
        total_transferred = transfer_uranium_to_refinery(containers_with_uranium, refinery)

        if total_transferred > 0:
            print(f"Всего перемещено урана: {total_transferred} ед.")

            # Шаг 4: Добавляем в очередь refinery
            success = add_uranium_to_refinery_queue(refinery, total_transferred)

            if success:
                print("Тест завершен успешно!")
            else:
                print("Ошибка при добавлении в очередь refinery")
        else:
            print("Не удалось переместить уран")

    except Exception as e:
        print(f"Ошибка выполнения скрипта: {e}")
    finally:
        if grid:
            close(grid)
            print("Соединение с гридом закрыто")


if __name__ == "__main__":
    main()
