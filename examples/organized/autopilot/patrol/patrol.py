#!/usr/bin/env python3
"""
Патрульный полёт дрона по окружностям вокруг базы
в плоскости, перпендикулярной вектору гравитации.

ЛОГИКА ИСПОЛЬЗОВАНИЯ КАРТЫ:

1) При старте:
   - Берём позицию базы (RemoteControl).
   - ПРОБУЕМ загрузить карту из Redis вокруг этой точки
     (SurfaceFlightController.load_map_region_from_redis).
   - Если по загруженной карте удаётся получить высоту поверхности
     под базой (get_surface_height) — считаем, что карта есть и
     НЕ сканируем.
   - Если данных о поверхности нет — выполняем первичный скан радара.

2) В полёте:
   - Для каждой патрульной точки считаем координату в "горизонтальной"
     плоскости.
   - Расчёт высоты над поверхностью делаем через
     controller.calculate_surface_point_at_altitude.
   - Этот метод должен СНАЧАЛА пытаться использовать существующую
     карту (occupancy_grid / get_surface_height / Redis), и только
     если данных нет — запускать скан радара.

3) Этот скрипт больше НЕ запускает scan_voxels после каждого перелёта —
   он опирается на уже имеющуюся карту. Периодический перескан (по
   радиусам) можно оставить для учёта изменений рельефа.
"""

import math
import time
from typing import Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.tools.navigation_tools import goto


Point3D = Tuple[float, float, float]

# --- Базовые параметры радара, с которыми создаётся контроллер --- #
DEFAULT_SCAN_RADIUS = 100.0
DEFAULT_BOUNDING_BOX_Y = 50.0


def _get_pos(rc) -> Optional[Point3D]:
    """Чтение мировых координат из телеметрии RemoteControl."""
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
    """
    Строим два ортонормальных вектора (h1, h2) в плоскости,
    перпендикулярной вектору гравитации (down).

    down предполагается нормированным.
    """
    dx, dy, dz = down

    if abs(dx) < 0.9:
        ref = (1.0, 0.0, 0.0)
    else:
        ref = (0.0, 1.0, 0.0)

    ax, ay, az = ref
    bx, by, bz = down

    # h1 = normalize(cross(ref, down))
    ux = ay * bz - az * by
    uy = az * bx - ax * bz
    uz = ax * by - ay * bx
    len_u = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
    ux /= len_u
    uy /= len_u
    uz /= len_u

    # h2 = normalize(cross(down, h1))
    vx = by * uz - bz * uy
    vy = bz * ux - bx * uz
    vz = bx * uy - by * ux
    len_v = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    vx /= len_v
    vy /= len_v
    vz /= len_v

    return (ux, uy, uz), (vx, vy, vz)


