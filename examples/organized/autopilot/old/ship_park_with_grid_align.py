from __future__ import annotations
import math
import time
from typing import Callable, Dict, Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice, BlockInfo
from secontrol.common import close, prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# ---- Settings ------------------------------------------------------------
ARRIVAL_DISTANCE = 0.20            # точность прилёта RC к цели
RC_STOP_TOLERANCE = 0.3            # если RC отключил АП < этого расстояния — считаем норм
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


def _dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _dot(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


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
    fixed_base_gps: Optional[str] = None,
) -> Tuple[Tuple[float, float, float], str]:
    """Получает мировую позицию коннектора базы (с учётом фиксированного GPS, если задан)."""
    if fixed_base_gps:
        base_pos = _parse_vector(fixed_base_gps)
        if base_pos:
            return base_pos, "   [POS] Using FIXED GPS for base connector."

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


# ---- Grid parking function -----------------------------------------------


def park_ship_grid_procedure(
    ship_grid,
    ship_conn: ConnectorDevice,
    timeout: float = 10.0,
) -> bool:
    """
    Паркует корабль: ждёт состояния коннектора, соединяет при готовности
    и паркует грид при соединении.
    """
    start_time = time.time()
    last_status = ""

    print("   [PARK] Monitoring connector status for parking...")

    while time.time() - start_time < timeout:
        ship_conn.update()
        status = get_connector_status(ship_conn)

        if status != last_status:
            print(f"   [PARK] Ship connector status: {status}")
            last_status = status

        if status == STATUS_CONNECTED:
            # Паркуем грид
            try:
                ship_grid.park()
                print("   [PARK] Grid parked successfully!")
                return True
            except Exception as e:
                print(f"   [PARK] Failed to park grid: {e}")
                return False

        if status == STATUS_READY_TO_LOCK:
            print("   [PARK] Ready to lock detected, connecting...")
            ship_conn.connect()
            time.sleep(0.5)
            ship_conn.update()
            final_status = get_connector_status(ship_conn)
            if final_status == STATUS_CONNECTED:
                # Паркуем после соединения
                try:
                    ship_grid.park()
                    print("   [PARK] Grid parked successfully!")
                    return True
                except Exception as e:
                    print(f"   [PARK] Failed to park grid: {e}")
                    return False
            else:
                print(f"   [PARK] Connect failed, final status: {final_status}")

        time.sleep(0.1)

    print("   [PARK] Timeout monitoring for parking.")
    return False


# ---- Grid alignment function ---------------------------------------------


def get_gravity_vector(device: BaseDevice) -> Optional[Tuple[float, float, float]]:
    """Получить вектор гравитации (up = -gravity_normalized)."""
    tel = device.telemetry or {}
    g = tel.get("gravitationalVector")
    if g:
        vec = _parse_vector(g)
        if vec:
            return vec
    return None


