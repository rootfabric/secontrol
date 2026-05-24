#!/usr/bin/env python3
"""
=== SMOOTH UNDOCK ===

Отстыковывает корабль и плавно отводит его от базы без автопилотного разворота.

Usage:
  python smooth_undock.py [ship_id_or_name] [base_id_or_name] [distance]

Examples:
  python smooth_undock.py skynet-baza0 skynet-farpost0 50
  python smooth_undock.py 104571351454649539 84360909276756422 100
"""

import math
import os
import sys
import time

ENV_PATH = "C:/secontrol/.env"
SRC_PATH = "C:/secontrol/src"

if os.path.exists(ENV_PATH):
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from secontrol.common import prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.thruster_device import ThrusterDevice
from secontrol.devices.gyro_device import GyroDevice

SHIP = sys.argv[1] if len(sys.argv) > 1 else "104571351454649539"
BASE = sys.argv[2] if len(sys.argv) > 2 else "84360909276756422"
DISTANCE = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0

PUSH_OVERRIDE = 0.10
PULSE_OVERRIDE = 0.06
MAX_PUSH_SECONDS = 90.0
MIN_THRUSTER_DOT = 0.75
RAMP_SECONDS = 3.0
BRAKE_DISTANCE = 12.0
STOP_WAIT_SECONDS = 20.0
DEFAULT_THRUSTER_FORCE_SIGN = -1.0


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def scale(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)


def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_add(a, s, v):
    return (a[0] + s * v[0], a[1] + s * v[1], a[2] + s * v[2])


def normalize(v):
    length = math.sqrt(dot(v, v))
    if length <= 1e-10:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def get_vec3(data):
    if not data:
        return None
    if isinstance(data, dict):
        return (
            float(data.get("x", 0.0)),
            float(data.get("y", 0.0)),
            float(data.get("z", 0.0)),
        )
    if isinstance(data, (list, tuple)) and len(data) == 3:
        return (float(data[0]), float(data[1]), float(data[2]))
    if isinstance(data, str):
        parts = [p.strip() for p in data.replace(";", ",").split(",")]
        if len(parts) == 3:
            return (float(parts[0]), float(parts[1]), float(parts[2]))
    return None


def get_pos(telemetry):
    d = (telemetry or {}).get("pos") or (telemetry or {}).get("position")
    if not d:
        return None
    return (float(d["x"]), float(d["y"]), float(d["z"]))


def get_forward(device):
    telemetry = device.telemetry or {}
    orient = telemetry.get("orientation") or {}
    return normalize(get_vec3(orient.get("forward")) or (0.0, 0.0, 0.0))


def get_speed(rc):
    t = rc.telemetry or {}

    for key in ("speed", "linearSpeed", "velocityLength"):
        if key in t:
            try:
                return abs(float(t[key]))
            except (TypeError, ValueError):
                pass

    for key in ("velocity", "linearVelocity", "linear_velocity"):
        v = get_vec3(t.get(key))
        if v:
            return math.sqrt(dot(v, v))

    return None


def check_connector(connector):
    t = connector.telemetry or {}
    return (
        bool(t.get("connectorIsConnected", False)),
        str(t.get("connectorStatus", "")),
        t.get("otherConnectorId"),
    )


def signed_clearance(ship_connector, base_connector, escape_dir):
    sc_pos = get_pos(ship_connector.telemetry or {})
    tc_pos = get_pos(base_connector.telemetry or {})
    if not sc_pos or not tc_pos:
        return None
    return dot(vec_sub(sc_pos, tc_pos), escape_dir)


def set_thrusters(thrusters, override):
    sent = 0
    for thruster in thrusters:
        try:
            sent += thruster.set_thrust(override=float(override), enabled=True)
        except Exception as e:
            print(f"  WARN: thruster command failed: {thruster.name}: {e}")
    return sent


def clear_thrusters(thrusters):
    for thruster in thrusters:
        try:
            thruster.set_thrust(override=0.0, enabled=True)
        except Exception:
            pass


def choose_ship_connector(ship_grid):
    connectors = ship_grid.find_devices_by_type(ConnectorDevice)
    if not connectors:
        return None

    for c in connectors:
        is_connected, _, _ = check_connector(c)
        if is_connected:
            return c

    return connectors[0]


