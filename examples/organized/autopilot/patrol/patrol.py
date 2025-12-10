#!/usr/bin/env python3
import math
import time
from typing import Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.tools.navigation_tools import goto


Point3D = Tuple[float, float, float]

# Радиус скана радара (важно: шаг патруля не должен превышать эту величину)
DEFAULT_SCAN_RADIUS = 200.0
DEFAULT_BOUNDING_BOX_Y = 50.0


def _get_pos(rc) -> Optional[Point3D]:
    tel = rc.telemetry or {}
    pos = tel.get("worldPosition") or tel.get("position")
    if not pos:
        return None
    return (
        float(pos.get("x", 0.0)),
        float(pos.get("y", 0.0)),
        float(pos.get("z", 0.0)),
    )


def _build_horizontal_basis(down: Point3D) -> Tuple[Point3D, Point3D]:
    dx, dy, dz = down

    if abs(dx) < 0.9:
        ref = (1.0, 0.0, 0.0)
    else:
        ref = (0.0, 1.0, 0.0)

    ax, ay, az = ref
    bx, by, bz = down

    # h1 = ref x down
    ux = ay * bz - az * by
    uy = az * bx - ax * bz
    uz = ax * by - ay * bx
    length_u = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
    ux /= length_u
    uy /= length_u
    uz /= length_u

    # h2 = down x h1
    vx = by * uz - bz * uy
    vy = bz * ux - bx * uz
    vz = bx * uy - by * ux
    length_v = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    vx /= length_v
    vy /= length_v
    vz /= length_v

    return (ux, uy, uz), (vx, vy, vz)


