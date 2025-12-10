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

    resource_point = nearest[0]['position']

    print("Go to point:", resource_point)

    # Перемещаемся к точке ресурса на высоте 50м над поверхностью
    print(f"Moving to resource at {resource_point} at altitude 50.0m above surface")
    controller.lift_drone_to_point_altitude(resource_point, 50.0)

    # Распечатываем текущую позицию грида после перемещения
    current_pos = controller.rc.telemetry
    if current_pos:
        pos = current_pos.get("worldPosition") or current_pos.get("position")
        if pos:
            current_coords = (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))
            print(f"Current grid position after movement: {current_coords}")
        else:
            print("Unable to retrieve current position")
    else:
        print("No telemetry available")

    print("Вышли на точку ресурса")





if __name__ == "__main__":
    main()
