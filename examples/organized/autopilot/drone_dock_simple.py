from __future__ import annotations
import math
import time
from typing import Callable, Dict, Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice, BlockInfo
from secontrol.common import close, prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import goto

# ---- Settings ------------------------------------------------------------
ARRIVAL_DISTANCE = 0.20            # точность прилёта RC к цели
RC_STOP_TOLERANCE = 0.7            # если RC отключил АП < этого расстояния — считаем норм
CHECK_INTERVAL = 0.2
MAX_FLIGHT_TIME = 240.0
SPEED_DISTANCE_THRESHOLD = 15.0

# Насколько "продавить" коннектор корабля ЗА коннектор базы вдоль линии стыковки.
DOCK_FORWARD_FUDGE = 0.5

# Максимум итераций "подползания" коннектором к базе
MAX_DOCK_STEPS = 10

# Считаем докинг успешным, если коннектор ближе к базе, чем это расстояние (метры)
DOCK_SUCCESS_TOLERANCE = 0.6

# ---- Connector status constants ------------------------------------------
STATUS_UNCONNECTED = "Unconnected"
STATUS_READY_TO_LOCK = "Connectable"
STATUS_CONNECTED = "Connected"


# ---- Math helpers --------------------------------------------------------


def _vec(value: Sequence[float]) -> Tuple[float, float, float]:
    """Convert sequence to (x, y, z) tuple."""
    return float(value[0]), float(value[1]), float(value[2])


def _parse_vector(value: object) -> Optional[Tuple[float, float, float]]:
    """Parse vector from GPS string, dict or list/tuple."""
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
    """Normalize vector."""
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-6:
        return 0.0, 0.0, 1.0
    return v[0] / length, v[1] / length, v[2] / length


