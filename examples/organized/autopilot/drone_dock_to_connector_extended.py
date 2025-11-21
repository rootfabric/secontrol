from __future__ import annotations
import math
import time
from typing import Dict, Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice, BlockInfo
from secontrol.common import close, prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# ---- Settings ------------------------------------------------------------
ARRIVAL_DISTANCE = 0.20
RC_STOP_TOLERANCE = 2.0
CHECK_INTERVAL = 0.2
MAX_FLIGHT_TIME = 240.0
SPEED_DISTANCE_THRESHOLD = 15.0


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
    conn: ConnectorDevice,
    base_grid,
    fixed_base_gps: Optional[str],
) -> Tuple[Tuple[float, float, float], str]:
    """
    Get connector world position with priority:
    1) telemetry["position"] or ["worldPosition"]
    2) fixed_base_gps (if provided)
    3) reconstruction via Anchor RC + relative_to_grid_center
    """
    tel = conn.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    if p:
        pos = _parse_vector(p)
        if pos:
            return pos, "[POS] Using connector telemetry position."

    if fixed_base_gps:
        pos = _parse_vector(fixed_base_gps)
        if pos:
            return pos, "[POS] Using FIXED_GPS as connector position."

    print("   [Base] Calculating connector position via Anchor RC...")
    anchor = base_grid.find_devices_by_type(RemoteControlDevice)[0]
    _ensure_telemetry(anchor)
    anchor_pos = _get_pos(anchor)
    anchor_basis = _get_orientation(anchor)
    a_blk = _get_block_info(base_grid, anchor)
    t_blk = _get_block_info(base_grid, conn)
    d = _sub(_vec(t_blk.relative_to_grid_center), _vec(a_blk.relative_to_grid_center))
    world_diff = _add(
        _add(_scale(anchor_basis.right, d[0]), _scale(anchor_basis.up, d[1])),
        _scale(anchor_basis.forward, d[2]),
    )
    base_pos = _add(anchor_pos, world_diff)
    return base_pos, "[POS] Reconstructed connector position via Anchor RC."


# ---- Docking geometry ----------------------------------------------------


def _calculate_docking_point(
    ship_rc: RemoteControlDevice,
    ship_conn: ConnectorDevice,
    base_conn: ConnectorDevice,
    base_grid,
    fixed_base_gps: str = None,
) -> Tuple[Tuple[float, float, float],
           Tuple[float, float, float],
           Tuple[float, float, float]]:
    """
    Compute final RC position for docking.

    Логика:
    - Скрипт запускаем, когда дрон СТОИТ на парковке.
    - Берём:
        rc_pos_plan       = текущая позиция RC
        base_connector_pos = позиция коннектора базы
      и считаем
        offset_world = rc_pos_plan - base_connector_pos
    - При стыковке возвращаемся в
        final_rc_pos = base_connector_pos + offset_world

    То есть дрон возвращается ровно туда, где стоял при запуске скрипта.
    """

    # 1. Базис коннектора базы (нужен для вектора подхода)
    base_basis = _get_orientation(base_conn)

    # 2. Позиция коннектора базы
    base_pos, pos_info = _get_connector_world_pos(base_conn, base_grid, fixed_base_gps)
    print(f"   {pos_info}")

    # 3. Позиция RC в момент планирования (дрон ещё на парковке)
    rc_pos = _get_pos(ship_rc)
    if not rc_pos:
        raise RuntimeError("Cannot get RC world position for docking calculation.")

    start_dist = _dist(rc_pos, base_pos)
    print(f"   [PLAN] RC distance to base connector at plan time: {start_dist:.2f}m")

    # 4. ВСЕГДА используем мировое смещение RC от коннектора базы
    offset_world = _sub(rc_pos, base_pos)
    final_rc_pos = _add(base_pos, offset_world)

    print(
        "   [PLAN] Using WORLD offset RC - BaseConnector for docking target.\n"
        f"          Offset_world = ({offset_world[0]:.2f}, "
        f"{offset_world[1]:.2f}, {offset_world[2]:.2f})"
    )

    base_forward = base_basis.forward
    return final_rc_pos, base_forward, base_pos



# ---- Autopilot with logging ----------------------------------------------


