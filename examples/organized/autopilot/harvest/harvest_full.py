#!/usr/bin/env python3
from __future__ import annotations

import math
import time
from typing import Dict, Any, List, Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.common import prepare_grid, close
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.base_device import BaseDevice, BlockInfo
from secontrol.tools.navigation_tools import goto
from typing import Callable, Dict, Optional, Sequence, Tuple
import math

GRID_NAME = "taburet2"
SEARCH_RADIUS = 400.0
FLY_ALTITUDE = 50.0  # высота полёта над поверхностью над точкой ресурса
# при желании можно сделать чуть больше: FLY_ALTITUDE + EXTRA_DEPTH
EXTRA_DEPTH = 0.0    # например, 5.0 если руда чуть глубже поверхности

Point3D = Tuple[float, float, float]

# ---- Docking constants and helpers ----
ARRIVAL_DISTANCE = 0.20
RC_STOP_TOLERANCE = 0.7
CHECK_INTERVAL = 0.2
MAX_FLIGHT_TIME = 240.0
SPEED_DISTANCE_THRESHOLD = 15.0
DOCK_FORWARD_FUDGE = 0.5
MAX_DOCK_STEPS = 10
DOCK_SUCCESS_TOLERANCE = 0.6
STATUS_UNCONNECTED = "Unconnected"
STATUS_READY_TO_LOCK = "Connectable"
STATUS_CONNECTED = "Connected"

def _vec(value: Sequence[float]) -> Tuple[float, float, float]:
    return float(value[0]), float(value[1]), float(value[2])

def _parse_vector(value: object) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, str):
        parts = value.split(':')
        if len(parts) >= 5 and parts[0] == 'GPS':
            return float(parts[2]), float(parts[3]), float(parts[4])
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return _vec((value["x"], value["y"], value["z"]))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return _vec(value)
    return None

def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-6:
        return 0.0, 0.0, 1.0
    return v[0] / length, v[1] / length, v[2] / length

