"""Пример сценария инвентаризации и запуска производства стальных пластин."""

from __future__ import annotations

from typing import Iterable, List

from secontrol.base_device import BaseDevice
from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice, Item

TARGET_TYPE = "MyObjectBuilder_Component"
TARGET_SUBTYPE = "SteelPlate"
TARGET_AMOUNT = 100
STEEL_PLATE_BLUEPRINT = "MyObjectBuilder_BlueprintDefinition/Component/SteelPlate"


def _iter_containers(grid) -> Iterable[ContainerDevice]:
    finder = getattr(grid, "find_devices_by_type", None)
    containers: List[ContainerDevice] = []
    if callable(finder):
        try:
            containers = [
                device
                for device in finder("container")  # type: ignore[misc]
                if isinstance(device, ContainerDevice)
            ]
        except Exception:
            containers = []
    if not containers:
        containers = [
            device
            for device in grid.devices.values()
            if isinstance(device, ContainerDevice)
        ]
    return containers


def _count_steel_plates(containers: Iterable[ContainerDevice]) -> float:
    total = 0.0
    for container in containers:
        for item in container.items():
            if not isinstance(item, Item):
                continue
            if item.type == TARGET_TYPE and item.subtype == TARGET_SUBTYPE:
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


def _queue_steel_plates(assembler: BaseDevice, amount: float) -> None:
    payload = {
        "cmd": "queue_add",
        "blueprint": STEEL_PLATE_BLUEPRINT,
        "amount": float(amount),
    }
    assembler.send_command(payload)


def main() -> None:
    grid = prepare_grid()
    try:
        containers = list(_iter_containers(grid))
        if not containers:
            print("Контейнеры не найдены на гриде.")
            return
        current = _count_steel_plates(containers)
        print(f"Найдено {current:.0f} стальных пластин в контейнерах.")
        if current >= TARGET_AMOUNT:
            print("Производство не требуется.")
            return
        deficit = TARGET_AMOUNT - current
        assembler = _find_assembler(grid)
        if not assembler:
            print("Ассемблер не найден, не могу поставить задачу на производство.")
            return
        print(
            "Добавляю в очередь ассемблера задачу на производство"
            f" {deficit:.0f} пластин."
        )
        _queue_steel_plates(assembler, deficit)
    finally:
        close(grid)


if __name__ == "__main__":
    main()
