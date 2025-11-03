"""Сценарий инвентаризации и запуска производства стальных пластин."""

from __future__ import annotations

from typing import Iterable, List

from secontrol.base_device import BaseDevice
from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice, Item as ContainerItem
from secontrol.item_types import item_matches, Item

# Настройки производства
TARGET_ITEM = Item.SteelPlate
TARGET_AMOUNT = 10



def _iter_inventory_devices(grid) -> Iterable[ContainerDevice]:
    finder = getattr(grid, "find_devices_by_type", None)
    devices: List[ContainerDevice] = []
    if callable(finder):
        try:
            # Find containers
            containers = [
                device
                for device in finder("container")  # type: ignore[misc]
                if isinstance(device, ContainerDevice)
            ]
            # Find assemblers
            assemblers = [
                device
                for device in finder("assembler")  # type: ignore[misc]
                if isinstance(device, ContainerDevice)
            ]
            # Find refineries
            refineries = [
                device
                for device in finder("refinery")  # type: ignore[misc]
                if isinstance(device, ContainerDevice)
            ]
            devices = containers + assemblers + refineries
        except Exception:
            devices = []
    if not devices:
        devices = [
            device
            for device in grid.devices.values()
            if isinstance(device, ContainerDevice)
        ]
    return devices


def _count_items(containers: Iterable[ContainerDevice], target_item: Item) -> float:
    total = 0.0
    for container in containers:
        for item in container.items():
            if not isinstance(item, ContainerItem):
                continue
            if item_matches(item, target_item):
                total += float(item.amount)
    return total


def _find_assembler(grid) -> BaseDevice | None:
    finder = getattr(grid, "find_devices_by_type", None)
    if callable(finder):
        try:
            for candidate in finder("assembler"):  # type: ignore[misc]
                if isinstance(candidate, BaseDevice):
                    return candidate
        except Exception:
            pass
    for device in grid.devices.values():
        device_type = getattr(device, "device_type", "")
        if device_type == "assembler":
            return device
        name = getattr(device, "name", None) or ""
        if "assembler" in name.lower():
            return device
    return None


def _queue_item(assembler: BaseDevice, blueprint_id: str, amount: float) -> None:
    payload = {
        "cmd": "queue_add",
        "blueprintId": blueprint_id,
        "amount": float(amount),
    }
    print(payload)
    assembler.send_command(payload)


def produce_item(
    item_type: str,
    item_subtype: str,
    blueprint_id: str,
    target_amount: int,
    grid=None
) -> None:
    """Производит заданный предмет до указанного количества."""
    if grid is None:
        grid = prepare_grid()
        should_close = True
    else:
        should_close = False

    try:
        inventory_devices = list(_iter_inventory_devices(grid))
        if not inventory_devices:
            print("Контейнеры, ассемблеры и refinery не найдены на гриде.")
            return

        # Создаем объект Item для проверки
        target_item = Item(type=item_type, subtype=item_subtype, display_name="")

        current = _count_items(inventory_devices, target_item)
        print(f"Найдено {current:.0f} {item_subtype} в контейнерах, ассемблерах и refinery.")
        if current >= target_amount:
            print("Производство не требуется.")
            return

        deficit = target_amount - current
        assembler = _find_assembler(grid)
        if not assembler:
            print("Ассемблер не найден, не могу поставить задачу на производство.")
            return

        print(f"Найден Ассемблер: {assembler.name} {assembler.grid_id}")
        print(
            f"Добавляю в очередь ассемблера задачу на производство {deficit:.0f} {item_subtype}."
        )
        _queue_item(assembler, blueprint_id, deficit)
    finally:
        if should_close:
            close(grid)


def main() -> None:
    grid = prepare_grid()
    try:
        inventory_devices = list(_iter_inventory_devices(grid))
        if not inventory_devices:
            print("Контейнеры, ассемблеры и refinery не найдены на гриде.")
            return

        current = _count_items(inventory_devices, TARGET_ITEM)
        print(f"Найдено {current:.0f} {TARGET_ITEM.subtype} в контейнерах, ассемблерах и refinery.")
        if current >= TARGET_AMOUNT:
            print("Производство не требуется.")
            return

        deficit = TARGET_AMOUNT - current
        assembler = _find_assembler(grid)
        if not assembler:
            print("Ассемблер не найден, не могу поставить задачу на производство.")
            return

        print(f"Найден Ассемблер: {assembler.name} {assembler.grid_id}")
        print(
            f"Добавляю в очередь ассемблера задачу на производство {deficit:.0f} {TARGET_ITEM.subtype}."
        )
        _queue_item(assembler, TARGET_ITEM.blueprint_id, deficit)
    finally:
        close(grid)


if __name__ == "__main__":
    main()
