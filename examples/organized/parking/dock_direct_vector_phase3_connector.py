#!/usr/bin/env python3
"""
=== DOCKING: Full automated docking sequence ===

One script to dock a ship to a target grid's connector:
  Phase 1: Fly to approach point (100m in front of target connector)
  Phase 2: Rotate ship so connector faces target connector
  Phase 3: Approach along connector axis + auto-lock

Usage: python dock.py [ship_id] [target_id] [approach_distance]
  ship_id   — grid ID or name (default: skynet-baza2)
  target_id — grid ID or name (default: Static Grid 6422 / skynet-farpost0)
  approach_distance — meters in front of connector for approach point (default: 100)

Examples:
  python dock.py 104571351454649539 84360909276756422
  python dock.py skynet-baza2 skynet-farpost0 80
"""
import sys, os, time, math

# --- Load .env (handles \r\n) ---
env_path = '/workspace/.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

sys.path.insert(0, "/workspace/src")
from secontrol.common import prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.thruster_device import ThrusterDevice

SHIP = sys.argv[1] if len(sys.argv) > 1 else "104571351454649539"
TARGET = sys.argv[2] if len(sys.argv) > 2 else "84360909276756422"
APPROACH_DIST = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0

# Settings
GYRO_GAIN = 0.3
MAX_RATE = 0.3
ALIGN_TOLERANCE = 0.1      # radians (~5.7°)
DOCK_DISTANCE = 3.0         # try connect() when closer than this
PHASE3_STEP_FAST = 15.0     # meters per step when far
PHASE3_STEP_SLOW = 5.0      # meters per step medium
PHASE3_STEP_CREEP = 1.0     # meters per step close
PHASE3_SPEED_FAST = 3.0     # m/s
PHASE3_SPEED_SLOW = 1.0
PHASE3_SPEED_CREEP = 0.5

# Safety guard for final docking. If the ship is already close but the
# connector angle becomes too large, continuing forward usually makes the
# ship scrape/overshoot. Direct-vector Phase 3 uses the same guard, but
# performs backoff with direct thruster control instead of RC autopilot.
SAFE_NEAR_DISTANCE = float(os.getenv("SE_DOCK_SAFE_NEAR_DISTANCE", "12.0"))
SAFE_ANGLE_JUMP_DEG = float(os.getenv("SE_DOCK_SAFE_ANGLE_JUMP_DEG", "20.0"))
SAFE_PANIC_ANGLE_DEG = float(os.getenv("SE_DOCK_SAFE_PANIC_ANGLE_DEG", "85.0"))
SAFE_BACKOFF_DISTANCE = float(os.getenv("SE_DOCK_SAFE_BACKOFF_DISTANCE", "10.0"))
SAFE_BACKOFF_SPEED = float(os.getenv("SE_DOCK_SAFE_BACKOFF_SPEED", "1.5"))
SAFE_BACKOFF_TIMEOUT = float(os.getenv("SE_DOCK_SAFE_BACKOFF_TIMEOUT", "22.0"))
SAFE_MAX_BACKOFFS = int(os.getenv("SE_DOCK_SAFE_MAX_BACKOFFS", "4"))

# =====================================================================
# Utility functions
# =====================================================================
def dist3(a, b):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))

def normalize(v):
    l = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    return (v[0]/l, v[1]/l, v[2]/l) if l > 1e-10 else (0, 0, 0)

def dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

def vec_sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def vec_add(a, s, v):
    return (a[0]+s*v[0], a[1]+s*v[1], a[2]+s*v[2])

def get_vec3(data):
    if not data: return None
    return (float(data.get("x",0)), float(data.get("y",0)), float(data.get("z",0)))

def get_pos(telemetry):
    d = telemetry.get("pos") or telemetry.get("position")
    if not d: return None
    return (float(d["x"]), float(d["y"]), float(d["z"]))

def get_body_frame(rc):
    orient = (rc.telemetry or {}).get("orientation", {})
    fwd = normalize(get_vec3(orient.get("forward")) or (0,0,0))
    up = normalize(get_vec3(orient.get("up")) or (0,0,0))
    right = normalize(cross(up, fwd))
    return fwd, up, right

def check_connector(connector):
    """Return (is_connected, status_str, other_id)."""
    t = connector.telemetry or {}
    return (
        t.get("connectorIsConnected", False),
        t.get("connectorStatus", ""),
        t.get("otherConnectorId"),
    )

def try_connect(sc, label="", axis_dist=None):
    """Try to lock connector. Returns True if locked."""
    is_conn, status, _ = check_connector(sc)
    if is_conn:
        return True
    if axis_dist is not None and axis_dist < 0.5:
        print(f"  {label}Physical contact (dist={axis_dist:.1f}m) — considering docked")
        return True
    if status == "Connectable":
        print(f"  {label}Connector sees target — sending connect()...")
        sc.connect()
        for _ in range(8):
            time.sleep(0.5)
            is_conn, status, _ = check_connector(sc)
            if is_conn:
                print(f"  {label}>> LOCKED!")
                return True
            if status != "Connectable":
                print(f"  {label}Status changed to {status}")
        print(f"  {label}Not locked yet (status={status})")
    return False