def _cross(a: Tuple[float, float, float],
           b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Cross product."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _add(a, b): return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _sub(a, b): return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _scale(v, s): return v[0] * s, v[1] * s, v[2] * s


def _dot(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class Basis:
    """Forward / Up / Right basis for a block in world space."""

    def __init__(self, forward: Tuple[float, float, float],
                 up: Tuple[float, float, float]):
        self.forward = _normalize(forward)
        raw_up = _normalize(up)
        right = _cross(self.forward, raw_up)
        self.right = _normalize(right)
        self.up = _normalize(_cross(self.right, self.forward))


# ---- Utilities -----------------------------------------------------------


def _ensure_telemetry(device: BaseDevice):
    """Force telemetry update."""
    device.update()


def _get_block_info(grid, device: BaseDevice) -> BlockInfo:
    """Get BlockInfo from gridinfo by device_id."""
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
    """
    Get world orientation from telemetry.

    Priority:
    1) device.telemetry["orientation"] or ["Orientation"]
       with forward/up (dict with x,y,z)
    2) Fallback: use RemoteControl on same grid.
    """
    tel: Dict = device.telemetry or {}
    ori = tel.get("orientation") or tel.get("Orientation")

    if ori:
        fwd = _parse_vector(ori.get("forward"))
        up = _parse_vector(ori.get("up"))
        if fwd and up:
            print(f"   [INFO] Using direct orientation vectors for {device.name}.")
            return Basis(fwd, up)

    if device.device_type != "RemoteControl":
        print(f"   [WARN] No direct orientation for {device.name}. Searching for RC on grid...")
        rcs = device.grid.find_devices_by_type(RemoteControlDevice)
        if rcs:
            rc = rcs[0]
            _ensure_telemetry(rc)
            rc_ori = (rc.telemetry or {}).get("orientation") or (rc.telemetry or {}).get("Orientation")
            if rc_ori:
                fwd = _parse_vector(rc_ori.get("forward"))
                up = _parse_vector(rc_ori.get("up"))
                print(f"   [WARN] Fallback: Using Remote Control orientation for {device.name}.")
                if fwd and up:
                    return Basis(fwd, up)

    raise RuntimeError(f"Cannot get world orientation (Forward/Up) for block {device.name}")


def _get_pos(dev: BaseDevice) -> Optional[Tuple[float, float, float]]:
    """Get world position from telemetry."""
    tel = dev.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    return _parse_vector(p) if p else None


def _get_connector_world_pos(
    base_conn: ConnectorDevice,
    base_grid,
) -> Tuple[Tuple[float, float, float], str]:
    """Получает мировую позицию коннектора базы (с учётом фиксированного GPS, если задан)."""

    tel = base_conn.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    if p:
        base_pos = _parse_vector(p)
        return base_pos, "   [POS] Using connector telemetry position."

    # Fallback через якорный RC на базе
    print("   [POS] No direct connector position, calculating via Anchor RC...")
    anchor_list = base_grid.find_devices_by_type(RemoteControlDevice)
    if not anchor_list:
        raise RuntimeError("No Anchor RC found on base grid to compute connector position.")
    anchor = anchor_list[0]
    _ensure_telemetry(anchor)
    anchor_pos = _get_pos(anchor)
    anchor_basis = _get_orientation(anchor)
    a_blk = _get_block_info(base_grid, anchor)
    t_blk = _get_block_info(base_grid, base_conn)
    d = _sub(_vec(t_blk.relative_to_grid_center), _vec(a_blk.relative_to_grid_center))
    world_diff = _add(
        _add(_scale(anchor_basis.right, d[0]), _scale(anchor_basis.up, d[1])),
        _scale(anchor_basis.forward, d[2]),
    )
    base_pos = _add(anchor_pos, world_diff)
    return base_pos, "   [POS] Computed connector position via Anchor RC."


# ---- Connector status functions ------------------------------------------


def get_connector_status(connector: ConnectorDevice) -> str:
    """Get current status of connector."""
    tel = connector.telemetry or {}
    return tel.get("connectorStatus") or "unknown"


def is_already_docked(connector: ConnectorDevice) -> bool:
    """Check if the connector is already docked (connected)."""
    status = get_connector_status(connector)
    return status == STATUS_CONNECTED


def is_parking_possible(connector: ConnectorDevice) -> bool:
    """Check if parking (docking) is possible on this connector."""
    status = get_connector_status(connector)
    return status in [STATUS_UNCONNECTED, STATUS_READY_TO_LOCK]


# ---- Docking geometry ----------------------------------------------------


def _calculate_docking_point(
    ship_rc: RemoteControlDevice,
    ship_conn: ConnectorDevice,
    base_conn: ConnectorDevice,
    base_grid,

) -> Tuple[
    Tuple[float, float, float],   # final_rc_pos
    Tuple[float, float, float],   # base_forward
    Tuple[float, float, float],   # base_pos
    Tuple[float, float, float],   # base_up
    Tuple[float, float, float],   # ship_conn_target
]:
    """
    Первый грубый просчёт точки докинга, чтобы получить:
      - линию подхода (forward базы),
      - примерную точку для RC,
      - цель для коннектора.
    """

    base_basis = _get_orientation(base_conn)

    base_pos, pos_info = _get_connector_world_pos(base_conn, base_grid, fixed_base_gps)
    print(pos_info)

    _ensure_telemetry(ship_rc)
    _ensure_telemetry(ship_conn)

    rc_pos = _get_pos(ship_rc)
    if not rc_pos:
        raise RuntimeError("Cannot get RC world position for docking calculation.")

    ship_conn_pos = _get_pos(ship_conn)
    if not ship_conn_pos:
        raise RuntimeError("Cannot get ship connector world position for docking calculation.")

    start_dist = _dist(rc_pos, base_pos)
    print(f"   [PLAN] RC distance to base connector at plan time: {start_dist:.2f}m")

    rc_to_ship_conn = _sub(ship_conn_pos, rc_pos)
    print(
        "   [PLAN] RC->ShipConnector vector (world via telemetry): "
        f"({rc_to_ship_conn[0]:.2f}, {rc_to_ship_conn[1]:.2f}, {rc_to_ship_conn[2]:.2f})"
    )

    dir_vec = _sub(base_pos, ship_conn_pos)
    dir_len = math.sqrt(dir_vec[0] ** 2 + dir_vec[1] ** 2 + dir_vec[2] ** 2)
    if dir_len < 1e-6:
        approach_dir = base_basis.forward
        print("   [PLAN] Ship connector already at base, using base_forward as approach_dir.")
    else:
        approach_dir = (dir_vec[0] / dir_len, dir_vec[1] / dir_len, dir_vec[2] / dir_len)
        print(
            "   [PLAN] Approach dir (ShipConn -> BaseConn): "
            f"({approach_dir[0]:.3f}, {approach_dir[1]:.3f}, {approach_dir[2]:.3f})"
        )

    if DOCK_FORWARD_FUDGE != 0.0:
        fudge_vec = _scale(approach_dir, DOCK_FORWARD_FUDGE)
        ship_conn_target = _add(base_pos, fudge_vec)
        print(
            f"   [PLAN] Ship connector target = BaseConn + approach_dir * {DOCK_FORWARD_FUDGE:.2f}m -> "
            f"({ship_conn_target[0]:.2f}, {ship_conn_target[1]:.2f}, {ship_conn_target[2]:.2f})"
        )
    else:
        ship_conn_target = base_pos
        print("   [PLAN] Ship connector target = Base connector position (no fudge).")

    # Грубая точка для RC (она дальше будет уточняться другим методом)
    final_rc_pos = _sub(ship_conn_target, rc_to_ship_conn)

    base_forward = base_basis.forward
    base_up = base_basis.up
    return final_rc_pos, base_forward, base_pos, base_up, ship_conn_target


# ---- Autopilot with logging ----------------------------------------------


def _fly_to(
    remote: RemoteControlDevice,
    target: Tuple[float, float, float],
    name: str,
    speed_far: float,
    speed_near: float,
    check_callback: Optional[Callable[[], bool]] = None,
    ship_conn: ConnectorDevice = None,
    ship_conn_target: Optional[Tuple[float, float, float]] = None,
    fixed_base_pos: Optional[Tuple[float, float, float]] = None,
):
    """Send RC to a waypoint with step-by-step logging."""

    curr_pos = _get_pos(remote)

    if not curr_pos:
        remote.update()
        curr_pos = _get_pos(remote)

    if not curr_pos:
        raise RuntimeError("Cannot get current RC position.")

    dist = _dist(curr_pos, target)
    speed = speed_far if dist > SPEED_DISTANCE_THRESHOLD else speed_near
    gps = f"GPS:{name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    print(f"--- Flying to {name} (Start Dist: {dist:.1f}m) ---")
    print(f"    Target GPS: {gps}")

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
        print("   [Error] Autopilot did not start!")
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
            print("   [Interrupting] Callback condition met, stopping flight.")
            remote.disable()
            break

        stop_pos = p

        now = time.time()
        if now - last_print > 1.0 or d < 3.0:
            dx = target[0] - p[0]
            dy = target[1] - p[1]
            dz = target[2] - p[2]
            log = (
                "   [FLY] CurrentPos(XYZ): "
                f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}) | "
                f"Target(XYZ): ({target[0]:.2f}, {target[1]:.2f}, {target[2]:.2f}) | "
                f"Dist: {d:.2f}m | "
                f"Delta(XYZ): ({dx:.2f}, {dy:.2f}, {dz:.2f})"
            )

            if ship_conn and ship_conn_target is not None:
                ship_conn_pos = _get_pos(ship_conn)
                if ship_conn_pos:
                    conn_dist = _dist(ship_conn_pos, ship_conn_target)
                    log += f" | ShipConn Dist: {conn_dist:.2f}m"
                    if fixed_base_pos is not None:
                        conn_dist_fixed = _dist(ship_conn_pos, fixed_base_pos)
                        log += f" | ShipConn->FixedBase: {conn_dist_fixed:.2f}m"

            print(log)
            last_print = now

        if d < ARRIVAL_DISTANCE:
            print(f"   [Success] Arrived. Final Dist: {d:.3f}")
            break

        if not remote.telemetry.get("autopilotEnabled"):
            if d < RC_STOP_TOLERANCE:
                print(f"   [Info] Stopped near target ({d:.2f}m). Considered aligned.")
                break
            else:
                print(f"   [Stop] Manual interrupt at dist {d:.2f}m!")
                return stop_pos

        if time.time() - start_t > MAX_FLIGHT_TIME:
            print("[Error] Max flight time exceeded, disabling autopilot.")
            remote.disable()
            break

        time.sleep(CHECK_INTERVAL)

    return stop_pos


