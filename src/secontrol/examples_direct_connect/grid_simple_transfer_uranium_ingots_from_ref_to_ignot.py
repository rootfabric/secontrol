#!/usr/bin/env python3
"""
Тестовый скрипт для поиска refinery с готовыми урановыми слитками и перемещения их в контейнер с тегом 'ignot'.
Скрипт находит refinery с UraniumIngot в output inventory и перемещает их в контейнер с именем, содержащим 'ignot'.
"""

from __future__ import annotations

import time
from typing import List, Optional

from secontrol.common import prepare_grid, close
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice


def find_refinery_with_uranium_ingots(grid) -> Optional[RefineryDevice]:
    """Найти refinery, содержащий урановые слитки (Uranium Ingot) в output inventory."""
    for device in grid.devices.values():
        if isinstance(device, RefineryDevice):
            output_inv = device.output_inventory()
            if output_inv:
                for item in output_inv.items:
                    if item.subtype == "Uranium" and item.type == "MyObjectBuilder_Ingot" and item.amount > 0:
                        print(f"Найден refinery '{device.name}' (ID: {device.device_id}) с {item.amount} Uranium Ingot")
                        return device
    return None


def find_container_with_tag_ignot(grid) -> Optional[ContainerDevice]:
    """Найти контейнер с именем, содержащим 'ignot'."""
    all_containers = grid.find_devices_containers()

    for container in all_containers:
        if container.name and "ingot" in container.name.lower():
            print(f"Найден контейнер '{container.name}' (ID: {container.device_id}) с тегом 'ignot'")
            return container
    return None


def transfer_uranium_ingots_from_refinery_to_container(refinery: RefineryDevice, container: ContainerDevice) -> int:
    """Переместить урановые слитки из refinery в контейнер."""
    output_inv = refinery.output_inventory()
    if not output_inv:
        print("Output inventory refinery пуст")
        return 0

    total_transferred = 0

    for item in output_inv.items:
        if item.subtype == "Uranium" and item.type == "MyObjectBuilder_Ingot" and item.amount > 0:
            print(f"Перемещаем {item.amount} Uranium Ingot из refinery '{refinery.name}' в контейнер '{container.name}'")

            # Перемещаем Uranium Ingot из output inventory refinery в контейнер
            result = refinery.move_subtype(container.device_id, "Uranium", type_id="MyObjectBuilder_Ingot", amount=item.amount, source_inventory="outputInventory")

            if result > 0:
                print(f"✅ Успешно перемещено {item.amount} Uranium Ingot")
                total_transferred += item.amount
            else:
                print(f"❌ Ошибка перемещения Uranium Ingot из refinery '{refinery.name}'")

            # Небольшая задержка между операциями
            time.sleep(0.5)

    return total_transferred


def main() -> None:
    """Основная функция скрипта."""
    print("Запуск тестового скрипта перемещения урановых слитков из refinery в контейнер с тегом 'ignot'...")

    grid = None
    try:
        # Подключаемся к гриду
        grid = prepare_grid()
        print(f"Подключено к гриду: {grid.name} (ID: {grid.grid_id})")

        # Шаг 1: Находим refinery с UraniumIngot
        refinery = find_refinery_with_uranium_ingots(grid)

        if not refinery:
            print("Refinery с UraniumIngot не найден на гриде. Завершение.")
            return

        # Шаг 2: Находим контейнер с тегом 'ignot'
        container = find_container_with_tag_ignot(grid)

        if not container:
            print("Контейнер с тегом 'ignot' не найден на гриде. Завершение.")
            return

        # Шаг 3: Перемещаем UraniumIngot из refinery в контейнер
        total_transferred = transfer_uranium_ingots_from_refinery_to_container(refinery, container)

        if total_transferred > 0:
            print(f"Всего перемещено UraniumIngot: {total_transferred} ед.")
            print("Тест завершен успешно!")
        else:
            print("Не удалось переместить UraniumIngot")

    except Exception as e:
        print(f"Ошибка выполнения скрипта: {e}")
    finally:
        if grid:
            close(grid)
            print("Соединение с гридом закрыто")


if __name__ == "__main__":
    main()
