#!/usr/bin/env python3
"""
Пример движения дрона вдоль поверхности планеты с сохранением высоты.

Скрипт использует `SurfaceFlightController` для сканирования рельефа, затем
пролетает вперед на заданное расстояние, поддерживая высоту над поверхностью,
и выводит список посещённых точек.
"""

from secontrol.controllers.surface_flight_controller import SurfaceFlightController


def main():
    # Создаем контроллер полёта с радаром (замените имя грида на ваше)
    controller = SurfaceFlightController("taburet", scan_radius=80)

    # Сканируем поверхность для получения высот
    print("Выполняю скан поверхности...")
    controller.scan_voxels()

    # Летим вперёд 10 метров на высоте 10 метров над рельефом
    controller.fly_forward_over_surface(10, 10)

    # Выводим посещённые точки маршрута
    print("Visited points:", controller.get_visited_points())


if __name__ == "__main__":
    main()