# ---- Final docking by connector->base vector -----------------------------


def _dock_by_connector_vector(
    rc: RemoteControlDevice,
    ship_conn: ConnectorDevice,
    base_conn: ConnectorDevice,
    fixed_base_gps: Optional[str],
) -> Optional[Tuple[float, float, float]]:
    """
    Финальный докинг: не доверяем заранее рассчитанной точке,
    а каждый раз двигаемся по вектору от коннектора корабля к коннектору базы.

    На каждой итерации:
      - меряем ShipConn->BaseTarget;
      - делаем шаг 0.8–3м в этом направлении;
      - снова меряем, пока не станет < DOCK_SUCCESS_TOLERANCE.
    """

    base_target_pos = (
        _parse_vector(fixed_base_gps)
        if fixed_base_gps
        else _get_pos(base_conn)
    )

    if base_target_pos is None:
        print("   [DOCK] Cannot determine base target position.")
        return None

    best_dist = None
    last_improve_time = time.time()
    stop_pos: Optional[Tuple[float, float, float]] = None

    for step_idx in range(1, MAX_DOCK_STEPS + 1):
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(rc)

        ship_pos = _get_pos(ship_conn)
        rc_pos = _get_pos(rc)

        if not ship_pos or not rc_pos:
            print("   [DOCK] Cannot get positions of RC or ship connector.")
            break

        dist_cb = _dist(ship_pos, base_target_pos)
        print(f"   [DOCK] Step {step_idx}: ShipConn->BaseTarget: {dist_cb:.3f}m")

        if dist_cb <= DOCK_SUCCESS_TOLERANCE:
            print("   [DOCK] Connector is within tolerance, stopping fine approach.")
            stop_pos = rc_pos
            break

        if best_dist is None or dist_cb < best_dist - 0.05:
            best_dist = dist_cb
            last_improve_time = time.time()
        elif time.time() - last_improve_time > 8.0:
            print("   [DOCK] No improvement for 8s, giving up fine approach.")
            stop_pos = rc_pos
            break

        dir_vec = _sub(base_target_pos, ship_pos)
        dir_len = math.sqrt(dir_vec[0] ** 2 + dir_vec[1] ** 2 + dir_vec[2] ** 2)
        if dir_len < 1e-3:
            print("   [DOCK] Direction vector too small.")
            stop_pos = rc_pos
            break

        dir_norm = (dir_vec[0] / dir_len, dir_vec[1] / dir_len, dir_vec[2] / dir_len)

        # Шаг: максимум 3м, минимум 0.8м, примерно 60% от текущего расстояния
        step_len = max(0.8, min(3.0, dist_cb * 0.6))
        move_vec = _scale(dir_norm, step_len)
        target_rc = _add(rc_pos, move_vec)

        stop_pos = _fly_to(
            rc,
            target_rc,
            f"DockStep#{step_idx}",
            speed_far=1.5,
            speed_near=0.6,
            check_callback=lambda: get_connector_status(ship_conn) == STATUS_READY_TO_LOCK,
            ship_conn=ship_conn,
            ship_conn_target=base_target_pos,
            fixed_base_pos=base_target_pos,
        )

        # Если АП не стартовал (например, цель слишком близко) — считаем, что дальше не пролезть
        if stop_pos is None:
            print("   [DOCK] Autopilot did not start on fine step, stopping.")
            break

    return stop_pos


