#!/usr/bin/env python3
"""
Пример использования метода remove_points_in_radius в SharedMapController.

Удаляет точки карты в радиусе от позиции CockpitDevice грида "taburet".
"""

from secontrol.common import prepare_grid
from secontrol.controllers.shared_map_controller import SharedMapController
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.tools.navigation_tools import get_world_position


def main():
    grid_name = "taburet"

    # Подготавливаем грид
    grid = prepare_grid(grid_name)

    # Находим CockpitDevice
    cockpits = grid.find_devices_by_type(CockpitDevice)
    if not cockpits:
        print("CockpitDevice не найден в гриде.")
        return

    cockpit = cockpits[0]
    cockpit.update()

    # Получаем мировую позицию кабины
    center = get_world_position(cockpit)
    if not center:
        print("Не удалось получить позицию CockpitDevice.")
        return

    print(f"Центр удаления: {center}")

    # Создаем контроллер карты
    mc = SharedMapController(owner_id=grid.owner_id)

    # Радиус удаления (в метрах)
    radius = 500.0

    # Удаляем точки в радиусе
    stats = mc.remove_points_in_radius(
        center=center,
        radius=radius,
        kinds=("voxels", "visited", "ores"),  # Удаляем все типы точек
        save=True
    )

    print(f"Статистика удаления:")
    print(f"  Удалено точек: {stats['total_removed']}")
    print(f"  Затронуто чанков: {stats['chunks_affected']}")
    print(f"  Обработанные типы: {stats['kinds_processed']}")


if __name__ == "__main__":
    main()