def choose_base_connector(base_grid, other_connector_id):
    connectors = base_grid.find_devices_by_type(ConnectorDevice)
    if not connectors:
        return None

    if other_connector_id is not None:
        other_text = str(other_connector_id)
        for c in connectors:
            if str(c.device_id) == other_text:
                return c

    return connectors[0]


def select_thrusters(thrusters, escape_dir, force_sign):
    selected = []

    for thruster in thrusters:
        fwd = get_forward(thruster)
        if dot(fwd, fwd) <= 1e-8:
            continue

        push_dir = normalize(scale(fwd, force_sign))
        if dot(push_dir, escape_dir) >= MIN_THRUSTER_DOT:
            selected.append(thruster)

    return selected


def calibrate_thrusters(thrusters, sc, tc, escape_dir):
    forced = os.getenv("SE_THRUSTER_FORCE_SIGN", "").strip().lower()

    if forced in {"1", "+1", "plus"}:
        return select_thrusters(thrusters, escape_dir, 1.0), 1.0

    if forced in {"-1", "minus"}:
        return select_thrusters(thrusters, escape_dir, -1.0), -1.0

    best_selected = []
    best_sign = DEFAULT_THRUSTER_FORCE_SIGN
    best_delta = -999.0

    for sign in (DEFAULT_THRUSTER_FORCE_SIGN, -DEFAULT_THRUSTER_FORCE_SIGN):
        selected = select_thrusters(thrusters, escape_dir, sign)
        if not selected:
            continue

        before = signed_clearance(sc, tc, escape_dir)

        set_thrusters(selected, PULSE_OVERRIDE)
        time.sleep(0.6)
        clear_thrusters(selected)
        time.sleep(0.4)

        after = signed_clearance(sc, tc, escape_dir)
        delta = 0.0 if before is None or after is None else after - before

        print(f"  Calibration sign={sign:+.0f}: thrusters={len(selected)}, delta={delta:.3f}m")

        if delta > best_delta:
            best_delta = delta
            best_selected = selected
            best_sign = sign

        if delta > 0.03:
            return selected, sign

    return best_selected, best_sign


def wait_updates(*devices, seconds=0.5):
    for d in devices:
        try:
            d.update()
        except Exception:
            pass
    time.sleep(seconds)