def try_dock(ship_conn):
    # 3) Ожидаем ReadyToLock и коннектим
    print("   [DOCKING] Waiting for connector to become ready to lock...")
    locked = False
    last_status = ""



    ship_conn.wait_for_telemetry()
    status = ship_conn.telemetry.get("connectorStatus")
    if status != last_status:
        print(f"   [DOCKING] Ship connector status: {status}")
        last_status = status

    if status == STATUS_READY_TO_LOCK:
        print("   [DOCKING] Ready to lock detected, connecting...")
        ship_conn.connect()
        time.sleep(0.5)
        ship_conn.update()
        final_status = get_connector_status(ship_conn)
        if final_status == STATUS_CONNECTED:
            print("   [DOCKING] Successfully connected!")
            locked = True
        else:
            print(f"   [DOCKING] Connect failed, final status: {final_status}")
            locked = True

    return locked

# ---- Main logic ----------------------------------------------------------


def dock_procedure(base_grid: str, ship_grid: str):
    ship_grid = prepare_grid(ship_grid)
    base_grid = prepare_grid(base_grid)

    current_rc_pos = None
    final_rc_pos_for_log = None
    stop_pos_docking = None


    rc_list = ship_grid.find_devices_by_type(RemoteControlDevice)
    ship_conn_list = ship_grid.find_devices_by_type(ConnectorDevice)
    base_conn_list = base_grid.find_devices_by_type(ConnectorDevice)

    if not rc_list:
        raise RuntimeError("No RemoteControl found on ship grid.")
    if not ship_conn_list:
        raise RuntimeError("No Connector found on ship grid.")
    if not base_conn_list:
        raise RuntimeError("No Connector found on base grid.")

    rc = rc_list[0]
    ship_conn = ship_conn_list[0]
    base_conn = base_conn_list[0]

    while not try_dock(ship_conn):
        _ensure_telemetry(rc)
        ship_conn.wait_for_telemetry()
        base_conn.wait_for_telemetry()


        # ---- Check initial status ----
        print(f"   [INITIAL] Ship connector status: {get_connector_status(ship_conn)}")

        if is_already_docked(ship_conn):
            print("   [INITIAL] Ship is already docked, undocking...")
            ship_conn.disconnect()
            time.sleep(1)
            ship_conn.update()
            print(f"   [INITIAL] After undock status: {get_connector_status(ship_conn)}")

        if get_connector_status(ship_conn) == STATUS_READY_TO_LOCK:
            ship_conn.connect()

        if not is_parking_possible(base_conn):
            print(f"Base connector not ready for parking, status: {get_connector_status(base_conn)}")

        connector_pos = _parse_vector(base_conn.telemetry.get("position"))
        connector_orientation = base_conn.telemetry.get("orientation")

        # Вычислим вектор от RC к коннектору корабля
        rc_pos = _get_pos(rc)
        ship_conn_pos = _get_pos(ship_conn)

        # Вектор от корабля к коннектору базы для корректного смещения
        # approach_dir = _normalize(_sub(connector_pos, rc_pos))
        # rc_to_ship_conn_world = _sub(ship_conn_pos, rc_pos)
        # longitudinal_offset = _dot(rc_to_ship_conn_world, approach_dir)
        # rc_to_ship_conn = _scale(approach_dir, longitudinal_offset)

        rc_to_ship_conn = _sub(ship_conn_pos, rc_pos)
        print("rc_to_ship_conn (adjusted along ship-to-base vector)", rc_to_ship_conn)

        # if connector_pos != (1083866.5338009384,145816.5344619157, 1661753.3332283949):
        #     exit(0)


        print(connector_orientation)

        forward_vec = _parse_vector(connector_orientation.get("forward"))

        # Точка подхода: по линии коннектора, но в сторону "от базы", с учётом смещения
        approach_rc_pos = _sub(_add(connector_pos, _scale(forward_vec, 5.0)), rc_to_ship_conn)

        final_rc_pos = _sub(_add(connector_pos, _scale(forward_vec, 1.5)), rc_to_ship_conn)

        ship_grid.create_gps_marker("approach_rc_pos", coordinates=approach_rc_pos)

        current_rc_pos = _get_pos(rc)

        ship_conn.disconnect()


        # возле коннектора
        goto(ship_grid, approach_rc_pos, 100)
        print("GO")

        time.sleep(1)


        #точка коннектора
        goto(ship_grid, final_rc_pos, speed=1)
        time.sleep(1)



if __name__ == "__main__":

    dock_procedure(
        base_grid="DroneBase",
        # ship_grid_id="Owl",
        ship_grid="taburet",
    )