def _cross(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

def _add(a, b): return a[0] + b[0], a[1] + b[1], a[2] + b[2]
def _sub(a, b): return a[0] - b[0], a[1] - b[1], a[2] - b[2]
def _scale(v, s): return v[0] * s, v[1] * s, v[2] * s
def _dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

class Basis:
    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        self.forward = _normalize(forward)
        raw_up = _normalize(up)
        right = _cross(self.forward, raw_up)
        self.right = _normalize(right)
        self.up = _normalize(_cross(self.right, self.forward))

def _ensure_telemetry(device: BaseDevice):
    device.update()

def _get_block_info(grid, device: BaseDevice) -> BlockInfo:
    try:
        b = grid.get_block(int(device.device_id))
        if b:
            return b
    except Exception:
        pass
    target_id = int(device.device_id)
    for b in grid.blocks.values():
        if b.id == target_id:
            return b
    raise RuntimeError(f"Block {device.name} not found in gridinfo!")

def _get_orientation(device: BaseDevice) -> Basis:
    tel: Dict = device.telemetry or {}
    ori = tel.get("orientation") or tel.get("Orientation")
    if ori:
        fwd = _parse_vector(ori.get("forward"))
        up = _parse_vector(ori.get("up"))
        if fwd and up:
            return Basis(fwd, up)
    if device.device_type != "RemoteControl":
        rcs = device.grid.find_devices_by_type(RemoteControlDevice)
        if rcs:
            rc = rcs[0]
            _ensure_telemetry(rc)
            rc_ori = (rc.telemetry or {}).get("orientation") or (rc.telemetry or {}).get("Orientation")
            if rc_ori:
                fwd = _parse_vector(rc_ori.get("forward"))
                up = _parse_vector(rc_ori.get("up"))
                if fwd and up:
                    return Basis(fwd, up)
    raise RuntimeError(f"Cannot get world orientation for block {device.name}")

def _get_pos(dev: BaseDevice) -> Optional[Tuple[float, float, float]]:
    tel = dev.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    return _parse_vector(p) if p else None

def _get_connector_world_pos(base_conn: ConnectorDevice, base_grid) -> Tuple[Tuple[float, float, float], str]:
    tel = base_conn.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    if p:
        base_pos = _parse_vector(p)
        return base_pos, "Using connector telemetry position."
    anchor_list = base_grid.find_devices_by_type(RemoteControlDevice)
    if not anchor_list:
        raise RuntimeError("No Anchor RC found on base grid.")
    anchor = anchor_list[0]
    _ensure_telemetry(anchor)
    anchor_pos = _get_pos(anchor)
    anchor_basis = _get_orientation(anchor)
    a_blk = _get_block_info(base_grid, anchor)
    t_blk = _get_block_info(base_grid, base_conn)
    d = _sub(_vec(t_blk.relative_to_grid_center), _vec(a_blk.relative_to_grid_center))
    world_diff = _add(_add(_scale(anchor_basis.right, d[0]), _scale(anchor_basis.up, d[1])), _scale(anchor_basis.forward, d[2]))
    base_pos = _add(anchor_pos, world_diff)
    return base_pos, "Computed connector position via Anchor RC."

def get_connector_status(connector: ConnectorDevice) -> str:
    tel = connector.telemetry or {}
    return tel.get("connectorStatus") or "unknown"

def is_already_docked(connector: ConnectorDevice) -> bool:
    status = get_connector_status(connector)
    return status == STATUS_CONNECTED

def is_parking_possible(connector: ConnectorDevice) -> bool:
    status = get_connector_status(connector)
    return status in [STATUS_UNCONNECTED, STATUS_READY_TO_LOCK]

def _calculate_docking_point(ship_rc: RemoteControlDevice, ship_conn: ConnectorDevice, base_conn: ConnectorDevice, base_grid) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
    base_basis = _get_orientation(base_conn)
    base_pos, pos_info = _get_connector_world_pos(base_conn, base_grid)
    print(pos_info)
    _ensure_telemetry(ship_rc)
    _ensure_telemetry(ship_conn)
    rc_pos = _get_pos(ship_rc)
    if not rc_pos:
        raise RuntimeError("Cannot get RC world position.")
    ship_conn_pos = _get_pos(ship_conn)
    if not ship_conn_pos:
        raise RuntimeError("Cannot get ship connector world position.")
    start_dist = _dist(rc_pos, base_pos)
    print(f"RC distance to base connector: {start_dist:.2f}m")
    rc_to_ship_conn = _sub(ship_conn_pos, rc_pos)
    dir_vec = _sub(base_pos, ship_conn_pos)
    dir_len = math.sqrt(dir_vec[0] ** 2 + dir_vec[1] ** 2 + dir_vec[2] ** 2)
    if dir_len < 1e-6:
        approach_dir = base_basis.forward
    else:
        approach_dir = (dir_vec[0] / dir_len, dir_vec[1] / dir_len, dir_vec[2] / dir_len)
    if DOCK_FORWARD_FUDGE != 0.0:
        fudge_vec = _scale(approach_dir, DOCK_FORWARD_FUDGE)
        ship_conn_target = _add(base_pos, fudge_vec)
    else:
        ship_conn_target = base_pos
    final_rc_pos = _sub(ship_conn_target, rc_to_ship_conn)
    base_forward = base_basis.forward
    base_up = base_basis.up
    return final_rc_pos, base_forward, base_pos, base_up, ship_conn_target

def _fly_to(remote: RemoteControlDevice, target: Tuple[float, float, float], name: str, speed_far: float, speed_near: float, check_callback: Optional[Callable[[], bool]] = None, ship_conn: ConnectorDevice = None, ship_conn_target: Optional[Tuple[float, float, float]] = None, fixed_base_pos: Optional[Tuple[float, float, float]] = None):
    curr_pos = _get_pos(remote)
    if not curr_pos:
        remote.update()
        curr_pos = _get_pos(remote)
    if not curr_pos:
        raise RuntimeError("Cannot get current RC position.")
    dist = _dist(curr_pos, target)
    speed = speed_far if dist > SPEED_DISTANCE_THRESHOLD else speed_near
    gps = f"GPS:{name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"
    print(f"Flying to {name} (Dist: {dist:.1f}m)")
    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(gps, speed=speed, gps_name=name, dock=False)
    if ship_conn:
        _ensure_telemetry(ship_conn)
    engaged = False
    for _ in range(15):
        time.sleep(0.2)
        remote.update()
        if remote.telemetry.get("autopilotEnabled"):
            engaged = True
            break
    if not engaged:
        print("Autopilot did not start!")
        return None
    start_t = time.time()
    last_print = 0.0
    stop_pos = curr_pos
    while True:
        remote.update()
        if ship_conn:
            ship_conn.update()
        p = _get_pos(remote)
        if not p:
            time.sleep(CHECK_INTERVAL)
            continue
        d = _dist(p, target)
        if check_callback and d < 1.0 and check_callback():
            print("Callback condition met, stopping flight.")
            remote.disable()
            break
        stop_pos = p
        now = time.time()
        if now - last_print > 1.0 or d < 3.0:
            dx = target[0] - p[0]
            dy = target[1] - p[1]
            dz = target[2] - p[2]
            if ship_conn and ship_conn_target is not None:
                ship_conn_pos = _get_pos(ship_conn)
                if ship_conn_pos:
                    conn_dist = _dist(ship_conn_pos, ship_conn_target)
            print(f"Flying... Dist: {d:.2f}m")
            last_print = now
        if d < ARRIVAL_DISTANCE:
            print("Arrived.")
            break
        if not remote.telemetry.get("autopilotEnabled"):
            if d < RC_STOP_TOLERANCE:
                print("Stopped near target.")
                break
            else:
                print("Manual interrupt!")
                return stop_pos
        if time.time() - start_t > MAX_FLIGHT_TIME:
            print("Max flight time exceeded.")
            remote.disable()
            break
        time.sleep(CHECK_INTERVAL)
    return stop_pos

def _dock_by_connector_vector(rc: RemoteControlDevice, ship_conn: ConnectorDevice, base_conn: ConnectorDevice) -> Optional[Tuple[float, float, float]]:
    base_target_pos = _get_pos(base_conn)
    if base_target_pos is None:
        print("Cannot determine base target position.")
        return None
    best_dist = None
    last_improve_time = time.time()
    stop_pos = None
    for step_idx in range(1, MAX_DOCK_STEPS + 1):
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(rc)
        ship_pos = _get_pos(ship_conn)
        rc_pos = _get_pos(rc)
        if not ship_pos or not rc_pos:
            print("Cannot get positions.")
            break
        dist_cb = _dist(ship_pos, base_target_pos)
        print(f"Step {step_idx}: ShipConn->BaseTarget: {dist_cb:.3f}m")
        if dist_cb <= DOCK_SUCCESS_TOLERANCE:
            print("Connector within tolerance.")
            stop_pos = rc_pos
            break
        if best_dist is None or dist_cb < best_dist - 0.05:
            best_dist = dist_cb
            last_improve_time = time.time()
        elif time.time() - last_improve_time > 8.0:
            print("No improvement.")
            stop_pos = rc_pos
            break
        dir_vec = _sub(base_target_pos, ship_pos)
        dir_len = math.sqrt(dir_vec[0] ** 2 + dir_vec[1] ** 2 + dir_vec[2] ** 2)
        if dir_len < 1e-3:
            print("Direction too small.")
            stop_pos = rc_pos
            break
        dir_norm = (dir_vec[0] / dir_len, dir_vec[1] / dir_len, dir_vec[2] / dir_len)
        step_len = max(0.8, min(3.0, dist_cb * 0.6))
        move_vec = _scale(dir_norm, step_len)
        target_rc = _add(rc_pos, move_vec)
        stop_pos = _fly_to(rc, target_rc, f"DockStep#{step_idx}", 1.5, 0.6, check_callback=lambda: get_connector_status(ship_conn) == STATUS_READY_TO_LOCK, ship_conn=ship_conn, ship_conn_target=base_target_pos, fixed_base_pos=base_target_pos)
        if stop_pos is None:
            print("Autopilot did not start.")
            break
    return stop_pos

def dock_procedure(base_grid_id: str, ship_grid_id: str):
    ship_grid = prepare_grid(ship_grid_id)
    base_grid = prepare_grid(base_grid_id)
    try:
        rc_list = ship_grid.find_devices_by_type(RemoteControlDevice)
        ship_conn_list = ship_grid.find_devices_by_type(ConnectorDevice)
        base_conn_list = base_grid.find_devices_by_type(ConnectorDevice)
        if not rc_list:
            raise RuntimeError("No RemoteControl on ship.")
        if not ship_conn_list:
            raise RuntimeError("No Connector on ship.")
        if not base_conn_list:
            raise RuntimeError("No Connector on base.")
        rc = rc_list[0]
        ship_conn = ship_conn_list[0]
        base_conn = base_conn_list[0]
        _ensure_telemetry(rc)
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(base_conn)
        print(f"Ship connector status: {get_connector_status(ship_conn)}")
        if is_already_docked(ship_conn):
            print("Already docked, undocking...")
            ship_conn.disconnect()
            time.sleep(1)
            ship_conn.update()
            print(f"After undock: {get_connector_status(ship_conn)}")
        if get_connector_status(ship_conn) == STATUS_READY_TO_LOCK:
            ship_conn.connect()
        final_rc_pos, base_fwd, base_conn_pos, base_up, ship_conn_target = _calculate_docking_point(rc, ship_conn, base_conn, base_grid)
        ship_conn.disconnect()
        approach_rc_pos = _add(final_rc_pos, _scale(base_fwd, 5.0))
        _fly_to(rc, approach_rc_pos, "Approach", 15.0, 5.0)
        stop_pos_docking = _dock_by_connector_vector(rc, ship_conn, base_conn)
        print("Waiting for connector to lock...")
        locked = False
        last_status = ""
        while not locked:
            ship_conn.update()
            status = get_connector_status(ship_conn)
            if status != last_status:
                print(f"Ship connector status: {status}")
                last_status = status
            if status == STATUS_READY_TO_LOCK:
                print("Ready to lock, connecting...")
                ship_conn.connect()
                time.sleep(0.5)
                ship_conn.update()
                final_status = get_connector_status(ship_conn)
                if final_status == STATUS_CONNECTED:
                    print("Successfully connected!")
                    locked = True
                else:
                    print(f"Connect failed: {final_status}")
                    locked = True
            time.sleep(CHECK_INTERVAL)
        print(f"Final Connector Status: {get_connector_status(ship_conn)}")
        rc.disable()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            rc.disable()
        except Exception:
            pass
        close(ship_grid)
        close(base_grid)


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
    print("Отстыковка, подъем и поиск ближайшего ресурса...")

    # 1. Контроллер поверхности для поиска ресурса и позиционирования дрона.
    controller = SurfaceFlightController(GRID_NAME)

    # Отстыковка и подъем
    grid_temp = prepare_grid(GRID_NAME)
    try:
        connectors = grid_temp.find_devices_by_type(ConnectorDevice)
        if connectors:
            ship_conn = connectors[0]
            ship_conn.update()
            status = get_connector_status(ship_conn)
            if status == STATUS_CONNECTED:
                print("Отстыковка...")
                ship_conn.disconnect()
                time.sleep(1)
                ship_conn.update()
        # Подъем на 100м
        current_pos = _get_rc_position(controller)
        if current_pos:
            print(f"Подъем на высоту 100м от текущей позиции {current_pos}")
            controller.lift_drone_to_point_altitude(current_pos, 100.0)
            time.sleep(2)
    finally:
        close(grid_temp)

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

        # Возврат на базу
        print("Возврат на базу...")
        dock_procedure("DroneBase", GRID_NAME)


    finally:
        close(grid)


if __name__ == "__main__":
    main()