def align_ship_to_gravity(grid) -> None:
    """Выровнять корабль по гравитации (up = -gravity_direction)."""
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        print("Не найден RemoteControlDevice")
        return
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        print("Не найдены гироскопы")
        return

    for gyro in gyros:
        gyro.enable()

    gravity_vec = get_gravity_vector(rc_dev)
    if not gravity_vec:
        print("Вектор гравитации не найден")
        return

    desired_up = _normalize((-gravity_vec[0], -gravity_vec[1], -gravity_vec[2]))

    # Желательно upward
    if desired_up[1] < 0:
        desired_up = (-desired_up[0], -desired_up[1], -desired_up[2])

    print(f"Целевой up вектор по гравитации: ({desired_up[0]:.3f}, {desired_up[1]:.3f}, {desired_up[2]:.3f})")

    # Настройки PID (здесь только P - пропорциональный)
    GAIN = 2.0  # Коэффициент усиления ("резкость" поворота)
    MAX_RATE = 1.0  # Максимальная скорость вращения (1.0 = 100% override)
    TOLERANCE = 0.01  # Допустимая ошибка (в радианах, ~2 градуса)

    try:
        while True:
            rc_dev.update()

            try:
                basis = _get_orientation(rc_dev)
            except RuntimeError:
                continue

            # 1. Текущее отклонение (угол)
            dot_val = max(-1.0, min(1.0, _dot(basis.up, desired_up)))
            angle_error = math.acos(dot_val)

            if angle_error < TOLERANCE or (abs(dot_val) > 0.99 and dot_val > 0):
                # Выровнено
                print(f"Выровнено по гравитации. Ошибка: {angle_error:.4f} rad, команды отключены")
                for gyro in gyros:
                    gyro.clear_override()
                break
            else:
                # 2. Переводим целевой вектор в ЛОКАЛЬНЫЕ координаты корабля.
                # Для выравнивания Up: проекции на Forward и Right
                local_y = _dot(desired_up, basis.forward)
                local_x = _dot(desired_up, basis.right)

                roll_cmd = 0.0

                # Для Up: исправленный знак
                pitch_cmd = -local_y * GAIN

                # Если desired в right направлении, yaw -
                yaw_cmd = -local_x * GAIN

                # Логирование только при вращении
                print(
                    f"Angle: {angle_error:.3f} rad | "
                    f"Local tgt: [F={local_y:.2f}, R={local_x:.2f}] | "
                    f"CMD: R={roll_cmd:.2f}, P={pitch_cmd:.2f}, Y={yaw_cmd:.2f}"
                )

            # 3. Ограничиваем (Clamp) значения от -MAX_RATE до +MAX_RATE
            pitch_cmd = max(-MAX_RATE, min(MAX_RATE, pitch_cmd))
            yaw_cmd = max(-MAX_RATE, min(MAX_RATE, yaw_cmd))

            # 4. Применяем
            for gyro in gyros:
                gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            time.sleep(0.1)

    finally:
        # Всегда отключаем оверрайд при выходе
        print("Остановка гироскопов...")
        for gyro in gyros:
            gyro.clear_override()


def align_ship_to_base_orientation(grid, desired_up: Tuple[float, float, float]) -> None:
    """Align the ship grid orientation to match the desired up vector (e.g., base's up)."""
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        print("Не найден RemoteControlDevice")
        return
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        print("Не найдены гироскопы")
        return

    for gyro in gyros:
        gyro.enable()

    desired_up = _normalize(desired_up)

    print(f"Целевой up вектор: ({desired_up[0]:.3f}, {desired_up[1]:.3f}, {desired_up[2]:.3f})")

    # Настройки PID (здесь только P - пропорциональный)
    GAIN = 2.0  # Коэффициент усиления ("резкость" поворота)
    MAX_RATE = 1.0  # Максимальная скорость вращения (1.0 = 100% override)
    TOLERANCE = 0.01  # Допустимая ошибка (в радианах, ~2 градуса)

    try:
        while True:
            rc_dev.update()

            try:
                basis = _get_orientation(rc_dev)
            except RuntimeError:
                continue

            # 1. Текущее отклонение (угол)
            dot_val = max(-1.0, min(1.0, _dot(basis.up, desired_up)))
            angle_error = math.acos(dot_val)

            if angle_error < TOLERANCE or (abs(dot_val) > 0.99 and dot_val > 0):
                # Выровнено
                print(f"Выровнено. Ошибка: {angle_error:.4f} rad, команды отключены")
                for gyro in gyros:
                    gyro.clear_override()
                break
            else:
                # 2. Переводим целевой вектор в ЛОКАЛЬНЫЕ координаты корабля.
                # Для выравнивания Up: проекции на Forward и Right
                local_y = _dot(desired_up, basis.forward)
                local_x = _dot(desired_up, basis.right)

                roll_cmd = 0.0

                # Для Up: исправленный знак
                pitch_cmd = -local_y * GAIN

                # Если desired в right направлении, yaw -
                yaw_cmd = -local_x * GAIN

                # Логирование только при вращении
                print(
                    f"Angle: {angle_error:.3f} rad | "
                    f"Local tgt: [F={local_y:.2f}, R={local_x:.2f}] | "
                    f"CMD: R={roll_cmd:.2f}, P={pitch_cmd:.2f}, Y={yaw_cmd:.2f}"
                )

            # 3. Ограничиваем (Clamp) значения от -MAX_RATE до +MAX_RATE
            pitch_cmd = max(-MAX_RATE, min(MAX_RATE, pitch_cmd))
            yaw_cmd = max(-MAX_RATE, min(MAX_RATE, yaw_cmd))

            # 4. Применяем
            for gyro in gyros:
                gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            time.sleep(0.1)

    finally:
        # Всегда отключаем оверрайд при выходе
        print("Остановка гироскопов...")
        for gyro in gyros:
            gyro.clear_override()


