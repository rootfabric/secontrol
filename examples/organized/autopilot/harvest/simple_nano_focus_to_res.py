#!/usr/bin/env python3
from __future__ import annotations

import math
import time
from typing import Dict, Any, List, Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.common import prepare_grid, close
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

GRID_NAME = "taburet2"
SEARCH_RADIUS = 400.0
FLY_ALTITUDE = 50.0  # высота полёта над поверхностью над точкой ресурса
# при желании можно сделать чуть больше: FLY_ALTITUDE + EXTRA_DEPTH
EXTRA_DEPTH = 0.0    # например, 5.0 если руда чуть глубже поверхности

Point3D = Tuple[float, float, float]


def parse_visible_ores(telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
    props = telemetry.get("properties", {}) if telemetry else {}
    targets = props.get("Drill.PossibleDrillTargets", []) or []
    visible: List[Dict[str, Any]] = []

    for target in targets:
        if len(target) >= 5:
            ore_name = target[3]
            ore_type = str(ore_name).split("/")[-1]
            ore_mapping = {"Snow": "Ice", "IronIngot": "Iron"}
            ore_display = ore_mapping.get(ore_type, ore_type)
            visible.append(
                {
                    "type": ore_display,
                    "volume": float(target[4]),
                    "distance": float(target[2]),
                }
            )
    return visible


def _get_rc_position(controller: SurfaceFlightController) -> Optional[Point3D]:
    """
    Безопасно достаём текущую мировую позицию грида из телеметрии Remote Control.
    """
    rc = getattr(controller, "rc", None)
    if rc is None:
        print("У контроллера нет rc (Remote Control).")
        return None

    tel: Dict[str, Any] = rc.telemetry or {}
    pos = tel.get("worldPosition") or tel.get("position")
    if not pos:
        print("В телеметрии Remote Control нет поля worldPosition/position.")
        return None

    try:
        x = float(pos.get("x", 0.0))
        y = float(pos.get("y", 0.0))
        z = float(pos.get("z", 0.0))
    except (TypeError, ValueError) as exc:
        print(f"Ошибка разбора координат позиции RC: {exc!r}")
        return None

    return x, y, z


def main() -> None:
    print("Поиск ближайшего ресурса и выставление зоны Nanobot Drill в эту точку...")

    # 1. Контроллер поверхности для поиска ресурса и позиционирования дрона.
    controller = SurfaceFlightController(GRID_NAME)

    # 2. Загружаем карту и ищем ближайший ресурс.
    controller.load_map_region(radius=SEARCH_RADIUS)
    nearest: List[Dict[str, Any]] = controller.find_nearest_resources(search_radius=SEARCH_RADIUS)

    print("Result list:", nearest)
    if not nearest:
        print("Ресурсы не найдены в радиусе поиска.")
        return

    resource_point: Point3D = nearest[0]["position"]
    print(f"Ближайший ресурс в точке: {resource_point}")

    # 3. Перелетаем к точке ресурса на заданную высоту над поверхностью.
    print(f"Летим к ресурсу на высоте {FLY_ALTITUDE} м над поверхностью...")
    controller.lift_drone_to_point_altitude(resource_point, FLY_ALTITUDE)

    # 4. Читаем актуальную позицию грида после перемещения.
    current_pos = _get_rc_position(controller)
    if current_pos is None:
        print("Не удалось получить текущую позицию грида, выходим.")
        return

    print(f"Текущая позиция грида после перелёта: {current_pos}")

    # 5. Для отладки — расстояние до ресурса.
    dx = resource_point[0] - current_pos[0]
    dy = resource_point[1] - current_pos[1]
    dz = resource_point[2] - current_pos[2]
    dist_to_resource = math.sqrt(dx * dx + dy * dy + dz * dz)
    print(f"Расстояние от грида до точки ресурса: {dist_to_resource:.2f} м")

    # 6. Открываем грид через prepare_grid и находим Nanobot Drill.
    grid = prepare_grid(GRID_NAME)
    try:
        drill: Optional[NanobotDrillSystemDevice] = grid.get_first_device(NanobotDrillSystemDevice)
        if not drill:
            print("Nanobot Drill не найден на гриде!")
            return

        drill.update()
        drill.wait_for_telemetry(timeout=10)

        tel = drill.telemetry or {}
        props: Dict[str, Any] = tel.get("properties", {}) or {}

        print("Nanobot Drill найден.")
        print("Доступные действия Nanobot Drill:")
        print("  " + ", ".join(drill.available_action_ids()))

        # 7. Включаем отображение зоны, чтобы визуально проверить смещение.
        drill.set_show_area(True)

        # 8. Логируем текущее смещение, но не полагаемся на ошибочное измерение высоты.
        current_offset_raw = props.get("Drill.AreaOffsetUpDown", 0.0)
        try:
            current_offset_value = float(current_offset_raw)
        except (TypeError, ValueError):
            current_offset_value = 0.0

        print(f"Текущее смещение Drill.AreaOffsetUpDown (до изменения): {current_offset_value:.2f} м")

        # 9. Используем известную высоту полёта над поверхностью (FLY_ALTITUDE)
        # и, при необходимости, добавочную глубину EXTRA_DEPTH.
        desired_offset = FLY_ALTITUDE + EXTRA_DEPTH

        print(
            f"По расчёту: дрон находится примерно на высоте {FLY_ALTITUDE:.2f} м над поверхностью "
            f"в точке ресурса.\n"
            f"EXTRA_DEPTH={EXTRA_DEPTH:.2f} м (доп. заглубление под поверхность).\n"
            f"Устанавливаем смещение зоны вниз: {desired_offset:.2f} м"
        )

        drill.set_property("AreaOffsetUpDown", desired_offset)

        # 10. Ещё раз обновляем телеметрию, чтобы убедиться, что значение применилось.
        drill.update()
        drill.wait_for_telemetry(timeout=5)
        tel = drill.telemetry or {}
        props = tel.get("properties", {}) or {}
        applied_offset = props.get("Drill.AreaOffsetUpDown")

        print(f"Применённое смещение Drill.AreaOffsetUpDown (по телеметрии): {applied_offset}")
        print(
            "Зона Nanobot Drill должна быть сдвинута примерно на высоту полёта дрона "
        )

        drill.turn_on()

        print("=== ДОБЫЧА ЗАПУЩЕНА ===")
        print("Программа будет проверять состояние каждые 5 секунд.")
        print("Остановка при исчерпании ресурсов или переполнении контейнеров (>=95%).")
        print("Проверка ресурсов начнется после 25 секунд (5 итераций), чтобы бур успел включиться.")

        i = 0
        max_iterations = 100  # защита от бесконечного цикла
        resource_check_delay = 5  # начинать проверку ресурсов после 5 итераций (25 сек)
        while i < max_iterations:
            time.sleep(5)
            i += 1

            drill.update()
            drill.wait_for_telemetry(timeout=5)

            tel = drill.telemetry or {}
            props = tel.get("properties", {}) or {}

            # Проверка контейнеров всегда
            containers = grid.find_devices_by_type("container")
            containers_full = False
            for container in containers:
                cap = container.capacity()
                fill_ratio = cap.get("fillRatio", 0.0)
                print(f"Контейнер {container.name}: заполненность {fill_ratio:.2f}")
                if fill_ratio >= 0.95:
                    containers_full = True
                    break

            if containers_full:
                print("Контейнеры переполнены (>=95%). Останавливаем добычу.")
                drill.stop_drilling()
                drill.set_show_area(False)
                break

            # Проверка ресурсов только после задержки
            if i >= resource_check_delay:
                visible_ores = parse_visible_ores(tel)
                current_target = props.get("Drill.CurrentDrillTarget")

                print(f"Итерация {i}: Видимых руд - {len(visible_ores)}, текущая цель - {bool(current_target)}")

                # Если ресурсов нет
                if not visible_ores or current_target is None:
                    print("Ресурсы в зоне добычи исчерпаны. Останавливаем добычу.")
                    drill.stop_drilling()
                    drill.set_show_area(False)
                    break

            if i >= max_iterations:
                print("Достигнуто максимальное количество итераций. Останавливаем добычу.")
                drill.stop_drilling()
                drill.set_show_area(False)
                break

        print("Добыча завершена.")


    finally:
        close(grid)


if __name__ == "__main__":
    main()