# =====================================================================
# Gyro orientation correction
# =====================================================================
def correct_orientation(rc, sc, gyros, axis_dir, timeout=8):
    """Rotate ship so connector forward aligns with axis_dir."""
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.3)
        sc_orient = (sc.telemetry or {}).get("orientation", {})
        sc_fwd = normalize(get_vec3(sc_orient.get("forward")) or (0,0,0))
        angle_err = math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))
        if angle_err < ALIGN_TOLERANCE:
            for g in gyros: g.clear_override()
            return angle_err

        ship_fwd, ship_up, ship_right = get_body_frame(rc)
        conn_pitch = math.atan2(dot(sc_fwd, ship_up), dot(sc_fwd, ship_fwd))
        des_pitch = math.atan2(dot(axis_dir, ship_up), dot(axis_dir, ship_fwd))
        pitch_err = (des_pitch - conn_pitch + math.pi) % (2*math.pi) - math.pi

        conn_yaw = math.atan2(dot(sc_fwd, ship_right), dot(sc_fwd, ship_fwd))
        des_yaw = math.atan2(dot(axis_dir, ship_right), dot(axis_dir, ship_fwd))
        yaw_err = (des_yaw - conn_yaw + math.pi) % (2*math.pi) - math.pi

        rate = min(MAX_RATE, angle_err * GYRO_GAIN)
        pitch_cmd = max(-rate, min(rate, -pitch_err * GYRO_GAIN))
        yaw_cmd = max(-rate, min(rate, -yaw_err * GYRO_GAIN))
        for g in gyros: g.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

    for g in gyros: g.clear_override()
    sc_orient = (sc.telemetry or {}).get("orientation", {})
    sc_fwd = normalize(get_vec3(sc_orient.get("forward")) or (0,0,0))
    return math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))

def compute_ship_target(rc, sc, axis_dir, move_dist):
    """Where ship center must be so connector moves move_dist along axis."""
    rc_pos = get_pos(rc.telemetry or {})
    sc_pos = get_pos(sc.telemetry or {})
    if not rc_pos or not sc_pos: return None
    offset = vec_sub(sc_pos, rc_pos)
    return vec_sub(vec_add(sc_pos, move_dist, axis_dir), offset)


def refresh_devices(*devices, delay=0.1):
    for device in devices:
        try:
            device.update()
        except Exception:
            pass
    if delay > 0:
        time.sleep(delay)


def get_connector_forward(sc):
    sc_orient = (sc.telemetry or {}).get("orientation", {})
    return normalize(get_vec3(sc_orient.get("forward")) or (0, 0, 0))


def get_connector_angle(sc, axis_dir):
    sc_fwd = get_connector_forward(sc)
    return math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))


def should_backoff(axis_dist, angle_deg, previous_angle_deg):
    """Back off only close to connector and only on a sharp angle jump/panic angle."""
    if axis_dist > SAFE_NEAR_DISTANCE:
        return False, ""

    if previous_angle_deg is None:
        if angle_deg >= SAFE_PANIC_ANGLE_DEG:
            return True, f"panic angle near connector: dist={axis_dist:.1f}m angle={angle_deg:.1f}°"
        return False, ""

    angle_jump = abs(angle_deg - previous_angle_deg)
    if angle_jump >= SAFE_ANGLE_JUMP_DEG:
        return True, (
            f"sharp angle change near connector: dist={axis_dist:.1f}m "
            f"angle={previous_angle_deg:.1f}° -> {angle_deg:.1f}°"
        )

    if angle_deg >= SAFE_PANIC_ANGLE_DEG:
        return True, f"panic angle near connector: dist={axis_dist:.1f}m angle={angle_deg:.1f}°"

    return False, ""


# =====================================================================
# Direct vector flight helpers for Phase 3
# =====================================================================
DIRECT_TICK = float(os.getenv("SE_DOCK_DIRECT_TICK", "0.30"))
DIRECT_MAX_THRUST_FAST = float(os.getenv("SE_DOCK_DIRECT_THRUST_FAST", "18.0"))
DIRECT_MAX_THRUST_SLOW = float(os.getenv("SE_DOCK_DIRECT_THRUST_SLOW", "12.0"))
DIRECT_MAX_THRUST_CREEP = float(os.getenv("SE_DOCK_DIRECT_THRUST_CREEP", "7.0"))
DIRECT_MIN_THRUST_DOT = float(os.getenv("SE_DOCK_DIRECT_MIN_THRUST_DOT", "0.10"))
DIRECT_THRUST_EXPONENT = float(os.getenv("SE_DOCK_DIRECT_THRUST_EXPONENT", "1.35"))
DIRECT_VEL_GAIN = float(os.getenv("SE_DOCK_DIRECT_VEL_GAIN", "0.24"))
DIRECT_GYRO_GAIN = float(os.getenv("SE_DOCK_DIRECT_GYRO_GAIN", "1.45"))
DIRECT_MAX_GYRO = float(os.getenv("SE_DOCK_DIRECT_MAX_GYRO", "0.30"))
DIRECT_PITCH_SIGN = float(os.getenv("SE_GYRO_SIGN_PITCH", "-1"))
DIRECT_YAW_SIGN = float(os.getenv("SE_GYRO_SIGN_YAW", "-1"))
DIRECT_ROLL_SIGN = float(os.getenv("SE_GYRO_SIGN_ROLL", "-1"))
DIRECT_POS_TOLERANCE = float(os.getenv("SE_DOCK_DIRECT_POS_TOLERANCE", "0.75"))
DIRECT_SPEED_TOLERANCE = float(os.getenv("SE_DOCK_DIRECT_SPEED_TOLERANCE", "0.35"))
DIRECT_ANGLE_TOL_DEG = float(os.getenv("SE_DOCK_DIRECT_ANGLE_TOL_DEG", "4.0"))
DIRECT_TELEMETRY_WAIT = float(os.getenv("SE_DOCK_DIRECT_TELEMETRY_WAIT", "1.5"))


