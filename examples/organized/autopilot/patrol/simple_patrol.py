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
    controller = SurfaceFlightController("taburet", scan_radius=200, boundingBoxY=60)

    while True:
        # Сканируем поверхность для получения данных
        print("Выполняю скан поверхности...")
        controller.scan_voxels()

        # Пример 2: Полет вперед на 50 метров с высотой 20 метров над поверхностью
        print("\nПример 2: Полет вперед на 50 метров с высотой 20 метров над поверхностью")
        # Получаем текущую позицию дрона
        pos = controller.rc.telemetry.get("worldPosition") or controller.rc.telemetry.get("position")
        if not pos:
            print("Не удалось получить позицию дрона")
            return
        pos = (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))
        print(f"Текущая позиция дрона: {pos}")

        # Получаем вектор вперед
        forward, _, _ = controller.rc.get_orientation_vectors_world()
        print(f"Вектор вперед: {forward}")

        # Вычисляем точку вперед на 50 метров
        forward_distance = 100.0
        flight_altitude = 50.0
        forward_point = (
            pos[0] + forward[0] * forward_distance,
            pos[1] + forward[1] * forward_distance,
            pos[2] + forward[2] * forward_distance,
        )
        print(f"Точка вперед: {forward_point}")

        # controller.grid.create_gps_marker(f"forward_point{forward_distance:.0f}m_{flight_altitude:.0f}m",
        #                                   coordinates=forward_point)

        # Вычисляем целевую точку на высоте 20м над поверхностью
        target_point = controller.calculate_surface_point_at_altitude(forward_point, flight_altitude)

        # Отправляем грид на движение к целевой точке
        from secontrol.controllers.surface_flight_controller import _fly_to
        controller.visited_points.append(pos)
        controller.grid.create_gps_marker(f"ForwardSurfaceAlt{forward_distance:.0f}m_{flight_altitude:.0f}m", coordinates=target_point)

        goto(controller.grid, target_point, speed=20.0)

        new_pos = controller.rc.telemetry.get("worldPosition") or controller.rc.telemetry.get("position")
        if new_pos:
            new_pos = (new_pos.get("x", 0.0), new_pos.get("y", 0.0), new_pos.get("z", 0.0))
            controller.visited_points.append(new_pos)




if __name__ == "__main__":
    main()
