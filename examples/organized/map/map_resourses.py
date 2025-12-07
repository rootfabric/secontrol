# from secontrol.controllers.surface_flight_controller import SurfaceFlightController
#
# def main():
#     controller = SurfaceFlightController("taburet", scan_radius=200, boundingBoxY=60)
#
#     # Найти ближайшие 5 ресурсов в радиусе 1500м
#     nearest = controller.find_nearest_resources(search_radius=1500.0, max_results=5)
#
#     print("Result list:", nearest)
#
# if __name__ == "__main__":
#     main()


from secontrol.controllers.surface_flight_controller import SurfaceFlightController

def main():
    controller = SurfaceFlightController("taburet", scan_radius=200, boundingBoxY=60)

    # 1) Загружаем карту из Redis вокруг текущей позиции
    controller.load_map_region_from_redis(radius=500.0)

    # 2) Ищем ближайшие ресурсы БЕЗ повторного скана
    nearest = controller.find_nearest_resources(search_radius=500.0, max_results=5)

    print("Result list:", nearest)

if __name__ == "__main__":
    main()

