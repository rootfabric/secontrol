#!/usr/bin/env python3
"""
Пример использования метода lift_drone_to_altitude для подъема дрона на заданную высоту над поверхностью.

Этот скрипт демонстрирует, как использовать SurfaceFlightController для подъема дрона
на 50 метров над поверхностью планеты с использованием данных радара.
"""

from secontrol.controllers.surface_flight_controller import SurfaceFlightController


def main():
    # Создаем контроллер полета с радаром
    controller = SurfaceFlightController("taburet", scan_radius=80)

    # Сканируем поверхность для получения данных
    print("Выполняю скан поверхности...")
    # controller.scan_voxels()
    controller.load_map_region_from_redis( radius=500.0)

    # Поднимаем дрон на 50 метров над поверхностью
    print("Поднимаю дрон на 50 метров над поверхностью...")
    controller.lift_drone_to_altitude(50.0)

    print("Пример завершен.")


if __name__ == "__main__":
    main()