def dv_len(v):
    return math.sqrt(dot(v, v))


def dv_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def dv_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dv_mul(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def dv_div(v, k):
    if abs(k) <= 1e-10:
        return (0.0, 0.0, 0.0)
    return (v[0] / k, v[1] / k, v[2] / k)


def dv_clamp(x, lo, hi):
    return max(lo, min(hi, x))


def dv_limit(v, max_len):
    l = dv_len(v)
    if l <= max_len or l <= 1e-10:
        return v
    return dv_mul(v, max_len / l)


def dv_angle_between(a, b):
    an = normalize(a)
    bn = normalize(b)
    return math.acos(dv_clamp(dot(an, bn), -1.0, 1.0))


def dv_vec_from_obj(value):
    if isinstance(value, dict):
        try:
            return (float(value.get("x", 0.0)), float(value.get("y", 0.0)), float(value.get("z", 0.0)))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
        if len(parts) == 3:
            try:
                return (float(parts[0]), float(parts[1]), float(parts[2]))
            except ValueError:
                return None
    return None


def dv_get_thruster_direction(thruster):
    t = thruster.telemetry or {}

    direction = dv_vec_from_obj(t.get("thrustDirection"))
    if direction and dv_len(direction) > 1e-8:
        return normalize(direction), "thrustDirection"

    orient = t.get("orientation") or {}
    forward = dv_vec_from_obj(orient.get("forward"))
    if forward and dv_len(forward) > 1e-8:
        return normalize(dv_mul(forward, -1.0)), "-orientation.forward"

    return None, "missing"


def dv_get_max_thrust(thruster):
    t = thruster.telemetry or {}
    for key in ("maxThrust", "MaxThrust", "maxEffectiveThrust"):
        try:
            value = float(t.get(key))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return 1.0


def dv_build_thruster_infos(thrusters):
    refresh_devices(*thrusters, delay=DIRECT_TELEMETRY_WAIT)

    infos = []
    source_count = {}

    for thruster in thrusters:
        direction, source = dv_get_thruster_direction(thruster)
        source_count[source] = source_count.get(source, 0) + 1
        if direction is None:
            continue
        infos.append({
            "device": thruster,
            "direction": direction,
            "max_thrust": dv_get_max_thrust(thruster),
            "source": source,
        })

    print(
        "  Thruster direction sources: "
        + ", ".join(f"{key}={value}" for key, value in sorted(source_count.items()))
    )
    return infos


def dv_set_thruster(thruster, pct):
    value = dv_clamp(float(pct), 0.0, 100.0)
    try:
        thruster.set_thrust(override=value, enabled=True)
    except Exception as exc:
        print(f"  WARN: thruster command failed {thruster.name or thruster.device_id}: {exc}")


def dv_clear_thrusters(thrusters):
    for thruster in thrusters:
        try:
            thruster.set_thrust(override=0.0, enabled=True)
        except Exception:
            try:
                thruster.clear_override()
            except Exception:
                pass


def dv_apply_force_vector(thruster_infos, force_vector, max_pct):
    magnitude = dv_len(force_vector)
    if magnitude <= 1e-5:
        for info in thruster_infos:
            dv_set_thruster(info["device"], 0.0)
        return 0, 0.0

    desired_dir = normalize(force_vector)
    active = 0
    max_sent = 0.0

    for info in thruster_infos:
        score = dot(info["direction"], desired_dir)
        if score <= DIRECT_MIN_THRUST_DOT:
            pct = 0.0
        else:
            pct = max_pct * (score ** DIRECT_THRUST_EXPONENT) * dv_clamp(magnitude, 0.0, 1.0)

        if pct > 0.01:
            active += 1
            max_sent = max(max_sent, pct)

        dv_set_thruster(info["device"], pct)

    return active, max_sent


def dv_clear_gyros(gyros):
    for gyro in gyros:
        try:
            gyro.clear_override()
        except Exception:
            pass


def dv_enable_gyros(gyros):
    for gyro in gyros:
        try:
            gyro.enable()
        except Exception:
            pass


def dv_apply_orientation_control(gyros, current_frame, desired_frame):
    cur_fwd, cur_up, cur_right = current_frame
    des_fwd, des_up, _ = desired_frame

    forward_err = dv_angle_between(cur_fwd, des_fwd)
    up_err = dv_angle_between(cur_up, des_up)
    total_err = max(forward_err, up_err)

    if total_err < math.radians(DIRECT_ANGLE_TOL_DEG * 0.35):
        dv_clear_gyros(gyros)
        return total_err, 0.0, 0.0, 0.0

    error_world = dv_add(cross(cur_fwd, des_fwd), cross(cur_up, des_up))

    pitch = dv_clamp(-dot(error_world, cur_right) * DIRECT_GYRO_GAIN * DIRECT_PITCH_SIGN, -DIRECT_MAX_GYRO, DIRECT_MAX_GYRO)
    yaw = dv_clamp(-dot(error_world, cur_up) * DIRECT_GYRO_GAIN * DIRECT_YAW_SIGN, -DIRECT_MAX_GYRO, DIRECT_MAX_GYRO)
    roll = dv_clamp(-dot(error_world, cur_fwd) * DIRECT_GYRO_GAIN * DIRECT_ROLL_SIGN, -DIRECT_MAX_GYRO, DIRECT_MAX_GYRO)

    for gyro in gyros:
        try:
            gyro.set_override(pitch=pitch, yaw=yaw, roll=roll)
        except Exception as exc:
            print(f"  WARN: gyro command failed {gyro.name or gyro.device_id}: {exc}")

    return total_err, pitch, yaw, roll


def dv_filtered_velocity(pos, previous_pos, previous_time, previous_velocity):
    now = time.time()
    if pos is None or previous_pos is None or previous_time is None:
        return previous_velocity
    dt = max(1e-3, now - previous_time)
    measured = dv_div(dv_sub(pos, previous_pos), dt)
    return dv_add(dv_mul(previous_velocity, 0.65), dv_mul(measured, 0.35))


def dv_speed_from_telemetry(rc, velocity):
    t = rc.telemetry or {}
    for key in ("speed", "linearSpeed", "velocityLength"):
        try:
            value = float(t.get(key))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return dv_len(velocity)


def dv_prepare_direct_controls(rc, gyros, thrusters):
    try:
        rc.disable()
    except Exception:
        pass
    try:
        rc.gyro_control_off()
    except Exception:
        pass
    try:
        rc.thrusters_on()
    except Exception:
        pass
    try:
        rc.dampeners_off()
    except Exception:
        pass
    dv_enable_gyros(gyros)
    dv_clear_gyros(gyros)
    dv_clear_thrusters(thrusters)


def dv_finish_direct_controls(rc, gyros, thrusters, dampeners=True):
    dv_clear_thrusters(thrusters)
    dv_clear_gyros(gyros)
    if dampeners:
        try:
            rc.dampeners_on()
        except Exception:
            pass
    try:
        rc.disable()
    except Exception:
        pass


def dv_apply_connector_axis_control(gyros, rc, sc, axis_dir):
    """Keep the ship connector forward vector aligned with the live connector-to-connector axis."""
    sc_fwd = get_connector_forward(sc)
    if dv_len(sc_fwd) <= 1e-8 or dv_len(axis_dir) <= 1e-8:
        dv_clear_gyros(gyros)
        return 0.0, 0.0, 0.0, 0.0

    angle_err = math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))
    if angle_err < math.radians(DIRECT_ANGLE_TOL_DEG * 0.35):
        dv_clear_gyros(gyros)
        return angle_err, 0.0, 0.0, 0.0

    ship_fwd, ship_up, ship_right = get_body_frame(rc)
    if dv_len(ship_fwd) <= 1e-8 or dv_len(ship_up) <= 1e-8 or dv_len(ship_right) <= 1e-8:
        dv_clear_gyros(gyros)
        return angle_err, 0.0, 0.0, 0.0

    conn_pitch = math.atan2(dot(sc_fwd, ship_up), dot(sc_fwd, ship_fwd))
    des_pitch = math.atan2(dot(axis_dir, ship_up), dot(axis_dir, ship_fwd))
    pitch_err = (des_pitch - conn_pitch + math.pi) % (2.0 * math.pi) - math.pi

    conn_yaw = math.atan2(dot(sc_fwd, ship_right), dot(sc_fwd, ship_fwd))
    des_yaw = math.atan2(dot(axis_dir, ship_right), dot(axis_dir, ship_fwd))
    yaw_err = (des_yaw - conn_yaw + math.pi) % (2.0 * math.pi) - math.pi

    rate = min(DIRECT_MAX_GYRO, max(0.04, angle_err * DIRECT_GYRO_GAIN))
    pitch = dv_clamp(-pitch_err * DIRECT_GYRO_GAIN * DIRECT_PITCH_SIGN, -rate, rate)
    yaw = dv_clamp(-yaw_err * DIRECT_GYRO_GAIN * DIRECT_YAW_SIGN, -rate, rate)
    roll = 0.0

    for gyro in gyros:
        try:
            gyro.set_override(pitch=pitch, yaw=yaw, roll=roll)
        except Exception as exc:
            print(f"  WARN: gyro command failed {gyro.name or gyro.device_id}: {exc}")

    return angle_err, pitch, yaw, roll


