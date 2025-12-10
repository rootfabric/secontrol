from secontrol.controllers.surface_flight_controller import SurfaceFlightController

def main():
    controller = SurfaceFlightController("taburet")

    # 1) Загружаем карту из Redis вокруг текущей позиции
    controller.load_map_region(radius=1500.0)

    # 2) Ищем ближайшие ресурсы БЕЗ повторного скана
    nearest = controller.find_nearest_resources(search_radius=1500.0, max_results=50)

    print("Result list:", nearest)

if __name__ == "__main__":
    main()

