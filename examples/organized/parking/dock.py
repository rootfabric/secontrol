#!/usr/bin/env python3
"""
=== DOCKING: Full automated docking sequence ===

One script to dock a ship to a target grid's connector:
  Phase 1: Fly to approach point
  Phase 2: Rotate ship connector to target connector docking axis
  Phase 3: Stable connector-axis approach with lateral line-up and auto-lock

Usage:
  python dock.py [ship_id] [target_id] [approach_distance]

Examples:
  python dock.py 104571351454649539 84360909276756422
  python dock.py skynet-baza2 skynet-farpost0 80
"""
import sys
import os
import time
import math

# --- Load .env (handles \r\n) ---
env_path = "/workspace/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

sys.path.insert(0, "/workspace/src")

from secontrol.common import prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.gyro_device import GyroDevice


SHIP = sys.argv[1] if len(sys.argv) > 1 else "104571351454649539"
TARGET = sys.argv[2] if len(sys.argv) > 2 else "84360909276756422"
APPROACH_DIST = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0

# =====================================================================
# Settings
# =====================================================================

GYRO_GAIN = 0.3
MAX_RATE = 0.3

ALIGN_TOLERANCE = 0.1
FINAL_ALIGN_TOLERANCE = 0.045

DOCK_DISTANCE = 3.0

# Space Engineers connector telemetry usually gives the block/connector center,
# not the exact magnetic contact plane. For a large-grid connector the two
# centers are normally still a few meters apart when the ports are close enough.
# Do not try to drive both connector centers to the same point.
CONNECT_ATTEMPT_DISTANCE = 3.2
CONNECTOR_CENTER_LOCK_DISTANCE = 2.55
CONNECTOR_HARD_CONTACT_DISTANCE = 2.85

PHASE3_STEP_FAST = 12.0
PHASE3_STEP_SLOW = 3.0
PHASE3_STEP_NEAR = 2.0
PHASE3_STEP_CREEP = 0.75
PHASE3_STEP_FINAL = 0.25

PHASE3_SPEED_FAST = 2.5
PHASE3_SPEED_SLOW = 0.8
PHASE3_SPEED_NEAR = 0.55
PHASE3_SPEED_CREEP = 0.3
PHASE3_SPEED_FINAL = 0.18

NEAR_CREEP_DISTANCE = 6.0
FINAL_CREEP_DISTANCE = 3.5
# From this distance we stop using small GPS hops and start a continuous
# contact push through the target connector. SE autopilot has a large internal
# arrival radius, so commands smaller than ~1m are often ignored at 7-8m.
FINAL_PUSH_START_DISTANCE = 20.0
FINAL_PUSH_START_MARGIN = 3.0
FINAL_PUSH_TARGET_OVERSHOOT = 30.0
FINAL_PUSH_SPEED = 0.65
FINAL_PUSH_TIMEOUT = 90.0
FINAL_PUSH_PRINT_INTERVAL = 1.0
FINAL_PUSH_NO_PROGRESS_TICKS = 12
# The final push is allowed to start with a wider lateral corridor while far away.
# Close to the connector the corridor becomes stricter. This prevents the script
# from stopping 20m away just because lateral error is about 1m.
FINAL_PUSH_LATERAL_TOLERANCE_FAR = 1.40
FINAL_PUSH_LATERAL_TOLERANCE_NEAR = 0.65
FINAL_PUSH_LINEUP_STOP_RADIUS = 0.30
MAX_PHASE3_STEPS = 120

SAFE_NEAR_DISTANCE = 12.0
SAFE_ANGLE_JUMP_DEG = 20.0
SAFE_PANIC_ANGLE_DEG = 85.0
SAFE_BACKOFF_DISTANCE = 10.0
SAFE_BACKOFF_SPEED = 1.0
SAFE_BACKOFF_TIMEOUT = 25.0
SAFE_MAX_BACKOFFS = 5

APPROACH_RC_REACHED_DIST = 2.0
APPROACH_CONNECTOR_ACCEPT_DIST = 16.0

FINAL_LINEUP_DISTANCE = 14.0
FINAL_LATERAL_TOLERANCE_FAR = 1.4
FINAL_LATERAL_TOLERANCE_NEAR = 0.60
FINAL_MOVE_STOP_RADIUS = 0.45
FINAL_MIN_AXIAL_BEFORE_ABORT = -0.25


# =====================================================================
# Vector utilities
# =====================================================================

def dist3(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def vec_len(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def normalize(v):
    l = vec_len(v)
    return (v[0] / l, v[1] / l, v[2] / l) if l > 1e-10 else (0.0, 0.0, 0.0)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_add(a, s, v):
    return (a[0] + s * v[0], a[1] + s * v[1], a[2] + s * v[2])


def vec_neg(v):
    return (-v[0], -v[1], -v[2])


def get_vec3(data):
    if not data:
        return None
    return (
        float(data.get("x", 0.0)),
        float(data.get("y", 0.0)),
        float(data.get("z", 0.0)),
    )


def get_pos(telemetry):
    d = telemetry.get("pos") or telemetry.get("position")
    if not d:
        return None
    return (float(d["x"]), float(d["y"]), float(d["z"]))


# =====================================================================
# Telemetry helpers
# =====================================================================

def refresh_devices(*devices, delay=0.1):
    for device in devices:
        try:
            device.update()
        except Exception:
            pass

    if delay > 0:
        time.sleep(delay)


def get_body_frame(rc):
    orient = (rc.telemetry or {}).get("orientation", {})
    fwd = normalize(get_vec3(orient.get("forward")) or (0.0, 0.0, 0.0))
    up = normalize(get_vec3(orient.get("up")) or (0.0, 0.0, 0.0))
    right = normalize(cross(up, fwd))
    return fwd, up, right


def get_connector_forward(sc):
    sc_orient = (sc.telemetry or {}).get("orientation", {})
    return normalize(get_vec3(sc_orient.get("forward")) or (0.0, 0.0, 0.0))


def get_connector_angle(sc, axis_dir):
    sc_fwd = get_connector_forward(sc)
    return math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))