def _distance(a: Point3D, b: Point3D) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def main() -> None:
    grid_name = "taburet"

    controller = SurfaceFlightController(
        grid_name,
        scan_radius=DEFAULT_SCAN_RADIUS,
        boundingBoxY=DEFAULT_BOUNDING_BOX_Y,
    )

    base_pos = _get_pos(controller.rc)
    if base_pos is None:
        print("Не удалось получить позицию RemoteControl. Завершение.")
        return

    print(f"Базовая позиция (центр патруля): {base_pos}")
    controller.visited_points.append(base_pos)

    print(
        "SurfaceFlightController: первичная загрузка карты из Redis "
        f"вокруг позиции {base_pos} (radius={DEFAULT_SCAN_RADIUS * 2:.1f}м)"
    )
    try:
        controller.load_map_region(center=base_pos, radius=DEFAULT_SCAN_RADIUS * 2.0)
    except AttributeError:
        print("ВНИМАНИЕ: у SurfaceFlightController нет метода load_map_region_from_redis.")
    except Exception as e:
        print(f"Ошибка при первичной загрузке карты из Redis: {e}")

    # Пытаемся взять высоту поверхности под базой из уже загруженной occupancy-сетки
    surface_y = None
    if getattr(controller, "radar_controller", None) is not None:
        rc = controller.radar_controller
        if getattr(rc, "occupancy_grid", None) is not None:
            surface_y = rc.get_surface_height(base_pos[0], base_pos[2])

    if surface_y is not None:
        print(
            "Использую ранее сохранённую карту поверхности: "
            f"высота под базой = {surface_y:.2f}"
        )
        solid = ore_cells = None
    else:
        print(
            "Ранее сохранённой поверхности под базой не найдено, "
            "выполняю первичный скан поверхности для заполнения карты..."
        )
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        print(
            f"[init] Начальный скан: solid={len(solid or [])}, "
            f"ores={len(ore_cells or []) if ore_cells is not None else 0}"
        )

    # Вектора гравитации и горизонтальные базисы
    down = controller._get_down_vector()
    print(f"Гравитация (down): {down}")
    h1, h2 = _build_horizontal_basis(down)
    print(f"Горизонтальные базисы: h1={h1}, h2={h2}")

    # Желаемая высота полёта над поверхностью
    flight_altitude = 50.0

    # Параметры колец
    ring_radius = 100.0
    ring_radius_step = 100.0
    max_ring_radius = 3000.0

    # Максимальная длина участка траектории:
    # ограничиваем её и сверху, и исходя из радиуса скана, чтобы
    # дрон не улетал дальше, чем видит радар.
    max_segment_length = min(100.0, DEFAULT_SCAN_RADIUS * 0.9)

    angle = 0.0

    while True:
        if ring_radius > max_ring_radius:
            print(f"Достигнут максимальный радиус {max_ring_radius} м. Ожидание на орбите.")
            time.sleep(10.0)
            continue

        current_pos = _get_pos(controller.rc) or base_pos
        print(f"\nТекущая позиция дрона: {current_pos}")

        down = controller._get_down_vector()
        up = (-down[0], -down[1], -down[2])  # пока не используется, но оставим для расширений

        # Считаем плоскую точку на окружности в горизонтальной плоскости
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        offset = (
            ring_radius * (cos_a * h1[0] + sin_a * h2[0]),
            ring_radius * (cos_a * h1[1] + sin_a * h2[1]),
            ring_radius * (cos_a * h1[2] + sin_a * h2[2]),
        )

        flat_point = (
            base_pos[0] + offset[0],
            base_pos[1] + offset[1],
            base_pos[2] + offset[2],
        )

        print(
            "Плоская патрульная точка (до учёта рельефа): "
            f"({flat_point[0]:.2f}, {flat_point[1]:.2f}, {flat_point[2]:.2f})"
        )

        # Быстрый скан поверхности под точкой назначения перед расчётом высоты
        # Это позволит обнаружить пропущенные воксели и предотвратить неверную высоту
        print("Выполняем быстрый скан поверхности под патрульной точкой...")
        rc = controller.radar_controller
        old_scan_params = rc.scan_params.copy() if hasattr(rc, "scan_params") else {}
        try:
            if hasattr(rc, "set_scan_params"):
                # Маленький радиус для точного скана, но boundingBoxY большой для узкого луча вниз
                rc.set_scan_params(
                    # radius=100.0, boundingBoxY=200.0, boundingBoxX=20.0, boundingBoxZ=20.0
                centerX =flat_point[0],
                centerY =flat_point[1],
                centerZ =flat_point[2],
                radius = 200,
                voxel_step = 1,
                cell_size = 10.0,

                boundingBoxX = 30,
                boundingBoxZ = 30,

                boundingBoxY = 100,
                                   )
            controller.scan_voxels(persist_to_shared_map=True)
            print("Быстрый скан завершён.")
        finally:
            if hasattr(rc, "set_scan_params") and old_scan_params:
                rc.set_scan_params(**old_scan_params)

        # # Проверяем высоту поверхности под flat_point и устанавливаем target_point
        # pos = flat_point
        # down = controller._get_down_vector()
        # up = (-down[0], -down[1], -down[2])
        # cell_size = controller.radar_controller.cell_size or 5.0
        # max_trace = cell_size * (controller.radar_controller.size[1] if controller.radar_controller.size else 50)
        # step = cell_size
        #
        # surface_point = controller._find_surface_point_along_gravity(pos, down, max_trace, step)
        # if surface_point is None:
        #     surface_height = controller.radar_controller.get_surface_height(pos[0], pos[2])
        #     if surface_height is not None:
        #         surface_point = (pos[0], surface_height, pos[2])
        #         print("Surface found via vertical lookup for patrol point.")
        #     else:
        #         print("Surface not found for patrol point; using flat_point as base.")
        #         surface_point = pos
        #
        # target_point = (
        #     surface_point[0] + up[0] * flight_altitude,
        #     surface_point[1] + up[1] * flight_altitude,
        #     surface_point[2] + up[2] * flight_altitude,
        # )
        #
        # # Высота над поверхностью в точке назначения (по Y)
        # altitude_y = target_point[1] - surface_point[1]

        # здесь measure_altitude_to_surface сам сделает live-скан,
        # если под flat_point пустота или нет данных в сетке
        cell_size = controller.radar_controller.cell_size or 5.0
        max_trace = cell_size * (
            controller.radar_controller.size[1]
            if controller.radar_controller.size
            else 50
        )

        # получаем точку поверхности под flat_point
        surface_point, altitude_y_now, altitude_along_up_now = controller.measure_altitude_to_surface(
            flat_point,
            max_trace_distance=max_trace,
            allow_live_scan_on_miss=True,
            scan_radius=DEFAULT_SCAN_RADIUS,
        )

        # пересчитаем вектор up ещё раз (на всякий случай, если гравитация изменилась)
        down = controller._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        # строим цель на заданной высоте над поверхностью вдоль up
        target_point = (
            surface_point[0] + up[0] * flight_altitude,
            surface_point[1] + up[1] * flight_altitude,
            surface_point[2] + up[2] * flight_altitude,
        )

        altitude_y = target_point[1] - surface_point[1]

        print(
            f"Патрульная точка: "
            f"угол={math.degrees(angle):.1f}°, "
            f"радиус={ring_radius:.1f}м, "
            f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f}), "
            f"alt_over_surface_Y≈{altitude_y:.1f}м"
        )

        # Для наглядности — GPS маркер патрульной точки
        controller.grid.create_gps_marker(
            f"Patrol_r{ring_radius:.0f}_a{math.degrees(angle):.0f}",
            coordinates=target_point,
        )

        print("Движение к patrol-точке...")

        # Здесь уже летим к безопасной 3D-точке над поверхностью
        # controller.lift_drone_to_point_altitude( target_point, 30)
        goto(controller.grid, target_point, speed=20.0)

        new_pos = _get_pos(controller.rc)
        if new_pos:
            print(f"Текущая позиция после перемещения: {new_pos}")
            controller.visited_points.append(new_pos)

        # Периодический перескан: по одному разу на каждое кольцо (при прохождении угла ~0°)
        if int(ring_radius) % 200 == 0 and abs(math.degrees(angle)) < 1e-3:
            print("[SCAN] Плановый перескан поверхности (радиусом сканера)...")
            controller.scan_voxels()

        # === Расчёт следующего шага по углу по ограничению длины дуги ===
        if ring_radius > 1e-3:
            angle_step = max_segment_length / ring_radius
        else:
            angle_step = 2.0 * math.pi

        # Страховка от бешеных шагов по углу
        max_angle_step_rad = math.radians(90.0)
        if angle_step > max_angle_step_rad:
            angle_step = max_angle_step_rad

        segment_distance = ring_radius * angle_step
        print(
            f"Следующий шаг по углу: {math.degrees(angle_step):.2f}°, "
            f"дуга≈{segment_distance:.1f}м (макс {max_segment_length:.1f}м)"
        )

        angle += angle_step
        if angle >= 2.0 * math.pi:
            angle -= 2.0 * math.pi
            ring_radius += ring_radius_step
            print(f"Переход на новое кольцо: радиус={ring_radius:.1f}м")

        time.sleep(0.5)


if __name__ == "__main__":
    main()