# ---- Docking geometry ----------------------------------------------------


def _calculate_docking_point(
    ship_rc: RemoteControlDevice,
    ship_conn: ConnectorDevice,
    base_conn: ConnectorDevice,
    base_grid,
    fixed_base_gps: str = None,
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
            if d < ARRIVAL_DISTANCE:
                print(f"   [Info] Stopped near target ({d:.2f}m). Considered aligned.")
                break
            elif d < RC_STOP_TOLERANCE:
                print(f"   [Info] Stopped near target ({d:.2f}m). Considered aligned.")
                break
            else:
                print(f"   [Re-enable] AP disabled at dist {d:.2f}m. Re-enabling.")
                # Re-send the waypoint
                new_gps = f"GPS:{name}:retry:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"
                remote.goto(new_gps, speed=speed, gps_name=name + "_retry", dock=False)
                time.sleep(1.0)  # Wait for AP to engage

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
    ship_grid,
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

        # Шаг: максимум 3м, минимум 0.5м, примерно 60% от текущего расстояния
        step_len = max(0.5, min(3.0, dist_cb * 0.6))
        move_vec = _scale(dir_norm, step_len)
        target_rc = _add(rc_pos, move_vec)

        def check_callback_for_dock():
            status = get_connector_status(ship_conn)
            if status == STATUS_READY_TO_LOCK:
                print("   [CB] Ready to lock, connecting...")
                ship_conn.connect()
                time.sleep(0.5)
                ship_conn.update()
                if get_connector_status(ship_conn) == STATUS_CONNECTED:
                    print("   [CB] Connected, parking...")
                    park_ship_grid_procedure(ship_grid, ship_conn, timeout=5.0)
                    rc.disable()
                    return True
            elif status == STATUS_CONNECTED:
                print("   [CB] Already connected, parking...")
                park_ship_grid_procedure(ship_grid, ship_conn, timeout=5.0)
                rc.disable()
                return True
            return False

        stop_pos = _fly_to(
            rc,
            target_rc,
            f"DockStep#{step_idx}",
            speed_far=1.5,
            speed_near=0.6,
            check_callback=check_callback_for_dock,
            ship_conn=ship_conn,
            ship_conn_target=base_target_pos,
            fixed_base_pos=base_target_pos,
        )

        # Если АП не стартовал (например, цель слишком близко) — считаем, что дальше не пролезть
        if stop_pos is None:
            print("   [DOCK] Autopilot did not start on fine step, stopping.")
            break

    return stop_pos


# ---- Main logic ----------------------------------------------------------


def ship_dock_with_grid_align_procedure(base_grid_id: str, ship_grid_id: str, fixed_base_gps: str = None):
    ship_grid = prepare_grid(ship_grid_id)
    base_grid = prepare_grid(ship_grid.redis, base_grid_id)

    current_rc_pos = None
    final_rc_pos_for_log = None
    stop_pos_docking = None

    try:
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

        _ensure_telemetry(rc)
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(base_conn)

        # ---- Check initial status ----
        print(f"   [INITIAL] Ship connector status: {get_connector_status(ship_conn)}")
        print(f"   [INITIAL] Base connector status: {get_connector_status(base_conn)}")

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

        (
            final_rc_pos,
            base_fwd,
            base_conn_pos,
            base_up,
            ship_conn_target,
        ) = _calculate_docking_point(
            rc,
            ship_conn,
            base_conn,
            base_grid,
            fixed_base_gps,
        )
        final_rc_pos_for_log = final_rc_pos

        # Точка подхода: по линии коннектора, но в сторону "от базы"
        approach_rc_pos = _add(final_rc_pos, _scale(base_fwd, 5.0))

        current_rc_pos = _get_pos(rc)

        print("\n=======================================================")
        print("                   --- PLAN ---")
        print("=======================================================")
        print(
            "🚀 Ship RC Current Position: "
            f"(X={current_rc_pos[0]:.2f}, Y={current_rc_pos[1]:.2f}, Z={current_rc_pos[2]:.2f})"
        )
        print(
            "⚓ Base Connector Position (Target): "
            f"(X={base_conn_pos[0]:.2f}, Y={base_conn_pos[1]:.2f}, Z={base_conn_pos[2]:.2f})"
        )
        print(
            f"   [PLAN] Ship connector target position: "
            f"({ship_conn_target[0]:.2f}, {ship_conn_target[1]:.2f}, {ship_conn_target[2]:.2f})"
        )
        print(
            "🎯 Final RC Position (Docking Point, coarse): "
            f"(X={final_rc_pos[0]:.2f}, Y={final_rc_pos[1]:.2f}, Z={final_rc_pos[2]:.2f})"
        )

        ship_conn.disconnect()

        # 0) Предварительное выравнивание по гравитации для плавного подхода
        print("   [ALIGN] Pre-aligning ship to gravity for smoother approach...")
        align_ship_to_gravity(ship_grid)

        # 1) Летим в точку подхода
        _fly_to(rc, approach_rc_pos, "Approach", 15.0, 5.0)

        # 2) Тонкий докинг по вектору коннектор->база (без финального выравнивания по базе, чтобы избежать подъёма носа)
        stop_pos_docking = _dock_by_connector_vector(
            rc,
            ship_conn,
            base_conn,
            ship_grid,
            fixed_base_gps,
        )

        # Проверка на ручную парковку, если близко и не подключено
        if stop_pos_docking and get_connector_status(ship_conn) != STATUS_CONNECTED:
            _ensure_telemetry(ship_conn)
            ship_conn_pos = _get_pos(ship_conn)
            base_conn_pos = _parse_vector(fixed_base_gps) if fixed_base_gps else _get_pos(base_conn)
            if ship_conn_pos and base_conn_pos:
                manual_dist = _dist(ship_conn_pos, base_conn_pos)
                if manual_dist < 1.0:
                    print(f"   [MANUAL PARK] ShipConn dist {manual_dist:.3f} < 1.0m, attempting manual connect.")
                    ship_conn.connect()
                    time.sleep(0.5)
                    ship_conn.update()
                    if get_connector_status(ship_conn) == STATUS_CONNECTED:
                        park_ship_grid_procedure(ship_grid, ship_conn)

        # 4) Ожидаем ReadyToLock и коннектим
        print("   [DOCKING] Waiting for connector to become ready to lock...")
        locked = False
        last_status = ""
        while not locked:
            ship_conn.update()
            status = get_connector_status(ship_conn)
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
                    park_ship_grid_procedure(ship_grid, ship_conn)
                else:
                    print(f"   [DOCKING] Connect failed, final status: {final_status}")
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

        if current_rc_pos and final_rc_pos_for_log and stop_pos_docking:
            print("\n=======================================================")
            print("                  --- RESULT ---")
            print("=======================================================")
            print(
                "🚀 RC Start Position: "
                f"(X={current_rc_pos[0]:.2f}, Y={current_rc_pos[1]:.2f}, Z={current_rc_pos[2]:.2f})"
            )
            print(
                "🎯 RC Final Target (coarse plan):   "
                f"(X={final_rc_pos_for_log[0]:.2f}, Y={final_rc_pos_for_log[1]:.2f}, Z={final_rc_pos_for_log[2]:.2f})"
            )
            print(
                "🛑 RC Actual Stop (after fine dock): "
                f"(X={stop_pos_docking[0]:.2f}, Y={stop_pos_docking[1]:.2f}, Z={stop_pos_docking[2]:.2f})"
            )

            final_delta_to_target = _sub(final_rc_pos_for_log, stop_pos_docking)
            print("--- Deviation from Coarse Target (InitialTarget - ActualStop) ---")
            print(
                "   Delta (DX/DY/DZ): "
                f"({final_delta_to_target[0]:.2f}, "
                f"{final_delta_to_target[1]:.2f}, {final_delta_to_target[2]:.2f})"
            )
            print(
                f"   Final Distance to Coarse Target: "
                f"{_dist(final_rc_pos_for_log, stop_pos_docking):.2f}m"
            )
            print("-----------------------------------------------")


if __name__ == "__main__":
    # FIXED_GPS — точные координаты коннектора на базе
    # FIXED_GPS = "GPS:root #2:1010037.18:170826.7:1672421.04:#FF75C9F1:"
    FIXED_GPS = None

    ship_dock_with_grid_align_procedure(
        base_grid_id="DroneBase",
        # ship_grid_id="Owl",
        ship_grid_id="taburet",
        fixed_base_gps=FIXED_GPS,
    )