def check_connector(connector):
    t = connector.telemetry or {}
    return (
        bool(t.get("connectorIsConnected", False)),
        str(t.get("connectorStatus", "")),
        t.get("otherConnectorId"),
    )


def try_connect(sc, label="", axis_dist=None):
    """
    Try to lock connector.

    Important:
    Physical contact is NOT treated as successful docking.
    Docking is successful only when connectorIsConnected becomes True.
    """
    is_conn, status, _ = check_connector(sc)
    if is_conn:
        return True

    if status == "Connectable":
        if axis_dist is None:
            print(f"  {label}Connector sees target — sending connect()...")
        else:
            print(f"  {label}Connector sees target at {axis_dist:.2f}m — sending connect()...")

        sc.connect()

        for _ in range(10):
            time.sleep(0.4)
            try:
                sc.update()
            except Exception:
                pass

            is_conn, status, _ = check_connector(sc)
            if is_conn:
                print(f"  {label}>> LOCKED!")
                return True

        print(f"  {label}Not locked yet, status={status}")

    return False


# =====================================================================
# Docking geometry
# =====================================================================

def get_target_docking_axis(tc, sc_pos=None, tc_pos=None):
    """
    Return stable docking movement axis.

    axis_dir means direction in which the ship connector must move
    to approach the target connector.

    Normally this is opposite to target connector forward.
    The dynamic connector-to-connector direction is used only to fix
    accidental inversion.
    """
    orient = (tc.telemetry or {}).get("orientation", {})
    target_fwd = normalize(get_vec3(orient.get("forward")) or (0.0, 0.0, 0.0))

    if target_fwd == (0.0, 0.0, 0.0):
        if sc_pos and tc_pos:
            return normalize(vec_sub(tc_pos, sc_pos))
        return (0.0, 0.0, 0.0)

    axis_dir = vec_neg(target_fwd)

    if sc_pos and tc_pos:
        dynamic_axis = normalize(vec_sub(tc_pos, sc_pos))
        if dynamic_axis != (0.0, 0.0, 0.0) and dot(axis_dir, dynamic_axis) < -0.2:
            axis_dir = vec_neg(axis_dir)

    return normalize(axis_dir)


def compute_docking_geometry(sc_pos, tc_pos, axis_dir):
    """
    Decompose connector error into:
      signed_axial_dist — distance along docking axis;
      lateral_error     — side offset from docking line;
      lateral_vec       — vector from ideal line point to current ship connector;
      line_sc_pos       — ideal connector position on docking line with same axial distance.
    """
    to_target = vec_sub(tc_pos, sc_pos)
    signed_axial_dist = dot(to_target, axis_dir)
    line_sc_pos = vec_add(tc_pos, -signed_axial_dist, axis_dir)
    lateral_vec = vec_sub(sc_pos, line_sc_pos)
    lateral_error = vec_len(lateral_vec)
    return signed_axial_dist, lateral_error, lateral_vec, line_sc_pos


def compute_ship_target_for_connector_position(rc, sc, connector_target_pos):
    rc_pos = get_pos(rc.telemetry or {})
    sc_pos = get_pos(sc.telemetry or {})

    if not rc_pos or not sc_pos:
        return None

    connector_offset = vec_sub(sc_pos, rc_pos)
    return vec_sub(connector_target_pos, connector_offset)


def compute_ship_target(rc, sc, axis_dir, move_dist):
    rc_pos = get_pos(rc.telemetry or {})
    sc_pos = get_pos(sc.telemetry or {})

    if not rc_pos or not sc_pos:
        return None

    connector_offset = vec_sub(sc_pos, rc_pos)
    connector_target_pos = vec_add(sc_pos, move_dist, axis_dir)
    return vec_sub(connector_target_pos, connector_offset)


# =====================================================================
# Gyro orientation correction
# =====================================================================

def correct_orientation(rc, sc, gyros, axis_dir, timeout=8, tolerance=ALIGN_TOLERANCE):
    """
    Rotate ship so ship connector forward aligns with stable docking axis.
    """
    start = time.time()

    while time.time() - start < timeout:
        time.sleep(0.25)
        refresh_devices(rc, sc, delay=0)

        sc_fwd = get_connector_forward(sc)
        angle_err = math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))

        if angle_err < tolerance:
            for g in gyros:
                g.clear_override()
            return angle_err

        ship_fwd, ship_up, ship_right = get_body_frame(rc)

        conn_pitch = math.atan2(dot(sc_fwd, ship_up), dot(sc_fwd, ship_fwd))
        des_pitch = math.atan2(dot(axis_dir, ship_up), dot(axis_dir, ship_fwd))
        pitch_err = (des_pitch - conn_pitch + math.pi) % (2 * math.pi) - math.pi

        conn_yaw = math.atan2(dot(sc_fwd, ship_right), dot(sc_fwd, ship_fwd))
        des_yaw = math.atan2(dot(axis_dir, ship_right), dot(axis_dir, ship_fwd))
        yaw_err = (des_yaw - conn_yaw + math.pi) % (2 * math.pi) - math.pi

        rate = min(MAX_RATE, angle_err * GYRO_GAIN)
        pitch_cmd = max(-rate, min(rate, -pitch_err * GYRO_GAIN))
        yaw_cmd = max(-rate, min(rate, -yaw_err * GYRO_GAIN))

        for g in gyros:
            g.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

    for g in gyros:
        g.clear_override()

    refresh_devices(rc, sc, delay=0)
    sc_fwd = get_connector_forward(sc)
    return math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))