def _distance(a: Point3D, b: Point3D) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _lerp_along_segment(a: Point3D, b: Point3D, max_dist: float) -> Point3D:
    """
    Берёт точку на отрезке A->B, отстоящую от A не больше max_dist.
    Если расстояние до B <= max_dist, возвращает B.
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    dz = b[2] - a[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist <= max_dist or dist < 1e-3:
        return b
    k = max_dist / dist
    return (
        a[0] + dx * k,
        a[1] + dy * k,
        a[2] + dz * k,
    )


def main() -> None:
    grid_name = "taburet"

    # Контроллер полёта над поверхностью (строит карту по радару)
    controller = SurfaceFlightController(
        grid_name,
        scan_radius=DEFAULT_SCAN_RADIUS,
        boundingBoxY=DEFAULT_BOUNDING_BOX_Y,
    )

    # Начальная позиция — центр патруля
    base_pos = _get_pos(controller.rc)
    if base_pos is None:
        print("Не удалось получить позицию RemoteControl. Завершение.")
        return

    print(f"Базовая позиция (центр патруля): {base_pos}")
    controller.visited_points.append(base_pos)

    # --- 1. Пробуем использовать уже сохранённую карту из Redis --- #
    print(
        f"SurfaceFlightController: первичная загрузка карты из Redis "
        f"вокруг позиции {base_pos} (radius={DEFAULT_SCAN_RADIUS * 2:.1f}м)"
    )
    try:
        controller.load_map_region_from_redis(center=base_pos, radius=DEFAULT_SCAN_RADIUS * 2.0)
    except AttributeError:
        # Если метод ещё не реализован в контроллере – просто лог,
        # чтобы не ломать скрипт.
        print("ВНИМАНИЕ: у SurfaceFlightController нет метода load_map_region_from_redis.")

    # Проверяем, есть ли данные о поверхности под базой в уже загруженной карте
    surface_y = None
    if getattr(controller, "radar_controller", None) is not None:
        rc = controller.radar_controller
        if getattr(rc, "occupancy_grid", None) is not None:
            surface_y = rc.get_surface_height(base_pos[0], base_pos[2])

    if surface_y is not None:
        print(
            f"Использую ранее сохранённую карту поверхности: "
            f"высота под базой = {surface_y:.2f}"
        )
        solid = ore_cells = None
    else:
        # --- 2. Если данных нет — выполняем первичный скан радара --- #
        print(
            "Ранее сохранённой поверхности под базой не найдено, "
            "выполняю первичный скан поверхности для заполнения карты..."
        )
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        print(
            f"[init] Начальный скан: solid={len(solid or [])}, "
            f"ores={len(ore_cells or []) if ore_cells is not None else 0}"
        )

    # Горизонтальная система координат относительно гравитации
    down = controller._get_down_vector()
    print(f"Гравитация (down): {down}")
    h1, h2 = _build_horizontal_basis(down)
    print(f"Горизонтальные базисы: h1={h1}, h2={h2}")

    # Параметры патруля
    flight_altitude = 50.0       # высота над поверхностью
    ring_radius = 100.0          # стартовый радиус
    ring_radius_step = 100.0     # шаг увеличения радиуса после полного круга
    max_ring_radius = 3000.0     # максимальный радиус облёта

    # Максимально допустимое расстояние между соседними точками по дуге
    max_segment_length = 100.0   # метров

    angle = 0.0  # начальный угол в радианах

    while True:
        if ring_radius > max_ring_radius:
            print(f"Достигнут максимальный радиус {max_ring_radius} м. Ожидание на орбите.")
            time.sleep(10.0)
            continue

        # Актуальный радиус скана из параметров радара
        raw_scan_radius = DEFAULT_SCAN_RADIUS
        if getattr(controller, "radar_controller", None) is not None:
            raw_scan_radius = controller.radar_controller.scan_params.get("radius", DEFAULT_SCAN_RADIUS)

        # Немного уменьшим радиус для безопасной границы перемещения
        safe_scan_move = raw_scan_radius * 0.8

        # Текущая позиция
        current_pos = _get_pos(controller.rc) or base_pos
        print(f"\nТекущая позиция дрона: {current_pos}")

        # Обновим вектор гравитации и up для корректной высоты
        down = controller._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        # Горизонтальное смещение в плоскости, перпендикулярной гравитации
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        offset = (
            ring_radius * (cos_a * h1[0] + sin_a * h2[0]),
            ring_radius * (cos_a * h1[1] + sin_a * h2[1]),
            ring_radius * (cos_a * h1[2] + sin_a * h2[2]),
        )

        # Точка патруля в "горизонтальной" плоскости (до учёта рельефа) — относительно центра патруля
        flat_point = (
            base_pos[0] + offset[0],
            base_pos[1] + offset[1],
            base_pos[2] + offset[2],
        )

        print(
            "Плоская патрульная точка (до учёта рельефа): "
            f"({flat_point[0]:.2f}, {flat_point[1]:.2f}, {flat_point[2]:.2f})"
        )

        # --- Ограничение по радиусу сканера ---
        dist_to_flat = _distance(current_pos, flat_point)
        if dist_to_flat > safe_scan_move:
            safe_flat_point = _lerp_along_segment(current_pos, flat_point, safe_scan_move)
            print(
                f"[SCAN-LIMIT] Цель вне надёжного радиуса сканера: "
                f"{dist_to_flat:.1f}м > {safe_scan_move:.1f}м. "
                f"Сдвигаем точку на границу скана: "
                f"({safe_flat_point[0]:.2f}, {safe_flat_point[1]:.2f}, {safe_flat_point[2]:.2f})"
            )
        else:
            safe_flat_point = flat_point

        # --- Расчёт точки на заданной высоте над поверхностью ---
        #
        # ВАЖНО:
        # - calculate_surface_point_at_altitude ДОЛЖЕН:
        #   1) Сначала смотреть в occupancy_grid (get_surface_height / трассировка).
        #   2) Если под точкой нет поверхности — попробовать загрузить карту
        #      из Redis (если ты это уже реализовал внутри контроллера).
        #   3) Только если после этого поверхность не найдена — запустить
        #      новый скан радара.
        #
        # Здесь мы просто пользуемся этим поведением.

        # Сначала точка на поверхности (altitude=0) — для контроля высоты
        surface_point = controller.calculate_surface_point_at_altitude(
            safe_flat_point,
            0.0,
        )

        # Затем целевая точка на нужной высоте
        target_point_raw = controller.calculate_surface_point_at_altitude(
            safe_flat_point,
            flight_altitude,
        )

        # Высота над поверхностью по проекции на вектор up
        alt_vec = (
            target_point_raw[0] - surface_point[0],
            target_point_raw[1] - surface_point[1],
            target_point_raw[2] - surface_point[2],
        )
        altitude_proj = alt_vec[0] * up[0] + alt_vec[1] * up[1] + alt_vec[2] * up[2]

        if altitude_proj < flight_altitude * 0.5:
            print(
                f"[ALT-CORRECT] Низкая высота над поверхностью ({altitude_proj:.1f}м). "
                f"Принудительно поднимаю до {flight_altitude:.1f}м."
            )
            target_point = (
                surface_point[0] + up[0] * flight_altitude,
                surface_point[1] + up[1] * flight_altitude,
                surface_point[2] + up[2] * flight_altitude,
            )
        else:
            target_point = target_point_raw

        print(
            "Патрульная точка: "
            f"угол={math.degrees(angle):.1f}°, "
            f"радиус={ring_radius:.1f}м, "
            f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )

        controller.grid.create_gps_marker(
            f"Patrol_r{ring_radius:.0f}_a{math.degrees(angle):.0f}",
            coordinates=target_point,
        )

        # Полёт к точке
        print("Движение к patrol-точке...")
        goto(controller.grid, target_point, speed=20.0)

        new_pos = _get_pos(controller.rc)
        if new_pos:
            print(f"Текущая позиция после перемещения: {new_pos}")
            controller.visited_points.append(new_pos)

        # Периодический перескан (редко), чтобы учитывать изменения рельефа
        # и при этом не жечь радар постоянно.
        if int(ring_radius) % 200 == 0 and abs(math.degrees(angle)) < 1e-3:
            print("[SCAN] Плановый перескан поверхности (радиусом сканера)...")
            controller.scan_voxels()

        # --- Динамический шаг по углу, чтобы расстояние по дуге не превышало max_segment_length ---

        if ring_radius > 1e-3:
            angle_step = max_segment_length / ring_radius
        else:
            angle_step = 2.0 * math.pi

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