def main():
    print("=" * 60)
    print("SMOOTH UNDOCK")
    print("=" * 60)

    print("\n[LOAD] Loading grids...")
    ship = prepare_grid(SHIP)
    time.sleep(1.0)

    base = prepare_grid(BASE)
    time.sleep(1.0)

    rc = ship.get_first_device(RemoteControlDevice)
    sc = choose_ship_connector(ship)

    if not rc:
        print("ERROR: no Remote Control on ship")
        return 1

    if not sc:
        print("ERROR: no connector on ship")
        return 1

    is_connected, status, other_id = check_connector(sc)
    tc = choose_base_connector(base, other_id)

    if not tc:
        print("ERROR: no connector on base")
        return 1

    thrusters = ship.find_devices_by_type(ThrusterDevice)
    gyros = ship.find_devices_by_type(GyroDevice)

    print(f"  Ship: {ship.name} ({ship.grid_id})")
    print(f"  Base: {base.name} ({base.grid_id})")
    print(f"  Ship connector: {sc.name or sc.device_id}")
    print(f"  Base connector: {tc.name or tc.device_id}")
    print(f"  Thrusters: {len(thrusters)}")
    print(f"  Gyros: {len(gyros)}")
    print(f"  Connected: {is_connected}, status={status}")

    if not is_connected:
        print("ERROR: ship is not connected")
        return 1

    if not thrusters:
        print("ERROR: no thrusters found; smooth manual departure is impossible")
        return 1

    wait_updates(rc, sc, tc, seconds=0.5)

    tc_pos = get_pos(tc.telemetry or {})
    tc_fwd = get_forward(tc)

    if not tc_pos or dot(tc_fwd, tc_fwd) <= 1e-8:
        print("ERROR: cannot read base connector position/orientation")
        return 1

    escape_dir = tc_fwd
    target_clearance = max(5.0, DISTANCE)
    target_point = vec_add(tc_pos, target_clearance, escape_dir)

    print("\n[PLAN]")
    print(f"  Escape dir: ({escape_dir[0]:.3f}, {escape_dir[1]:.3f}, {escape_dir[2]:.3f})")
    print(f"  Target point: ({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})")
    print(f"  Target clearance: {target_clearance:.1f}m")

    print("\n[INIT] Preparing ship...")
    rc.disable()
    rc.gyro_control_off()
    rc.thrusters_on()
    rc.dampeners_on()

    for g in gyros:
        try:
            g.clear_override()
            g.enable()
        except Exception:
            pass

    clear_thrusters(thrusters)
    time.sleep(0.5)

    print("\n[UNDOCK] Disconnecting connector...")

    try:
        ship.park_off()
    except Exception:
        pass

    sc.disconnect()
    time.sleep(1.0)
    sc.update()
    time.sleep(0.5)

    is_connected, status, _ = check_connector(sc)

    if is_connected or status == "Connected":
        print("  First disconnect failed, retrying...")
        sc.disconnect()
        time.sleep(1.5)
        sc.update()
        is_connected, status, _ = check_connector(sc)

    print(f"  Status after disconnect: {status}")

    if is_connected or status == "Connected":
        print("ERROR: disconnect failed")
        return 1

    print("  Disabling connector magnet...")

    try:
        sc.set_state(enabled=False)
    except Exception:
        pass

    print("\n[THRUSTERS] Selecting departure thrusters...")
    rc.dampeners_off()
    time.sleep(0.3)

    selected, sign = calibrate_thrusters(thrusters, sc, tc, escape_dir)

    if not selected:
        rc.dampeners_on()
        print("ERROR: cannot find thrusters aligned with departure axis")
        print("TIP: check that thruster telemetry has orientation.forward")
        return 1

    names = ", ".join((t.name or str(t.device_id)) for t in selected[:8])
    if len(selected) > 8:
        names += f", ... +{len(selected) - 8}"

    print(f"  Using sign={sign:+.0f}, thrusters={len(selected)}")
    print(f"  Selected: {names}")

    print("\n[PUSH] Smooth manual departure...")

    start = time.time()
    last_print = 0.0

    try:
        while time.time() - start < MAX_PUSH_SECONDS:
            wait_updates(rc, sc, tc, seconds=0.15)

            clearance = signed_clearance(sc, tc, escape_dir)
            if clearance is None:
                continue

            elapsed = time.time() - start
            remaining = target_clearance - clearance

            if remaining <= 0.0:
                print(f"  Clearance reached: {clearance:.1f}m")
                break

            ramp = clamp(elapsed / max(0.1, RAMP_SECONDS), 0.15, 1.0)
            brake = clamp(remaining / max(1.0, BRAKE_DISTANCE), 0.20, 1.0)
            override = PUSH_OVERRIDE * ramp * brake

            set_thrusters(selected, override)

            if elapsed - last_print >= 1.0:
                speed = get_speed(rc)
                speed_text = f", speed={speed:.2f}m/s" if speed is not None else ""
                print(
                    f"  [{elapsed:5.1f}s] "
                    f"clearance={clearance:6.2f}m, "
                    f"remaining={remaining:6.2f}m, "
                    f"override={override:.4f}"
                    f"{speed_text}"
                )
                last_print = elapsed
        else:
            print("  WARN: push timeout reached")

    finally:
        clear_thrusters(thrusters)

    print("\n[STOP] Stopping with dampeners...")
    rc.dampeners_on()

    stop_start = time.time()

    while time.time() - stop_start < STOP_WAIT_SECONDS:
        wait_updates(rc, sc, tc, seconds=0.5)

        speed = get_speed(rc)
        clearance = signed_clearance(sc, tc, escape_dir)

        if speed is not None:
            print(f"  speed={speed:.2f}m/s, clearance={(clearance or 0.0):.1f}m")
            if speed < 0.25:
                break
        else:
            break

    rc.disable()
    rc.dampeners_on()
    clear_thrusters(thrusters)

    final_clearance = signed_clearance(sc, tc, escape_dir)

    print("\n[DONE]")

    if final_clearance is not None:
        print(f"  Final clearance: {final_clearance:.1f}m")

    print("  Autopilot was not used during departure, so ship should not rotate nose-to-target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