def dv_direct_move_connector_offset(
    rc,
    sc,
    tc,
    gyros,
    thrusters,
    thruster_infos,
    axis_dir,
    move_dist,
    speed,
    max_thrust_pct,
    timeout,
    label,
):
    """Move by controlling the ship connector position, not the RC/cockpit position.

    Docking mode:
      axis_dir points from ship connector to target connector. The controller
      recomputes target connector coordinates every tick and drives the ship
      connector to tc_pos - axis_dir * target_axis_distance.

    Backoff mode:
      axis_dir points away from target connector. The controller drives the
      ship connector to a fixed point away from the target connector.
    """
    refresh_devices(rc, sc, tc, delay=0.05)
    sc_start = get_pos(sc.telemetry or {})
    tc_start = get_pos(tc.telemetry or {})
    if not sc_start or not tc_start:
        return False, False

    start_axis_vec = vec_sub(tc_start, sc_start)
    start_axis_dist = dv_len(start_axis_vec)
    start_axis_dir = normalize(start_axis_vec)
    cmd_axis = normalize(axis_dir)
    if dv_len(cmd_axis) <= 1e-8:
        return False, False

    # If command axis points to the target connector, this is a docking move.
    # If it points away, this is a safety/backoff move.
    docking_mode = dot(cmd_axis, start_axis_dir) >= 0.25
    target_axis_dist = max(0.35, start_axis_dist - max(0.0, move_dist))
    fixed_backoff_target = dv_add(sc_start, dv_mul(cmd_axis, max(0.0, move_dist)))

    if docking_mode:
        print(
            f"  DIRECT {label}: connector-relative docking move={move_dist:.2f}m "
            f"axis {start_axis_dist:.2f}m -> {target_axis_dist:.2f}m "
            f"speed={speed:.2f}m/s maxThrust={max_thrust_pct:.1f}%"
        )
    else:
        print(
            f"  DIRECT {label}: connector-relative backoff move={move_dist:.2f}m "
            f"speed={speed:.2f}m/s maxThrust={max_thrust_pct:.1f}%"
        )

    dv_prepare_direct_controls(rc, gyros, thrusters)

    previous_sc_pos = sc_start
    previous_time = time.time()
    connector_velocity = (0.0, 0.0, 0.0)
    hold_frame = get_body_frame(rc)
    started = time.time()
    last_print = 0.0
    connected = False
    reached = False

    try:
        while time.time() - started < timeout:
            loop_started = time.time()
            refresh_devices(rc, sc, tc, delay=0.02)

            sc_pos = get_pos(sc.telemetry or {})
            tc_pos = get_pos(tc.telemetry or {})
            if not sc_pos or not tc_pos:
                time.sleep(DIRECT_TICK)
                continue

            live_axis_vec = vec_sub(tc_pos, sc_pos)
            live_axis_dist = dv_len(live_axis_vec)
            live_axis_dir = normalize(live_axis_vec) if live_axis_dist > 1e-8 else cmd_axis

            if try_connect(sc, "  ", live_axis_dist):
                connected = True
                reached = True
                break

            if docking_mode:
                # The point where the ship connector itself should be.
                # This follows the target connector if the station/grid moves.
                connector_target = dv_sub(tc_pos, dv_mul(live_axis_dir, target_axis_dist))
                target_axis_for_gyro = live_axis_dir
            else:
                connector_target = fixed_backoff_target
                target_axis_for_gyro = None

            now = time.time()
            connector_velocity = dv_filtered_velocity(sc_pos, previous_sc_pos, previous_time, connector_velocity)
            previous_sc_pos = sc_pos
            previous_time = now

            to_target = dv_sub(connector_target, sc_pos)
            target_dist = dv_len(to_target)
            target_dir = normalize(to_target) if target_dist > 1e-8 else (0.0, 0.0, 0.0)

            slow_radius = max(1.2, min(10.0, max(abs(move_dist), live_axis_dist) * 0.75))
            speed_limit = speed * dv_clamp(target_dist / slow_radius, 0.12, 1.0)

            # Near the target connector, never add side velocity on purpose.
            # This makes the connector walk straight along the live connector axis.
            if docking_mode and live_axis_dist <= SAFE_NEAR_DISTANCE:
                target_dir = live_axis_dir
                target_dist = max(0.0, live_axis_dist - target_axis_dist)
                speed_limit = min(speed_limit, PHASE3_SPEED_CREEP)

            desired_velocity = dv_mul(target_dir, speed_limit)
            velocity_error = dv_sub(desired_velocity, connector_velocity)
            force_vector = dv_limit(dv_mul(velocity_error, DIRECT_VEL_GAIN), 1.0)

            active, max_sent = dv_apply_force_vector(thruster_infos, force_vector, max_thrust_pct)

            if docking_mode:
                angle_err, pitch, yaw, roll = dv_apply_connector_axis_control(
                    gyros, rc, sc, target_axis_for_gyro
                )
            else:
                frame = get_body_frame(rc)
                if frame and hold_frame:
                    angle_err, pitch, yaw, roll = dv_apply_orientation_control(gyros, frame, hold_frame)
                else:
                    angle_err, pitch, yaw, roll = 0.0, 0.0, 0.0, 0.0

            speed_now = dv_len(connector_velocity)
            elapsed = now - started

            if elapsed - last_print >= 1.0:
                target_text = f"target={target_dist:5.2f}m"
                print(
                    f"    [{elapsed:5.1f}s] {target_text} conn_axis={live_axis_dist:5.2f}m "
                    f"speed={speed_now:4.2f}m/s angle={math.degrees(angle_err):4.1f}° "
                    f"thr={active:2d}/{len(thruster_infos)} pct={max_sent:4.1f} "
                    f"gyro=({pitch:+.2f},{yaw:+.2f},{roll:+.2f})"
                )
                last_print = elapsed

            if target_dist <= DIRECT_POS_TOLERANCE and speed_now <= DIRECT_SPEED_TOLERANCE:
                reached = True
                break

            spent = time.time() - loop_started
            time.sleep(max(0.02, DIRECT_TICK - spent))

    finally:
        dv_finish_direct_controls(rc, gyros, thrusters, dampeners=True)
        time.sleep(0.2)
        refresh_devices(rc, sc, tc, delay=0.05)

    return reached, connected