# =====================================================================
# Movement helpers
# =====================================================================

def stop_ship(rc, gyros=None, settle=0.4):
    try:
        rc.disable()
    except Exception:
        pass

    try:
        rc.dampeners_on()
    except Exception:
        pass

    if gyros:
        for g in gyros:
            try:
                g.clear_override()
            except Exception:
                pass

    time.sleep(settle)


def fly_connector_to_position(rc, sc, connector_target_pos, speed, gps_name, timeout, stop_radius=FINAL_MOVE_STOP_RADIUS):
    """
    Move ship so the ship connector reaches connector_target_pos.
    This monitors connector position, not only RC position.
    """
    ship_target = compute_ship_target_for_connector_position(rc, sc, connector_target_pos)
    if not ship_target:
        return False

    gps = (
        f"GPS:{gps_name}:"
        f"{ship_target[0]:.2f}:"
        f"{ship_target[1]:.2f}:"
        f"{ship_target[2]:.2f}:"
    )

    rc.goto(gps, speed=speed, gps_name=gps_name)
    time.sleep(0.2)
    rc.enable()

    start = time.time()

    while time.time() - start < timeout:
        time.sleep(0.35)
        refresh_devices(rc, sc, delay=0)

        cur_sc = get_pos(sc.telemetry or {})
        if cur_sc:
            connector_dist = dist3(cur_sc, connector_target_pos)
            autopilot_enabled = bool((rc.telemetry or {}).get("autopilotEnabled", False))

            if connector_dist < stop_radius:
                return True

            if not autopilot_enabled and connector_dist < max(1.5, stop_radius * 3.0):
                return True

    return False


def fly_connector_offset(rc, sc, axis_dir, move_dist, speed, gps_name, timeout):
    sc_pos = get_pos(sc.telemetry or {})
    if not sc_pos:
        return False

    connector_target_pos = vec_add(sc_pos, move_dist, axis_dir)
    return fly_connector_to_position(
        rc=rc,
        sc=sc,
        connector_target_pos=connector_target_pos,
        speed=speed,
        gps_name=gps_name,
        timeout=timeout,
        stop_radius=0.7,
    )