def _fly_to(
    remote: RemoteControlDevice,
    target: Tuple[float, float, float],
    name: str,
    speed_far: float,
    speed_near: float,
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
        p = _get_pos(remote)
        if not p:
            time.sleep(CHECK_INTERVAL)
            continue

        stop_pos = p
        d = _dist(p, target)

        now = time.time()
        if now - last_print > 1.0 or d < 3.0:
            dx = target[0] - p[0]
            dy = target[1] - p[1]
            dz = target[2] - p[2]
            print(
                "   [FLY] CurrentPos(XYZ): "
                f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}) | "
                f"Dist: {d:.2f}m | "
                f"Delta(XYZ): ({dx:.2f}, {dy:.2f}, {dz:.2f})"
            )
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


# ---- Main logic ----------------------------------------------------------


def dock_procedure(base_grid_id: str, ship_grid_id: str, fixed_base_gps: str = None):
    ship_grid = prepare_grid(ship_grid_id)
    base_grid = prepare_grid(ship_grid.redis, base_grid_id)

    current_rc_pos = None
    final_rc_pos = None
    stop_pos_docking = None

    try:
        rc = ship_grid.find_devices_by_type(RemoteControlDevice)[0]
        ship_conn = ship_grid.find_devices_by_type(ConnectorDevice)[0]
        base_conn = base_grid.find_devices_by_type(ConnectorDevice)[0]

        _ensure_telemetry(rc)
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(base_conn)

        # Важно: здесь дрон ещё СТОИТ на парковке.
        # Считаем его "родную" точку стыковки.
        final_rc_pos, base_fwd, base_conn_pos = _calculate_docking_point(
            rc,
            ship_conn,
            base_conn,
            base_grid,
            fixed_base_gps,
        )

        # Точка подхода: на линии коннектора, но дальше в открытое пространство
        approach_rc_pos = _add(final_rc_pos, _scale(base_fwd, 20.0))

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
            "🎯 Final RC Position (Docking Point): "
            f"(X={final_rc_pos[0]:.2f}, Y={final_rc_pos[1]:.2f}, Z={final_rc_pos[2]:.2f})"
        )
        print("-------------------------------------------------------")

        input("\nPress Enter to Execute Docking Sequence...")

        _fly_to(rc, approach_rc_pos, "Approach", 15.0, 5.0)
        stop_pos_docking = _fly_to(rc, final_rc_pos, "Docking", 3.0, 0.5)

        print("Locking...")
        ship_conn.connect()

        time.sleep(0.5)
        ship_conn.update()
        status = ship_conn.telemetry.get("status") or ship_conn.telemetry.get("Status")
        print(f"Final Connector Status: {status}")

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

        if current_rc_pos and final_rc_pos and stop_pos_docking:
            print("\n=======================================================")
            print("                  --- RESULT ---")
            print("=======================================================")
            print(
                "🚀 RC Start Position: "
                f"(X={current_rc_pos[0]:.2f}, Y={current_rc_pos[1]:.2f}, Z={current_rc_pos[2]:.2f})"
            )
            print(
                "🎯 RC Final Target:   "
                f"(X={final_rc_pos[0]:.2f}, Y={final_rc_pos[1]:.2f}, Z={final_rc_pos[2]:.2f})"
            )
            print(
                "🛑 RC Actual Stop:    "
                f"(X={stop_pos_docking[0]:.2f}, Y={stop_pos_docking[1]:.2f}, Z={stop_pos_docking[2]:.2f})"
            )

            final_delta_to_target = _sub(final_rc_pos, stop_pos_docking)
            print("--- Deviation from Target (Target - Actual) ---")
            print(
                "   Delta (DX/DY/DZ): "
                f"({final_delta_to_target[0]:.2f}, "
                f"{final_delta_to_target[1]:.2f}, "
                f"{final_delta_to_target[2]:.2f})"
            )
            print(
                f"   Final Distance to Target: "
                f"{_dist(final_rc_pos, stop_pos_docking):.2f}m"
            )
            print("-----------------------------------------------")


if __name__ == "__main__":
    # Сейчас FIXED_GPS можно оставить None — коннектор имеет position в телеметрии.
    FIXED_GPS = None

    dock_procedure(
        base_grid_id="DroneBase",
        ship_grid_id="Owl",
        fixed_base_gps=FIXED_GPS,
    )

