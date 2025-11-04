from __future__ import annotations

import time
from typing import Dict, Tuple, Any, List
from collections import defaultdict

from secontrol.devices.container_device import ContainerDevice, Item
from secontrol.common import resolve_owner_id, prepare_grid


def generate_inventory_report(grid) -> None:
    """Generate a comprehensive inventory report for the grid."""

    print("=" * 80)
    print("ОТЧЕТ ПО ИНВЕНТАРЮ ГРИДА")
    print("=" * 80)
    print(f"Грид: {grid.name} (ID: {grid.grid_id})")
    print(f"Владелец: {grid.owner_id}")
    print()

    # Get all container devices
    containers = grid.find_devices_containers()
    print(f"Найдено устройств-контейнеров: {len(containers)}")
    print()

    if not containers:
        print("На гриде нет устройств с инвентарем.")
        return

    # Detailed device inventory report
    print("ПОДРОБНЫЙ ОТЧЕТ ПО УСТРОЙСТВАМ:")
    print("-" * 80)

    total_devices_with_items = 0
    total_items_count = 0

    for device in containers:
        device_items = device.inventory_items()
        if not device_items:
            continue

        total_devices_with_items += 1
        device_item_count = sum(item.amount for item in device_items)

        print(f"Устройство: {device.name} (ID: {device.device_id})")
        print(f"Тип: {device.device_type}")
        print(f"Всего предметов: {device_item_count}")
        print(f"Количество инвентарей: {device.inventory_count()}")

        # Show inventories
        for inventory in device.inventories():
            if inventory.items:
                print(f"  Инвентарь '{inventory.name}':")
                for item in inventory.items:
                    print(f"    - {item.display_name} ({item.subtype}): {item.amount}")
                print()

        print("-" * 40)

    print()
    print("ОБЩАЯ СТАТИСТИКА ПО РЕСУРСАМ:")
    print("-" * 80)

    # Get all items for aggregation
    all_items = grid.get_all_grid_items()

    if not all_items:
        print("На гриде нет предметов.")
        return

    # Aggregate by item subtype
    resource_summary = defaultdict(int)
    device_type_summary = defaultdict(lambda: defaultdict(int))
    inventory_type_summary = defaultdict(lambda: defaultdict(int))

    for item in all_items:
        resource_summary[item['item_subtype']] += item['amount']
        device_type_summary[item['device_type']][item['item_subtype']] += item['amount']
        inventory_type_summary[item['inventory_name']][item['item_subtype']] += item['amount']

    # Sort resources by total amount
    sorted_resources = sorted(resource_summary.items(), key=lambda x: x[1], reverse=True)

    print("ТОП РЕСУРСОВ ПО КОЛИЧЕСТВУ:")
    for subtype, amount in sorted_resources[:20]:  # Top 20
        print(f"  {subtype}: {amount}")
    if len(sorted_resources) > 20:
        print(f"  ... и ещё {len(sorted_resources) - 20} типов ресурсов")
    print()

    print("РАСПРЕДЕЛЕНИЕ ПО ТИПАМ УСТРОЙСТВ:")
    for device_type, resources in device_type_summary.items():
        device_total = sum(resources.values())
        print(f"  {device_type}: {device_total} предметов")
        top_resources = sorted(resources.items(), key=lambda x: x[1], reverse=True)[:5]
        for subtype, amount in top_resources:
            print(f"    - {subtype}: {amount}")
        print()

    print("РАСПРЕДЕЛЕНИЕ ПО ТИПАМ ИНВЕНТАРЕЙ:")
    for inventory_name, resources in inventory_type_summary.items():
        inv_total = sum(resources.values())
        print(f"  {inventory_name}: {inv_total} предметов")
        top_resources = sorted(resources.items(), key=lambda x: x[1], reverse=True)[:3]
        for subtype, amount in top_resources:
            print(f"    - {subtype}: {amount}")
        print()

    print("ИТОГИ:")
    print(f"- Всего устройств с предметами: {total_devices_with_items}")
    print(f"- Всего типов ресурсов: {len(resource_summary)}")
    print(f"- Общее количество всех предметов: {sum(resource_summary.values())}")


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    grid = prepare_grid()

    # Generate comprehensive inventory report
    generate_inventory_report(grid)


if __name__ == "__main__":
    main()
