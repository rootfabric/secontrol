#!/usr/bin/env python3

from __future__ import annotations

from secontrol.controllers.surface_flight_controller import SurfaceFlightController


def main() -> None:

    controller = SurfaceFlightController("taburet2")

    radius = 400.0

    # 1) Загружаем карту из Redis вокруг текущей позиции
    controller.load_map_region(radius=radius)

    # 2) Ищем ближайшие ресурсы БЕЗ повторного скана
    nearest = controller.find_nearest_resources(search_radius=radius)

    print("Result list:", nearest)

    if len(nearest) == 0:
        print("No resources found")
        return

    go_to_point = nearest[0]['position']
    print("Go to point:", go_to_point)

    # Перемещаемся к точке ресурса на высоте 20м над поверхностью
    print(f"Moving to resource at {go_to_point} at altitude 20.0m above surface")
    controller.lift_drone_to_point_altitude(go_to_point, 50.0)

    print("Вышли на точку ресурса")





if __name__ == "__main__":
    main()
