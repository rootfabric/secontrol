#!/usr/bin/env python3
"""
Скрипт для переноса всех предметов из контейнеров присоединенных кораблей (субгридов) в основной грид.
"""

from __future__ import annotations

import time

from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.ship_drill_device import ShipDrillDevice
from secontrol.common import resolve_owner_id
from secontrol.redis_client import RedisEventClient
from secontrol.base_device import Grid


def main() -> None:
    owner_id = resolve_owner_id()
    client = RedisEventClient()

    try:
        grids = client.list_grids(owner_id)
        if not grids:
            print("Гриды не найдены.")
            return

        # Найти основной грид по имени "DroneBase"
        main_grid_info = None
        for grid_info in grids:
            if grid_info.get('name') == 'DroneBase':
                main_grid_info = grid_info
                break

        if main_grid_info is None:
            print("Основной грид с именем 'DroneBase' не найден.")
            return

        main_grid_id = str(main_grid_info.get('id'))
        print(f"Основной грид: {main_grid_info.get('name', 'unnamed')} (ID: {main_grid_id})")

        # Создать Grid объект для основного грида
        main_grid = Grid(client, owner_id, main_grid_id, owner_id, name=main_grid_info.get('name'))

        # Получить присоединенные гриды через коннекторы
        attached_connectors = []
        connectors = main_grid.find_devices_by_type(ConnectorDevice)
        for connector in connectors:
            if connector.telemetry and isinstance(connector.telemetry, dict):
                other_grid_id = connector.telemetry.get("otherConnectorGridId")
                other_connector_id = connector.telemetry.get("otherConnectorId")
                if other_grid_id and other_connector_id:
                    attached_connectors.append({
                        'connector': connector,
                        'subgrid_id': str(other_grid_id),
                        'sub_connector_id': str(other_connector_id)
                    })

        print(f"Найдено {len(attached_connectors)} присоединенных коннекторов.")

        # Найти все контейнеры на основном гриде
        containers = list(main_grid.find_devices_by_type(ContainerDevice))
        if not containers:
            print("Контейнеры на основном гриде не найдены.")
            return

        # Выбрать начальный целевой контейнер (предпочтительно "Main")
        target_container = None
        for container in containers:
            if container.name == "Main":
                target_container = container
                break
        if target_container is None:
            target_container = containers[0]

        print(f"Начальный целевой контейнер: {target_container.name} (ID: {target_container.device_id}) на гриде {main_grid.name}")

        def select_target_container(current, all_containers):
            """Выбирает подходящий контейнер для переноса: текущий, если не полон, иначе следующий неполный."""
            current.send_command({"cmd": "update"})
            cap = current.capacity()
            if cap['fillRatio'] < 1.0:
                return current
            for cont in all_containers:
                if cont.device_id == current.device_id:
                    continue
                cont.send_command({"cmd": "update"})
                cap = cont.capacity()
                if cap['fillRatio'] < 1.0:
                    print(f"Переключение на контейнер {cont.name} (ID: {cont.device_id})")
                    return cont
            return None  # Нет доступных контейнеров

        total_transferred = 0

        # Обработать каждый присоединенный коннектор
        for conn_info in attached_connectors:
            connector_main = conn_info['connector']
            subgrid_id = conn_info['subgrid_id']
            sub_connector_id = conn_info['sub_connector_id']

            # Найти имя грида
            subgrid_name = 'unnamed'
            for g in grids:
                if str(g.get('id')) == subgrid_id:
                    subgrid_name = g.get('name', 'unnamed')
                    break

            print(f"\nОбработка присоединенного грида: {subgrid_name} (ID: {subgrid_id}) через коннектор {connector_main.name}")

            # Создать Grid объект для субгрида
            subgrid = Grid(client, owner_id, subgrid_id, owner_id, name=subgrid_name)

            # Найти суб-коннектор
            sub_connector = subgrid.get_device(sub_connector_id)
            if not sub_connector or not isinstance(sub_connector, ConnectorDevice):
                print(f"Не найден коннектор {sub_connector_id} на субгриде {subgrid_name}")
                continue

            # Перенести предметы, которые уже находятся в суб-коннекторе
            sub_connector.send_command({"cmd": "update"})
            existing_items = sub_connector.inventory_items()
            if existing_items:
                print(f"Перенос предметов, уже находящихся в суб-коннекторе:")
                for item in existing_items:
                    print(f"  - {item.amount} x {item.display_name or item.subtype or 'unknown'}")

                # Проверить и выбрать подходящий контейнер
                target_container = select_target_container(target_container, containers)
                if target_container is None:
                    print("Нет доступных контейнеров для переноса из суб-коннектора")
                    continue

                result = sub_connector.move_all(target_container)
                if result > 0:
                    total_transferred += result
                    print(f"Перенесено {result} тип(ов) предметов из суб-коннектора")
                else:
                    print("Не удалось перенести из суб-коннектора")

            # Найти контейнеры, кокпиты, буры и коннекторы на гриде (исключая только суб-коннектор, используемый для переноса)
            sub_containers = []
            sub_containers.extend(subgrid.find_devices_by_type(ContainerDevice))
            sub_containers.extend(subgrid.find_devices_by_type(CockpitDevice))
            sub_containers.extend(subgrid.find_devices_by_type(ShipDrillDevice))
            # Исключить только суб-коннектор
            sub_containers = [d for d in sub_containers if d.device_id != sub_connector_id]
            if not sub_containers:
                print(f"Контейнеры/кокпиты/буры на гриде {subgrid_name} не найдены.")
                continue

            print(f"Найдено {len(sub_containers)} устройств с инвентарем на гриде {subgrid_name}:")
            for device in sub_containers:
                print(f"  - {device.name or 'Unnamed'} ({device.device_type})")

            # Перенести предметы из каждого контейнера напрямую в целевой контейнер
            for container in sub_containers:
                source_items = container.items()
                if not source_items:
                    continue

                print(f"Перенос из контейнера {container.name} (ID: {container.device_id}):")
                for item in source_items:
                    print(f"  - {item.amount} x {item.display_name or item.subtype or 'unknown'}")

                # Проверить и выбрать подходящий контейнер
                target_container = select_target_container(target_container, containers)
                if target_container is None:
                    print(f"Нет доступных контейнеров для переноса из {container.name}")
                    continue

                try:
                    result = container.move_all(target_container)
                    if result > 0:
                        total_transferred += result
                        print(f"Перенесено {result} тип(ов) предметов")
                    else:
                        print("Не удалось переместить в целевой контейнер")

                    # Проверить, остались ли предметы в суб-контейнере
                    time.sleep(0.5)
                    container.send_command({"cmd": "update"})
                    remaining_items = container.items()
                    if remaining_items:
                        print("Предупреждение: предметы остались в контейнере:")
                        for item in remaining_items:
                            print(f"  - {item.amount} x {item.display_name or item.subtype}")

                except Exception as exc:
                    print(f"Ошибка при переносе из контейнера {container.name}: {exc}")

        if total_transferred > 0:
            print(f"\nВсего перенесено {total_transferred} тип(ов) предметов в основной грид.")
        else:
            print("\nПредметы для переноса не найдены.")

        # Обновить телеметрию
        time.sleep(0.5)
        target_container.send_command({"cmd": "update"})

        print("Операция завершена.")

    finally:
        client.close()


if __name__ == "__main__":
    main()