def final_push_to_connector(rc, sc, tc, axis_dir, gyros):
    """
    Final docking movement.

    RC autopilot often ignores very small GPS shifts near the connector because
    its internal arrival radius is larger than our final correction. To avoid
    this, we give RC a target behind the target connector, but stop ourselves
    using connector telemetry and connector status.
    """
    refresh_devices(rc, sc, tc, delay=0.1)

    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})

    if not sc_pos or not tc_pos:
        return False

    signed_axial, lateral_error, _, _ = compute_docking_geometry(sc_pos, tc_pos, axis_dir)
    angle_deg = math.degrees(get_connector_angle(sc, axis_dir))

    allowed_lateral = (
        FINAL_PUSH_LATERAL_TOLERANCE_NEAR
        if signed_axial <= SAFE_NEAR_DISTANCE
        else FINAL_PUSH_LATERAL_TOLERANCE_FAR
    )

    if lateral_error > allowed_lateral:
        print(
            f"  FINAL PUSH: lateral error is too high: "
            f"{lateral_error:.2f}m > {allowed_lateral:.2f}m"
        )
        return False

    if angle_deg > math.degrees(FINAL_ALIGN_TOLERANCE) * 2.0:
        print(f"  FINAL PUSH: angle is too high: {angle_deg:.1f}°")
        return False

    # Target is intentionally beyond the target connector. We do not wait for
    # this GPS point to be reached. We stop when connector geometry/status says so.
    connector_target = vec_add(tc_pos, FINAL_PUSH_TARGET_OVERSHOOT, axis_dir)
    ship_target = compute_ship_target_for_connector_position(rc, sc, connector_target)

    if not ship_target:
        return False

    gps = (
        f"GPS:FinalPush:"
        f"{ship_target[0]:.2f}:"
        f"{ship_target[1]:.2f}:"
        f"{ship_target[2]:.2f}:"
    )

    print(
        f"  FINAL PUSH: axial={signed_axial:.2f}m, "
        f"target center distance={CONNECTOR_CENTER_LOCK_DISTANCE:.2f}m, "
        f"gps overshoot={FINAL_PUSH_TARGET_OVERSHOOT:.1f}m"
    )

    rc.goto(gps, speed=FINAL_PUSH_SPEED, gps_name="FinalPush")
    time.sleep(0.2)
    rc.enable()

    start = time.time()
    last_print = 0.0
    last_axial = signed_axial
    no_progress_ticks = 0
    push_retry_count = 0

    while time.time() - start < FINAL_PUSH_TIMEOUT:
        time.sleep(0.25)
        refresh_devices(rc, sc, tc, delay=0)

        is_conn, status, _ = check_connector(sc)
        if is_conn:
            print("  FINAL PUSH: >> LOCKED!")
            return True

        cur_sc = get_pos(sc.telemetry or {})
        cur_tc = get_pos(tc.telemetry or {})

        if not cur_sc or not cur_tc:
            continue

        cur_axial, cur_lateral, _, _ = compute_docking_geometry(cur_sc, cur_tc, axis_dir)
        cur_angle = math.degrees(get_connector_angle(sc, axis_dir))
        ap = bool((rc.telemetry or {}).get("autopilotEnabled", False))

        # RC sometimes disables autopilot if it thinks the path target is reached or blocked.
        # During final push we intentionally keep the target far beyond the connector,
        # so a disabled autopilot before lock is treated as a command failure and re-enabled.
        if not ap and cur_axial > CONNECTOR_HARD_CONTACT_DISTANCE:
            if push_retry_count < 5:
                push_retry_count += 1
                extra_overshoot = FINAL_PUSH_TARGET_OVERSHOOT + push_retry_count * 10.0
                retry_speed = min(1.0, FINAL_PUSH_SPEED + push_retry_count * 0.08)
                connector_target = vec_add(cur_tc, extra_overshoot, axis_dir)
                ship_target = compute_ship_target_for_connector_position(rc, sc, connector_target)

                if ship_target:
                    gps = (
                        f"GPS:FinalPushResume{push_retry_count}:"
                        f"{ship_target[0]:.2f}:"
                        f"{ship_target[1]:.2f}:"
                        f"{ship_target[2]:.2f}:"
                    )
                    print(
                        f"  FINAL PUSH: autopilot disabled at {cur_axial:.2f}m — "
                        f"reissuing target, overshoot={extra_overshoot:.1f}m, "
                        f"speed={retry_speed:.2f}m/s"
                    )
                    rc.goto(gps, speed=retry_speed, gps_name=f"FinalPushResume{push_retry_count}")
                    time.sleep(0.2)
                    rc.enable()
                    no_progress_ticks = 0

        now = time.time()
        if now - last_print >= FINAL_PUSH_PRINT_INTERVAL:
            print(
                f"  FINAL PUSH: axial={cur_axial:.2f}m "
                f"lateral={cur_lateral:.2f}m angle={cur_angle:.1f}° "
                f"status={status} autopilot={ap}"
            )
            last_print = now

        if status == "Connectable":
            print("  FINAL PUSH: connector is connectable — sending connect()...")
            sc.connect()
            for _ in range(12):
                time.sleep(0.25)
                refresh_devices(sc, delay=0)
                if check_connector(sc)[0]:
                    print("  FINAL PUSH: >> LOCKED!")
                    return True

        allowed_lateral_now = (
            FINAL_PUSH_LATERAL_TOLERANCE_NEAR
            if cur_axial <= SAFE_NEAR_DISTANCE
            else FINAL_PUSH_LATERAL_TOLERANCE_FAR
        )

        if cur_lateral > allowed_lateral_now * 2.0:
            print(
                f"  FINAL PUSH: lateral error grew to {cur_lateral:.2f}m "
                f"> {allowed_lateral_now * 2.0:.2f}m, stopping"
            )
            break

        if cur_angle > SAFE_PANIC_ANGLE_DEG:
            print(f"  FINAL PUSH: angle grew to {cur_angle:.1f}°, stopping")
            break

        # Connector center distance reached the expected magnetic zone.
        # Keep pushing gently unless it locks or we clearly hit hard contact.
        if cur_axial <= CONNECTOR_CENTER_LOCK_DISTANCE:
            print(
                f"  FINAL PUSH: reached connector magnetic zone "
                f"axial={cur_axial:.2f}m — trying connect()"
            )
            sc.connect()
            for _ in range(8):
                time.sleep(0.25)
                refresh_devices(sc, delay=0)
                if check_connector(sc)[0]:
                    print("  FINAL PUSH: >> LOCKED!")
                    return True

        if cur_axial <= -0.15:
            print(
                f"  FINAL PUSH: connector passed target plane "
                f"axial={cur_axial:.2f}m — stopping to avoid overshoot"
            )
            sc.connect()
            for _ in range(8):
                time.sleep(0.25)
                refresh_devices(sc, delay=0)
                if check_connector(sc)[0]:
                    print("  FINAL PUSH: >> LOCKED!")
                    return True
            break

        if abs(last_axial - cur_axial) < 0.03:
            no_progress_ticks += 1
        else:
            no_progress_ticks = 0

        last_axial = cur_axial

        if no_progress_ticks >= FINAL_PUSH_NO_PROGRESS_TICKS:
            if cur_axial <= CONNECTOR_HARD_CONTACT_DISTANCE:
                print(
                    f"  FINAL PUSH: hard contact/no progress at "
                    f"axial={cur_axial:.2f}m — trying final connect()"
                )
                sc.connect()
                for _ in range(12):
                    time.sleep(0.25)
                    refresh_devices(sc, delay=0)
                    if check_connector(sc)[0]:
                        print("  FINAL PUSH: >> LOCKED!")
                        return True
                break

            if push_retry_count < 3:
                push_retry_count += 1
                extra_overshoot = FINAL_PUSH_TARGET_OVERSHOOT + push_retry_count * 8.0
                retry_speed = min(0.85, FINAL_PUSH_SPEED + push_retry_count * 0.12)
                connector_target = vec_add(cur_tc, extra_overshoot, axis_dir)
                ship_target = compute_ship_target_for_connector_position(rc, sc, connector_target)

                if ship_target:
                    gps = (
                        f"GPS:FinalPush{push_retry_count}:"
                        f"{ship_target[0]:.2f}:"
                        f"{ship_target[1]:.2f}:"
                        f"{ship_target[2]:.2f}:"
                    )
                    print(
                        f"  FINAL PUSH: no progress at {cur_axial:.2f}m — "
                        f"reissuing farther target, overshoot={extra_overshoot:.1f}m, "
                        f"speed={retry_speed:.2f}m/s"
                    )
                    rc.goto(gps, speed=retry_speed, gps_name=f"FinalPush{push_retry_count}")
                    time.sleep(0.2)
                    rc.enable()
                    no_progress_ticks = 0
                    last_axial = cur_axial
                    continue

            print(
                f"  FINAL PUSH: no axial progress at {cur_axial:.2f}m after retries, "
                "stopping and re-evaluating"
            )
            break

    stop_ship(rc, gyros, settle=0.35)
    return False


