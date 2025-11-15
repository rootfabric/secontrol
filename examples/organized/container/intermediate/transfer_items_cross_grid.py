#!/usr/bin/env python3
"""
Скрипт для переноса всех предметов из контейнера с названием "1" на одном гриде в контейнер с названием "2" на другом гриде.
"""

from __future__ import annotations

import time

from secontrol.devices.container_device import ContainerDevice
from secontrol.common import resolve_owner_id, prepare_grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    print("Получаем список гридов...")

    owner_id = resolve_owner_id()
    client = RedisEventClient()

    grids = client.list_grids(owner_id)
    if not grids:
        print("Гриды не найдены.")
        return

    # Фильтровать не-субгриды
    from secontrol.common import _is_subgrid
    non_subgrids = [g for g in grids if not _is_subgrid(g)]
    print(f"Найдено {len(non_subgrids)} основных гридов.")

    if len(non_subgrids) < 2:
        print("Нужно как минимум 2 грида для межгридового переноса.")
        return

    # Взять первые два грида
    source_grid_info = non_subgrids[0]
    target_grid_info = non_subgrids[1]

    print(f"Источник: {source_grid_info.get('name', 'unnamed')} (ID: {source_grid_info.get('id')})")
    print(f"Цель: {target_grid_info.get('name', 'unnamed')} (ID: {target_grid_info.get('id')})")

    # Получить гриды
    source_grid = prepare_grid(client, str(source_grid_info.get('id')))
    target_grid = prepare_grid(client, str(target_grid_info.get('id')))

    # Найти контейнер "1" на source_grid
    source_container = None
    for container in source_grid.find_devices_by_type(ContainerDevice):
        if container.name == "1":
            source_container = container
            break

    if source_container is None:
        print("Контейнер с названием '1' не найден на исходном гриде")
        return

    # Найти контейнер "2" на target_grid
    target_container = None
    for container in target_grid.find_devices_by_type(ContainerDevice):
        if container.name == "2":
            target_container = container
            break

    if target_container is None:
        print("Контейнер с названием '2' не найден на целевом гриде")
        return

    print(f"Найден источник: {source_container.name} (ID: {source_container.device_id}) на гриде {source_grid.name}")
    print(f"Найден цель: {target_container.name} (ID: {target_container.device_id}) на гриде {target_grid.name}")

    # Получить предметы источника для отчета
    source_items = source_container.items()
    if not source_items:
        print("В контейнере '1' нет предметов для переноса")
        return

    print(f"Переносим {len(source_items)} тип(ов) предметов из контейнера '1' на {source_grid.name} в контейнер '2' на {target_grid.name}")

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

    print("Межгридовой перенос завершен")


if __name__ == "__main__":
    main()
