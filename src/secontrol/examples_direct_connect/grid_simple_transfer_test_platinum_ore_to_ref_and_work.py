#!/usr/bin/env python3
"""
Тестовый скрипт для поиска платины на гриде и перемещения её в refinery.
Скрипт находит платину в контейнерах и перемещает её в очистительный завод для обработки.
"""

from __future__ import annotations

import time
from typing import List, Optional

from secontrol.common import prepare_grid, close
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.item_types import item_matches, Item


def find_containers_with_platinum_ore(grid) -> List[ContainerDevice]:
    """Найти все контейнеры, содержащие платиновую РУДУ (не слитки)."""
    containers_with_platinum_ore = []

    # Получить все контейнеры на гриде
    all_containers = grid.find_devices_containers()

    print(f"Проверяем {len(all_containers)} контейнеров на наличие платиновой руды...")

    for container in all_containers:
        items = container.items()
        platinum_ore_amount = 0

        for item in items:
            # Ищем только руду Platinum, а не слитки PlatinumIngot
            if item_matches(item, Item.PlatinumOre):
                # Дополнительная проверка по display_name, если доступно
                display_name = (item.display_name or "").lower()
                if "ore" in display_name or "руда" in display_name or not display_name:
                    platinum_ore_amount += item.amount
                    print(f"  Найдена платина руда: {item.display_name or item.subtype}, количество: {item.amount}")

        if platinum_ore_amount > 0:
            containers_with_platinum_ore.append(container)
            print(f"Найдена платина руда в контейнере '{container.name}' (ID: {container.device_id}): {platinum_ore_amount} ед.")

    print(f"Всего контейнеров с платиновой рудой: {len(containers_with_platinum_ore)}")
    return containers_with_platinum_ore


def find_refinery(grid) -> Optional[RefineryDevice]:
    """Найти первый доступный refinery на гриде."""
    for device in grid.devices.values():
        if isinstance(device, RefineryDevice):
            print(f"Найден refinery: '{device.name}' (ID: {device.device_id})")
            return device
    return None


def transfer_platinum_to_refinery(containers: List[ContainerDevice], refinery: RefineryDevice) -> int:
    """Переместить платину из контейнеров в refinery."""
    total_transferred = 0

    for container in containers:
        items = container.items()
        for item in items:
            if item_matches(item, Item.PlatinumOre) and item.amount > 0:
                print(f"Перемещаем {item.amount} платины из '{container.name}' в refinery '{refinery.name}'")

                # Перемещаем платину в input inventory refinery
                result = container.move_subtype(refinery.device_id, "Platinum", type_id="MyObjectBuilder_Ore", amount=item.amount)

                if result > 0:
                    print(f"✅ Успешно перемещено {item.amount} платины")
                    total_transferred += item.amount
                else:
                    print(f"❌ Ошибка перемещения платины из '{container.name}'")

                # Небольшая задержка между операциями
                time.sleep(0.5)

    return total_transferred


def add_platinum_to_refinery_queue(refinery: RefineryDevice, amount: int) -> bool:
    """Добавить обработку платины в очередь refinery."""
    if amount <= 0:
        print("Нет платины для добавления в очередь")
        return False

    print(f"Добавляем {amount} платины в очередь refinery для обработки PlatinumOreToIngot")

    # Очищаем текущую очередь
    refinery.clear_queue()
    time.sleep(0.5)

    # Добавляем PlatinumOreToIngot в очередь
    result = refinery.add_queue_item("PlatinumOreToIngot", amount)

    if result > 0:
        print("✅ Успешно добавлено в очередь refinery")
        return True
    else:
        print("❌ Ошибка добавления в очередь refinery")
        return False


def main() -> None:
    """Основная функция скрипта."""
    print("Запуск тестового скрипта перемещения платины...")

    grid = None
    try:
        # Подключаемся к гриду
        grid = prepare_grid()
        print(f"Подключено к гриду: {grid.name} (ID: {grid.grid_id})")

        # Шаг 1: Находим контейнеры с платиной
        containers_with_platinum = find_containers_with_platinum_ore(grid)

        if not containers_with_platinum:
            print("Платина не найдена на гриде. Завершение.")
            return

        # Шаг 2: Находим refinery
        refinery = find_refinery(grid)

        if not refinery:
            print("Refinery не найден на гриде. Завершение.")
            return

        # Шаг 3: Перемещаем платину в refinery
        total_transferred = transfer_platinum_to_refinery(containers_with_platinum, refinery)

        if total_transferred > 0:
            print(f"Всего перемещено платины: {total_transferred} ед.")

            # Шаг 4: Добавляем в очередь refinery
            success = add_platinum_to_refinery_queue(refinery, total_transferred)

            if success:
                print("Тест завершен успешно!")
            else:
                print("Ошибка при добавлении в очередь refinery")
        else:
            print("Не удалось переместить платину")

    except Exception as e:
        print(f"Ошибка выполнения скрипта: {e}")
    finally:
        if grid:
            close(grid)
            print("Соединение с гридом закрыто")


if __name__ == "__main__":
    main()