def dv_direct_backoff(rc, sc, tc, gyros, thrusters, thruster_infos, distance=None):
    if distance is None:
        distance = SAFE_BACKOFF_DISTANCE
    refresh_devices(rc, sc, tc, delay=0.1)
    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})
    if not sc_pos or not tc_pos:
        print("  DIRECT SAFETY: cannot back off, connector positions are missing")
        return False
    away_dir = normalize(vec_sub(sc_pos, tc_pos))
    if away_dir == (0, 0, 0):
        print("  DIRECT SAFETY: cannot back off, connector axis is zero")
        return False
    ok, _ = dv_direct_move_connector_offset(
        rc, sc, tc, gyros, thrusters, thruster_infos,
        away_dir, distance, SAFE_BACKOFF_SPEED,
        DIRECT_MAX_THRUST_SLOW, SAFE_BACKOFF_TIMEOUT, "BACKOFF"
    )
    return ok

# =====================================================================
# MAIN
# =====================================================================
print("=" * 60)
print("AUTOMATED DOCKING SEQUENCE")
print("=" * 60)

# --- Load grids ---
print(f"\n[LOAD] Loading grids...")
target_grid = prepare_grid(TARGET)
time.sleep(2)
ship = prepare_grid(SHIP)
time.sleep(2)