def backoff_from_connector(rc, sc, tc, axis_dir, distance=SAFE_BACKOFF_DISTANCE):
    """
    Back away from target connector along stable docking axis.
    """
    print(f"  SAFETY: backing away {distance:.1f}m before retry")

    stop_ship(rc, gyros, settle=0.3)
    refresh_devices(rc, sc, tc, delay=0.1)

    away_dir = vec_neg(axis_dir)

    ok = fly_connector_offset(
        rc=rc,
        sc=sc,
        axis_dir=away_dir,
        move_dist=distance,
        speed=SAFE_BACKOFF_SPEED,
        gps_name="Backoff",
        timeout=SAFE_BACKOFF_TIMEOUT,
    )

    stop_ship(rc, gyros, settle=0.5)
    refresh_devices(rc, sc, tc, delay=0.1)

    if ok:
        print("  SAFETY: backoff complete")
    else:
        print("  SAFETY: backoff command timed out, continuing with caution")

    return ok


def should_backoff(axis_dist, angle_deg, previous_angle_deg):
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
# MAIN
# =====================================================================

print("=" * 60)
print("AUTOMATED DOCKING SEQUENCE")
print("=" * 60)

# --- Load grids ---
print("\n[LOAD] Loading grids...")
target_grid = prepare_grid(TARGET)
time.sleep(2)

ship = prepare_grid(SHIP)
time.sleep(2)

rc = ship.get_first_device(RemoteControlDevice)
sc_list = ship.find_devices_by_type(ConnectorDevice)
tc_list = target_grid.find_devices_by_type(ConnectorDevice)
gyros = ship.find_devices_by_type(GyroDevice)

if not rc:
    print("ERROR: no RemoteControl on ship")
    sys.exit(1)

if not sc_list:
    print("ERROR: no connector on ship")
    sys.exit(1)

if not tc_list:
    print("ERROR: no connector on target grid")
    sys.exit(1)

sc = sc_list[0]
tc = tc_list[0]

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

refresh_devices(rc, sc, tc, delay=0.2)

t_pos = get_pos(tc.telemetry or {})
t_orient = (tc.telemetry or {}).get("orientation", {})
t_fwd = normalize(get_vec3(t_orient.get("forward")) or (0.0, 0.0, 0.0))

if not t_pos:
    print("ERROR: no target connector position")
    sys.exit(1)

if t_fwd == (0.0, 0.0, 0.0):
    print("ERROR: no target connector forward vector")
    sys.exit(1)

stable_axis_dir = vec_neg(t_fwd)
target_point = vec_add(t_pos, -APPROACH_DIST, stable_axis_dir)

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
print(
    f"  Connector approach point ({APPROACH_DIST:.1f}m): "
    f"({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})"
)
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

    refresh_devices(rc, sc, delay=0)

    cur_rc = get_pos(rc.telemetry or {})
    cur_sc = get_pos(sc.telemetry or {})

    if not cur_rc or not cur_sc:
        continue

    rc_dist = dist3(cur_rc, ship_target)
    sc_dist = dist3(cur_sc, target_point)
    ap = bool((rc.telemetry or {}).get("autopilotEnabled", False))

    print(
        f"  [{time.time() - start:.0f}s] "
        f"rc_dist={rc_dist:.1f}m sc_dist={sc_dist:.1f}m autopilot={ap}"
    )

    if sc_dist < 8.0:
        print("  Ship connector reached approach area")
        break

    if not ap:
        if rc_dist < APPROACH_RC_REACHED_DIST and sc_dist < APPROACH_CONNECTOR_ACCEPT_DIST:
            print(
                f"  Remote reached approach target; connector residual {sc_dist:.1f}m "
                "will be handled in Phase 2/3"
            )
            break

        print(f"  Autopilot stopped too early at {sc_dist:.1f}m — retrying approach")
        rc.goto(gps, speed=10.0, gps_name="Approach")
        time.sleep(0.3)
        rc.enable()
        time.sleep(1.0)
        continue

    if prev_d is not None and abs(prev_d - sc_dist) < 0.5:
        stuck_count += 1
    else:
        stuck_count = 0

    prev_d = sc_dist

    if stuck_count >= 4:
        if rc_dist < APPROACH_RC_REACHED_DIST and sc_dist < APPROACH_CONNECTOR_ACCEPT_DIST:
            print(
                f"  Approach stabilized with rc_dist={rc_dist:.1f}m, "
                f"sc_dist={sc_dist:.1f}m — continuing"
            )
            break

        print(f"  WARNING: approach stuck at {sc_dist:.1f}m — retrying approach")
        rc.goto(gps, speed=7.0, gps_name="ApproachRetry")
        time.sleep(0.3)
        rc.enable()
        stuck_count = 0
        time.sleep(1.0)

stop_ship(rc, gyros=None, settle=1.0)
print("  Phase 1 complete.")

# =====================================================================
# PHASE 2: Rotate connector to target
# =====================================================================

print("\n" + "=" * 60)
print("PHASE 2: ROTATE CONNECTOR")
print("=" * 60)

