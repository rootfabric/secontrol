#!/usr/bin/env python3
"""
Пример использования методов calculate_surface_point_at_altitude и fly_forward_to_altitude.

Этот скрипт демонстрирует:
1. Использование calculate_surface_point_at_altitude для расчета точки на заданной высоте над поверхностью для произвольных координат.
2. Использование fly_forward_to_altitude для полета вперед от носа дрона на заданное расстояние с поддержанием высоты над поверхностью.
"""

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.tools.navigation_tools import goto


def main():
    # Создаем контроллер полета с радаром
    controller = SurfaceFlightController("taburet", scan_radius=100)

    # Сканируем поверхность для получения данных
    print("Выполняю скан поверхности...")
    controller.scan_voxels()

    # Пример 1: Использование calculate_surface_point_at_altitude
    # print("\nПример 1: Расчет точки на высоте 30м над поверхностью для координат (100, 50, 200)")
    # test_position = (100.0, 50.0, 200.0)
    # altitude = 30.0
    # target_point = controller.calculate_surface_point_at_altitude(test_position, altitude)
    # print(f"Исходная позиция: {test_position}")
    # print(f"Целевая точка на высоте {altitude}м: {target_point}")

    # Пример 2: Снижение на 10 метров вниз по гравитации при отсутствии поверхности
    print("\nПример 2: Снижение на 10 метров вниз по гравитации при отсутствии поверхности")
    # Получаем текущую позицию дрона
    pos = controller.rc.telemetry.get("worldPosition") or controller.rc.telemetry.get("position")
    if not pos:
        print("Не удалось получить позицию дрона")
        return
    pos = (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))
    print(f"Текущая позиция дрона: {pos}")

    # Вычисляем целевую точку: снижение ровно на 10м вниз по гравитации
    down = controller._get_down_vector()
    target_point = (
        pos[0] + down[0] * 10.0,
        pos[1] + down[1] * 10.0,
        pos[2] + down[2] * 10.0,
    )
    print(f"Целевая точка (снижение на 10м вниз по гравитации): {target_point}")

    # Отправляем грид на движение к целевой точке
    controller.visited_points.append(pos)
    controller.grid.create_gps_marker("Descent10m", coordinates=target_point)
    goto(controller.grid, target_point, speed=10.0)


    new_pos = controller.rc.telemetry.get("worldPosition") or controller.rc.telemetry.get("position")
    if new_pos:
        new_pos = (new_pos.get("x", 0.0), new_pos.get("y", 0.0), new_pos.get("z", 0.0))
        controller.visited_points.append(new_pos)

    print("Пример завершен.")


if __name__ == "__main__":
    main()