rc = ship.get_first_device(RemoteControlDevice)
sc = ship.find_devices_by_type(ConnectorDevice)[0]
tc = target_grid.find_devices_by_type(ConnectorDevice)[0]
gyros = ship.find_devices_by_type(GyroDevice)

if not rc:
    print("ERROR: no RemoteControl on ship"); sys.exit(1)

print(f"  Ship: {ship.name} (ID: {ship.grid_id})")
print(f"  Target: {target_grid.name} (ID: {target_grid.grid_id})")
print(f"  Ship connector: {sc.device_id}")
print(f"  Target connector: {tc.device_id}")
print(f"  Gyros: {len(gyros)}")

# =====================================================================
# PHASE 1: Fly to approach point
# =====================================================================
print("\n" + "=" * 60)
print("PHASE 1: APPROACH POINT")
print("=" * 60)

t_pos = get_pos(tc.telemetry or {})
t_orient = (tc.telemetry or {}).get("orientation", {})
t_fwd = normalize(get_vec3(t_orient.get("forward")) or (0,0,0))

if not t_pos:
    print("ERROR: no target connector position"); sys.exit(1)

target_point = vec_add(t_pos, APPROACH_DIST, t_fwd)

rc_pos = get_pos(rc.telemetry or {})
sc_pos = get_pos(sc.telemetry or {})

if not rc_pos:
    print("ERROR: no ship remote control position")
    sys.exit(1)

if not sc_pos:
    print("ERROR: no ship connector position")
    sys.exit(1)

connector_offset = vec_sub(sc_pos, rc_pos)
ship_target = vec_sub(target_point, connector_offset)

print(f"  Target connector: ({t_pos[0]:.1f}, {t_pos[1]:.1f}, {t_pos[2]:.1f})")
print(f"  Connector approach point ({APPROACH_DIST}m): ({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})")
print(f"  Remote target point: ({ship_target[0]:.1f}, {ship_target[1]:.1f}, {ship_target[2]:.1f})")

if (rc.telemetry or {}).get("autopilotEnabled"):
    rc.disable()
    time.sleep(0.5)
    rc.update()

try:
    rc.handbrake_off()
except Exception:
    pass

rc.thrusters_on()
rc.dampeners_on()
rc.set_mode("oneway")
rc.set_collision_avoidance(False)

time.sleep(0.5)

gps = f"GPS:Approach:{ship_target[0]:.1f}:{ship_target[1]:.1f}:{ship_target[2]:.1f}:"

print("  Flying to approach point...")
rc.goto(gps, speed=10.0, gps_name="Approach")
time.sleep(0.3)
rc.enable()

engaged = False

for attempt in range(5):
    for _ in range(15):
        time.sleep(0.2)
        rc.update()

        if (rc.telemetry or {}).get("autopilotEnabled"):
            engaged = True
            break

    if engaged:
        break

    print(f"  Autopilot did not engage, retry {attempt + 1}/5")
    rc.goto(gps, speed=10.0, gps_name="Approach")
    time.sleep(0.3)
    rc.enable()
    time.sleep(0.5)

