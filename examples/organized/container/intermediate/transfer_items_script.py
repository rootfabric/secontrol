#!/usr/bin/env python3
"""
Простой скрипт для переноса всех предметов из контейнера с названием "1" в контейнер с названием "2" на текущем гриде.
"""

from __future__ import annotations

import time

from secontrol.devices.container_device import ContainerDevice
from secontrol.common import prepare_grid


def main() -> None:
    print("Получаем текущий грид...")

    grid = prepare_grid("95416675777277504")

    print(f"Работаем с гридом: {grid.name} (ID: {grid.grid_id})")

    containers = list(grid.find_devices_by_type(ContainerDevice))
    print(f"Найдено {len(containers)} контейнер(ов) на гриде")

    # Найти контейнеры с именами "1" и "2"
    source_container = None
    target_container = None

    for container in containers:
        if container.name == "1":
            source_container = container
        elif container.name == "2":
            target_container = container

    if source_container is None:
        print("Контейнер с названием '1' не найден")
        return

    if target_container is None:
        print("Контейнер с названием '2' не найден")
        return

    print(f"Найден источник: {source_container.name} (ID: {source_container.device_id})")
    print(f"Найден цель: {target_container.name} (ID: {target_container.device_id})")

    # Получить предметы источника для отчета
    source_items = source_container.items()
    if not source_items:
        print("В контейнере '1' нет предметов для переноса")
        return

    print(f"Переносим {len(source_items)} тип(ов) предметов из контейнера '1' в контейнер '2'")

    # Перенести все предметы
    try:
        result = source_container.move_all(target_container)
        if result > 0:
            print("Предметы успешно перенесены")
        else:
            print("Не удалось перенести предметы")
    except Exception as exc:
        print(f"Ошибка при переносе предметов: {exc}")
        return

    # Обновить телеметрию
    time.sleep(0.5)
    source_container.send_command({"cmd": "update"})
    target_container.send_command({"cmd": "update"})

    print("Перенос завершен")


if __name__ == "__main__":
    main()