for g in gyros:
    g.enable()

time.sleep(0.3)
refresh_devices(rc, sc, tc, delay=0.2)

sc_pos = get_pos(sc.telemetry or {})
tc_pos = get_pos(tc.telemetry or {})

if not sc_pos or not tc_pos:
    print("ERROR: cannot compute connector positions")
    sys.exit(1)

axis_dir = get_target_docking_axis(tc, sc_pos, tc_pos)
if axis_dir == (0.0, 0.0, 0.0):
    print("ERROR: cannot compute stable docking axis")
    sys.exit(1)

init_angle = get_connector_angle(sc, axis_dir)
print(f"  Initial angle to stable axis: {math.degrees(init_angle):.1f}°")

if init_angle > ALIGN_TOLERANCE:
    final_angle = correct_orientation(
        rc=rc,
        sc=sc,
        gyros=gyros,
        axis_dir=axis_dir,
        timeout=30,
        tolerance=ALIGN_TOLERANCE,
    )
    print(f"  Final angle: {math.degrees(final_angle):.1f}°")
else:
    print(f"  Already aligned ({math.degrees(init_angle):.1f}°)")

for g in gyros:
    g.clear_override()

time.sleep(0.3)
print("  Phase 2 complete.")

# =====================================================================
# PHASE 3: Connector-axis approach + auto-lock
# =====================================================================

print("\n" + "=" * 60)
print("PHASE 3: STABLE CONNECTOR APPROACH + LOCK")
print("=" * 60)

rc.set_mode("oneway")
rc.set_collision_avoidance(False)
rc.dampeners_on()