if not engaged:
    print("  WARNING: autopilot did not engage, proceeding anyway")

start = time.time()
prev_d = None
stuck_count = 0

while time.time() - start < 120:
    time.sleep(3)

    rc.update()
    sc.update()

    cur_rc = get_pos(rc.telemetry or {})
    cur_sc = get_pos(sc.telemetry or {})

    if not cur_rc or not cur_sc:
        continue

    rc_dist = dist3(cur_rc, ship_target)
    sc_dist = dist3(cur_sc, target_point)
    ap = (rc.telemetry or {}).get("autopilotEnabled", False)

    d = sc_dist

    print(
        f"  [{time.time() - start:.0f}s] "
        f"rc_dist={rc_dist:.1f}m sc_dist={sc_dist:.1f}m autopilot={ap}"
    )

    if sc_dist < 8.0:
        print("  Ship connector reached approach area")
        break

    if not ap and sc_dist < 40.0:
        print("  Autopilot stopped near approach area — continuing")
        break

    if prev_d is not None and abs(prev_d - d) < 0.5:
        stuck_count += 1
    else:
        stuck_count = 0

    prev_d = d

    if stuck_count >= 4 and sc_dist < 50.0:
        print(f"  WARNING: approach stuck at {sc_dist:.1f}m — continuing to connector alignment")
        break

rc.disable()
rc.dampeners_on()
time.sleep(1)

print("  Phase 1 complete.")

# =====================================================================
# PHASE 2: Rotate connector to target
# =====================================================================
print("\n" + "=" * 60)
print("PHASE 2: ROTATE CONNECTOR")
print("=" * 60)

for g in gyros: g.enable()
time.sleep(0.3)

sc_pos = get_pos(sc.telemetry or {})
tc_pos = get_pos(tc.telemetry or {})
if sc_pos and tc_pos:
    axis_dir = normalize(vec_sub(tc_pos, sc_pos))
else:
    print("ERROR: cannot compute axis"); sys.exit(1)

sc_orient = (sc.telemetry or {}).get("orientation", {})
sc_fwd = normalize(get_vec3(sc_orient.get("forward")) or (0,0,0))
init_angle = math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))
print(f"  Initial angle: {math.degrees(init_angle):.1f}°")

if init_angle > ALIGN_TOLERANCE:
    final_angle = correct_orientation(rc, sc, gyros, axis_dir, timeout=30)
    print(f"  Final angle: {math.degrees(final_angle):.1f}°")
else:
    print(f"  Already aligned ({math.degrees(init_angle):.1f}°)")

# Clear overrides but keep gyros enabled
for g in gyros: g.clear_override()
time.sleep(0.3)
print(f"  Phase 2 complete.")

# =====================================================================
# PHASE 3: Direct vector connector-axis approach + auto-lock
# =====================================================================
print("\n" + "=" * 60)
print("PHASE 3: DIRECT VECTOR CONNECTOR APPROACH + LOCK")
print("=" * 60)

thrusters = ship.find_devices_by_type(ThrusterDevice)
if not thrusters:
    print("ERROR: no thrusters on ship for direct Phase 3 control")
    sys.exit(1)

print(f"  Thrusters: {len(thrusters)}")
print("  Updating thruster telemetry...")
thruster_infos = dv_build_thruster_infos(thrusters)
if not thruster_infos:
    print("ERROR: no thruster direction telemetry found")
    print("Need thruster telemetry with thrustDirection or orientation.forward")
    sys.exit(1)

try:
    sc.set_state(enabled=True)
except Exception:
    pass

try:
    rc.disable()
except Exception:
    pass
rc.set_collision_avoidance(False)
rc.thrusters_on()
rc.dampeners_on()

step = 0
stuck_count = 0
prev_dist = float('inf')
previous_angle_deg = None
backoff_count = 0
connected = False
aborted = False

while True:
    step += 1

    refresh_devices(rc, sc, tc, delay=0.1)

    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})
    if not sc_pos or not tc_pos:
        time.sleep(1)
        continue

    axis_vec = vec_sub(tc_pos, sc_pos)
    axis_dist = math.sqrt(axis_vec[0]**2 + axis_vec[1]**2 + axis_vec[2]**2)
    axis_dir = normalize(axis_vec)

    # Check connector lock
    if try_connect(sc, "", axis_dist):
        connected = True
        break

    # Sub-phase
    if axis_dist > 20:
        step_size, speed, timeout, max_thrust = PHASE3_STEP_FAST, PHASE3_SPEED_FAST, 40, DIRECT_MAX_THRUST_FAST
        phase = "FAST"
    elif axis_dist > 5:
        step_size, speed, timeout, max_thrust = PHASE3_STEP_SLOW, PHASE3_SPEED_SLOW, 30, DIRECT_MAX_THRUST_SLOW
        phase = "SLOW"
    else:
        step_size, speed, timeout, max_thrust = PHASE3_STEP_CREEP, PHASE3_SPEED_CREEP, 22, DIRECT_MAX_THRUST_CREEP
        phase = "CREEP"

    angle_err = get_connector_angle(sc, axis_dir)
    angle_deg = math.degrees(angle_err)
    print(f"\n  [Step {step}] DIRECT {phase} | dist={axis_dist:.2f}m angle={angle_deg:.1f}°")

    need_backoff, backoff_reason = should_backoff(axis_dist, angle_deg, previous_angle_deg)
    if need_backoff:
        backoff_count += 1
        print(f"  SAFETY: {backoff_reason}")

        if backoff_count > SAFE_MAX_BACKOFFS:
            print(f"  SAFETY: too many backoffs ({SAFE_MAX_BACKOFFS}), aborting docking")
            aborted = True
            break

        dv_direct_backoff(rc, sc, tc, gyros, thrusters, thruster_infos, distance=SAFE_BACKOFF_DISTANCE)
        stuck_count = 0
        prev_dist = float('inf')
        previous_angle_deg = None
        continue

    # Stuck detection
    if abs(axis_dist - prev_dist) < 0.25:
        stuck_count += 1
    else:
        stuck_count = 0
    prev_dist = axis_dist

    if stuck_count >= 5:
        print("  STUCK — trying connect() + slightly larger direct push")
        if try_connect(sc, "  ", axis_dist):
            connected = True
            break
        step_size = max(1.5, min(4.0, axis_dist - DOCK_DISTANCE + 0.5))
        max_thrust = max(max_thrust, DIRECT_MAX_THRUST_SLOW)
        stuck_count = 0
        stuck_mode = True
    else:
        stuck_mode = False

    # Correct orientation first using the known working gyro method.
    # Direct movement then holds this exact body angle during translation.
    if angle_err > ALIGN_TOLERANCE:
        print(f"  Correcting connector angle before direct move: {angle_deg:.1f}°")
        final_angle = correct_orientation(rc, sc, gyros, axis_dir, timeout=5)
        for g in gyros:
            g.clear_override()
        time.sleep(0.3)
        refresh_devices(rc, sc, tc, delay=0.1)

        final_angle_deg = math.degrees(final_angle)
        need_backoff, backoff_reason = should_backoff(axis_dist, final_angle_deg, previous_angle_deg)
        if need_backoff:
            backoff_count += 1
            print(f"  SAFETY after correction: {backoff_reason}")

            if backoff_count > SAFE_MAX_BACKOFFS:
                print(f"  SAFETY: too many backoffs ({SAFE_MAX_BACKOFFS}), aborting docking")
                aborted = True
                break

            dv_direct_backoff(rc, sc, tc, gyros, thrusters, thruster_infos, distance=SAFE_BACKOFF_DISTANCE)
            stuck_count = 0
            prev_dist = float('inf')
            previous_angle_deg = None
            continue

    # Move. Near the connector, never make a large push.
    if stuck_mode:
        move_dist = step_size
    else:
        move_dist = min(step_size, max(0, axis_dist - DOCK_DISTANCE + 0.5))

    if axis_dist <= SAFE_NEAR_DISTANCE:
        move_dist = min(move_dist, PHASE3_STEP_CREEP)
        speed = min(speed, PHASE3_SPEED_CREEP)
        max_thrust = min(max_thrust, DIRECT_MAX_THRUST_CREEP)

    if move_dist < 0.1:
        if try_connect(sc, "  ", axis_dist):
            connected = True
            break
        move_dist = 0.4
        speed = min(speed, PHASE3_SPEED_CREEP)
        max_thrust = min(max_thrust, DIRECT_MAX_THRUST_CREEP)

    reached, connected_in_move = dv_direct_move_connector_offset(
        rc=rc,
        sc=sc,
        tc=tc,
        gyros=gyros,
        thrusters=thrusters,
        thruster_infos=thruster_infos,
        axis_dir=axis_dir,
        move_dist=move_dist,
        speed=speed,
        max_thrust_pct=max_thrust,
        timeout=timeout,
        label=f"D{step}",
    )

    if connected_in_move or check_connector(sc)[0]:
        print("  >> CONNECTED DURING DIRECT APPROACH!")
        connected = True
        break

    if not reached:
        print("  DIRECT move timed out or did not settle; continuing cautiously")

    previous_angle_deg = angle_deg
    time.sleep(0.3)

# =====================================================================
# FINAL
# =====================================================================
print("\n" + "=" * 60)
print("FINAL")
print("=" * 60)

dv_finish_direct_controls(rc, gyros, thrusters, dampeners=True)
time.sleep(0.5)
refresh_devices(rc, sc, tc, delay=0.1)

sc_pos = get_pos(sc.telemetry or {})
tc_pos = get_pos(tc.telemetry or {})
is_conn, status, other_id = check_connector(sc)

if sc_pos and tc_pos:
    print(f"  Connector distance: {dist3(sc_pos, tc_pos):.2f}m")
print(f"  Connected: {is_conn}")
print(f"  Status: {status}")
print(f"  Other connector: {other_id}")

if is_conn:
    print("\n✅ DOCKING COMPLETE")
elif aborted:
    print("\n❌ DOCKING ABORTED BY SAFETY GUARD")
else:
    print("\n❌ DOCKING INCOMPLETE")

print("[DONE]")