step = 0
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
        print("  WARNING: missing connector positions")
        time.sleep(1)
        continue

    axis_dir = get_target_docking_axis(tc, sc_pos, tc_pos)

    if axis_dir == (0.0, 0.0, 0.0):
        print("  WARNING: stable docking axis is zero")
        time.sleep(1)
        continue

    signed_axial, lateral_error, lateral_vec, line_sc_pos = compute_docking_geometry(sc_pos, tc_pos, axis_dir)
    raw_dist = dist3(sc_pos, tc_pos)

    if try_connect(sc, "", raw_dist):
        connected = True
        break

    angle_err = get_connector_angle(sc, axis_dir)
    angle_deg = math.degrees(angle_err)

    if step > MAX_PHASE3_STEPS:
        print(f"  SAFETY: too many Phase 3 steps ({MAX_PHASE3_STEPS}), aborting docking")
        aborted = True
        break

    if signed_axial > 20.0:
        phase = "FAST"
        step_size = PHASE3_STEP_FAST
        speed = PHASE3_SPEED_FAST
        timeout = 25
    elif signed_axial > SAFE_NEAR_DISTANCE:
        phase = "SLOW"
        step_size = PHASE3_STEP_SLOW
        speed = PHASE3_SPEED_SLOW
        timeout = 18
    elif signed_axial > NEAR_CREEP_DISTANCE:
        phase = "NEAR"
        step_size = PHASE3_STEP_NEAR
        speed = PHASE3_SPEED_NEAR
        timeout = 16
    elif signed_axial > FINAL_CREEP_DISTANCE:
        phase = "CREEP"
        step_size = PHASE3_STEP_CREEP
        speed = PHASE3_SPEED_CREEP
        timeout = 12
    else:
        phase = "FINAL"
        step_size = PHASE3_STEP_FINAL
        speed = PHASE3_SPEED_FINAL
        timeout = 8

    lateral_limit = (
        FINAL_LATERAL_TOLERANCE_NEAR
        if signed_axial <= SAFE_NEAR_DISTANCE
        else FINAL_LATERAL_TOLERANCE_FAR
    )

    print(
        f"\n  [Step {step}] {phase} | "
        f"raw={raw_dist:.2f}m axial={signed_axial:.2f}m "
        f"lateral={lateral_error:.2f}m angle={angle_deg:.1f}°"
    )

    if signed_axial < FINAL_MIN_AXIAL_BEFORE_ABORT:
        backoff_count += 1
        print(
            f"  SAFETY: connector passed target plane "
            f"(axial={signed_axial:.2f}m), backing out to line"
        )

        if backoff_count > SAFE_MAX_BACKOFFS:
            print(f"  SAFETY: too many backoffs ({SAFE_MAX_BACKOFFS}), aborting docking")
            aborted = True
            break

        connector_target = vec_add(tc_pos, -FINAL_LINEUP_DISTANCE, axis_dir)
        fly_connector_to_position(
            rc=rc,
            sc=sc,
            connector_target_pos=connector_target,
            speed=SAFE_BACKOFF_SPEED,
            gps_name="PlaneBackoff",
            timeout=SAFE_BACKOFF_TIMEOUT,
            stop_radius=0.8,
        )
        stop_ship(rc, gyros, settle=0.6)
        previous_angle_deg = None
        continue

    need_backoff, backoff_reason = should_backoff(
        axis_dist=max(0.0, signed_axial),
        angle_deg=angle_deg,
        previous_angle_deg=previous_angle_deg,
    )

    if need_backoff:
        backoff_count += 1
        print(f"  SAFETY: {backoff_reason}")

        if backoff_count > SAFE_MAX_BACKOFFS:
            print(f"  SAFETY: too many backoffs ({SAFE_MAX_BACKOFFS}), aborting docking")
            aborted = True
            break

        backoff_from_connector(
            rc=rc,
            sc=sc,
            tc=tc,
            axis_dir=axis_dir,
            distance=SAFE_BACKOFF_DISTANCE,
        )
        previous_angle_deg = None
        continue

    if lateral_error > lateral_limit:
        if signed_axial <= SAFE_NEAR_DISTANCE:
            target_axial = FINAL_LINEUP_DISTANCE
            print(
                f"  LINE-UP: lateral error {lateral_error:.2f}m is too high near connector. "
                f"Backing to {target_axial:.1f}m and centering on docking line."
            )
        else:
            target_axial = max(signed_axial, SAFE_NEAR_DISTANCE)
            print(
                f"  LINE-UP: lateral error {lateral_error:.2f}m is too high. "
                f"Moving connector to docking line at axial={target_axial:.1f}m."
            )

        connector_target = vec_add(tc_pos, -target_axial, axis_dir)

        fly_connector_to_position(
            rc=rc,
            sc=sc,
            connector_target_pos=connector_target,
            speed=min(speed, 1.0),
            gps_name=f"Lineup{step}",
            timeout=25,
            stop_radius=0.7,
        )

        stop_ship(rc, gyros, settle=0.5)

        refresh_devices(rc, sc, tc, delay=0.1)
        axis_dir = get_target_docking_axis(tc, get_pos(sc.telemetry or {}), get_pos(tc.telemetry or {}))

        final_angle = correct_orientation(
            rc=rc,
            sc=sc,
            gyros=gyros,
            axis_dir=axis_dir,
            timeout=12,
            tolerance=FINAL_ALIGN_TOLERANCE,
        )

        print(f"  LINE-UP: angle after centering {math.degrees(final_angle):.1f}°")
        previous_angle_deg = None
        continue

    if angle_err > FINAL_ALIGN_TOLERANCE:
        print(f"  Correcting angle: {angle_deg:.1f}°")

        final_angle = correct_orientation(
            rc=rc,
            sc=sc,
            gyros=gyros,
            axis_dir=axis_dir,
            timeout=8,
            tolerance=FINAL_ALIGN_TOLERANCE,
        )

        for g in gyros:
            g.clear_override()

        time.sleep(0.3)
        final_angle_deg = math.degrees(final_angle)
        print(f"  Angle after correction: {final_angle_deg:.1f}°")

        need_backoff, backoff_reason = should_backoff(
            axis_dist=max(0.0, signed_axial),
            angle_deg=final_angle_deg,
            previous_angle_deg=previous_angle_deg,
        )

        if need_backoff:
            backoff_count += 1
            print(f"  SAFETY after correction: {backoff_reason}")

            if backoff_count > SAFE_MAX_BACKOFFS:
                print(f"  SAFETY: too many backoffs ({SAFE_MAX_BACKOFFS}), aborting docking")
                aborted = True
                break

            backoff_from_connector(
                rc=rc,
                sc=sc,
                tc=tc,
                axis_dir=axis_dir,
                distance=SAFE_BACKOFF_DISTANCE,
            )
            previous_angle_deg = None
            continue

    refresh_devices(rc, sc, tc, delay=0.1)

    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})

    if not sc_pos or not tc_pos:
        time.sleep(1)
        continue

    axis_dir = get_target_docking_axis(tc, sc_pos, tc_pos)
    signed_axial, lateral_error, lateral_vec, line_sc_pos = compute_docking_geometry(sc_pos, tc_pos, axis_dir)
    raw_dist = dist3(sc_pos, tc_pos)

    if try_connect(sc, "  ", raw_dist):
        connected = True
        break

    # Important: do not try to approach the final-push boundary with a tiny GPS hop.
    # SE autopilot may consider such a point reached and stop 10-20m away.
    # Enter continuous push early, while RC still has enough distance to accelerate.
    final_push_zone = signed_axial <= FINAL_PUSH_START_DISTANCE
    almost_final_push_zone = (signed_axial - FINAL_PUSH_START_DISTANCE) <= FINAL_PUSH_START_MARGIN

    if final_push_zone or almost_final_push_zone:
        # Critical order fix:
        # Do not just print "FINAL PUSH skipped" and continue forever.
        # Either start the continuous push, or actively center on the docking axis.
        final_push_lateral_limit = (
            FINAL_PUSH_LATERAL_TOLERANCE_NEAR
            if signed_axial <= SAFE_NEAR_DISTANCE
            else FINAL_PUSH_LATERAL_TOLERANCE_FAR
        )

        if lateral_error > final_push_lateral_limit:
            target_axial = max(signed_axial, FINAL_LINEUP_DISTANCE)
            connector_target = vec_add(tc_pos, -target_axial, axis_dir)
            print(
                f"  FINAL PUSH LINE-UP: lateral={lateral_error:.2f}m > "
                f"{final_push_lateral_limit:.2f}m, centering at axial={target_axial:.1f}m"
            )

            fly_connector_to_position(
                rc=rc,
                sc=sc,
                connector_target_pos=connector_target,
                speed=min(max(speed, 0.8), 1.2),
                gps_name=f"FinalLineup{step}",
                timeout=35,
                stop_radius=FINAL_PUSH_LINEUP_STOP_RADIUS,
            )

            stop_ship(rc, gyros, settle=0.5)
            refresh_devices(rc, sc, tc, delay=0.1)

            sc_pos = get_pos(sc.telemetry or {})
            tc_pos = get_pos(tc.telemetry or {})
            if sc_pos and tc_pos:
                axis_dir = get_target_docking_axis(tc, sc_pos, tc_pos)
                final_angle = correct_orientation(
                    rc=rc,
                    sc=sc,
                    gyros=gyros,
                    axis_dir=axis_dir,
                    timeout=10,
                    tolerance=FINAL_ALIGN_TOLERANCE,
                )
                signed_axial2, lateral_error2, _, _ = compute_docking_geometry(sc_pos, tc_pos, axis_dir)
                print(
                    f"  FINAL PUSH LINE-UP: after centering axial={signed_axial2:.2f}m "
                    f"lateral={lateral_error2:.2f}m angle={math.degrees(final_angle):.1f}°"
                )

            previous_angle_deg = None
            continue

        print("  FINAL PUSH: starting continuous contact approach")
        if final_push_to_connector(rc, sc, tc, axis_dir, gyros):
            connected = True
            break

        previous_angle_deg = None
        continue

    remaining_before_final_push = signed_axial - FINAL_PUSH_START_DISTANCE
    move_dist = min(step_size, max(0.0, remaining_before_final_push))

    if signed_axial > NEAR_CREEP_DISTANCE and move_dist < 1.0:
        move_dist = min(1.0, remaining_before_final_push)

    if signed_axial > SAFE_NEAR_DISTANCE and move_dist < 1.5:
        move_dist = min(1.5, remaining_before_final_push)

    if move_dist < 0.05:
        if try_connect(sc, "  ", raw_dist):
            connected = True
            break

        print("  Cannot move safely closer; trying short creep")
        move_dist = 0.12
        speed = PHASE3_SPEED_FINAL
        timeout = 6

    connector_target = vec_add(sc_pos, move_dist, axis_dir)

    print(f"  Moving along stable axis: {move_dist:.2f}m at {speed:.2f}m/s")

    ship_target = compute_ship_target_for_connector_position(rc, sc, connector_target)
    if not ship_target:
        print("  WARNING: cannot compute ship target")
        time.sleep(1)
        continue

    gps = (
        f"GPS:D{step}:"
        f"{ship_target[0]:.2f}:"
        f"{ship_target[1]:.2f}:"
        f"{ship_target[2]:.2f}:"
    )

    rc.goto(gps, speed=speed, gps_name=f"D{step}")
    time.sleep(0.2)
    rc.enable()

    for _ in range(8):
        refresh_devices(rc, sc, delay=0)
        if (rc.telemetry or {}).get("autopilotEnabled"):
            break
        time.sleep(0.15)

    step_start = time.time()
    reached_step = False

    while time.time() - step_start < timeout:
        time.sleep(0.35)
        refresh_devices(rc, sc, tc, delay=0)

        cur_sc = get_pos(sc.telemetry or {})
        cur_tc = get_pos(tc.telemetry or {})

        if cur_sc and cur_tc:
            cur_axis = get_target_docking_axis(tc, cur_sc, cur_tc)
            cur_axial, cur_lateral, _, _ = compute_docking_geometry(cur_sc, cur_tc, cur_axis)
            cur_raw = dist3(cur_sc, cur_tc)
        else:
            cur_axis = axis_dir
            cur_axial = signed_axial
            cur_lateral = lateral_error
            cur_raw = raw_dist

        if try_connect(sc, "  ", cur_raw):
            connected = True
            break

        cur_angle = math.degrees(get_connector_angle(sc, cur_axis))
        cur_to_target = dist3(cur_sc, connector_target) if cur_sc else 999999.0
        ap = bool((rc.telemetry or {}).get("autopilotEnabled", False))

        if cur_axial <= CONNECT_ATTEMPT_DISTANCE:
            if try_connect(sc, "  ", cur_axial):
                connected = True
                break

        if cur_lateral > lateral_limit * 2.2 and cur_axial <= SAFE_NEAR_DISTANCE:
            print(
                f"  SAFETY: lateral error grew during move "
                f"({cur_lateral:.2f}m), stopping"
            )
            break

        if cur_angle > SAFE_PANIC_ANGLE_DEG and cur_axial <= SAFE_NEAR_DISTANCE:
            print(
                f"  SAFETY: angle grew during move "
                f"({cur_angle:.1f}°), stopping"
            )
            break

        if cur_to_target < FINAL_MOVE_STOP_RADIUS:
            reached_step = True
            break

        if move_dist >= 1.5 and not ap and cur_to_target < 1.5:
            reached_step = True
            break

    if connected:
        break

    stop_ship(rc, gyros, settle=0.35)

    refresh_devices(rc, sc, tc, delay=0.1)
    sc_pos_after = get_pos(sc.telemetry or {})
    tc_pos_after = get_pos(tc.telemetry or {})

    if sc_pos_after and tc_pos_after:
        axis_after = get_target_docking_axis(tc, sc_pos_after, tc_pos_after)
        previous_angle_deg = math.degrees(get_connector_angle(sc, axis_after))
    else:
        previous_angle_deg = None

    if not reached_step:
        print("  Step stopped before exact target; re-evaluating geometry")


# =====================================================================
# FINAL
# =====================================================================

print("\n" + "=" * 60)
print("FINAL")
print("=" * 60)

stop_ship(rc, gyros, settle=0.5)
refresh_devices(rc, sc, tc, delay=0.2)

sc_pos = get_pos(sc.telemetry or {})
tc_pos = get_pos(tc.telemetry or {})
is_conn, status, other_id = check_connector(sc)

if sc_pos and tc_pos:
    final_axis = get_target_docking_axis(tc, sc_pos, tc_pos)
    final_axial, final_lateral, _, _ = compute_docking_geometry(sc_pos, tc_pos, final_axis)

    print(f"  Connector raw distance: {dist3(sc_pos, tc_pos):.2f}m")
    print(f"  Connector axial distance: {final_axial:.2f}m")
    print(f"  Connector lateral error: {final_lateral:.2f}m")

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
