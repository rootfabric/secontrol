#!/usr/bin/env python3
"""
=== SAFE NOSE-THRUSTER UNDOCK ===

Отстыковывает корабль от коннектора и сразу даёт тягу на носовые/отстыковочные
двигатели без автопилота. RC не летит к GPS-точке и не разворачивает корабль.

Usage:
  python smooth_undock_nose_fixed.py [ship_id_or_name] [base_id_or_name] [distance]

Examples:
  python smooth_undock_nose_fixed.py skynet-agent0 skynet-farpost0 50
  python smooth_undock_nose_fixed.py 112837053629091503 80828718952705651 80

Environment overrides:
  SE_UNDOCK_PUSH_OVERRIDE=35       # normal push override percent
  SE_UNDOCK_EMERGENCY_OVERRIDE=70  # if no movement after a few seconds
  SE_UNDOCK_MIN_VECTOR_DOT=0.65    # vector selector threshold
  SE_UNDOCK_FORCE_NOSE=1           # ignore telemetry vectors, use local nose group
  SE_UNDOCK_THRUSTER_IDS=id1,id2   # explicit thruster ids to use
"""

import json
import math
import os
import sys
import time
from typing import Iterable, Optional

ENV_PATHS = (
    "C:/secontrol/.env",
    "/workspace/.env",
    ".env",
)
SRC_PATHS = (
    "C:/secontrol/src",
    "/workspace/src",
)

for env_path in ENV_PATHS:
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

for src_path in SRC_PATHS:
    if os.path.isdir(src_path) and src_path not in sys.path:
        sys.path.insert(0, src_path)

from secontrol.common import prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.thruster_device import ThrusterDevice

SHIP = sys.argv[1] if len(sys.argv) > 1 else "112837053629091503"
BASE = sys.argv[2] if len(sys.argv) > 2 else "80828718952705651"
DISTANCE = float(sys.argv[3]) if len(sys.argv) > 3 else 50.0

PUSH_OVERRIDE = float(os.getenv("SE_UNDOCK_PUSH_OVERRIDE", "35"))
EMERGENCY_OVERRIDE = float(os.getenv("SE_UNDOCK_EMERGENCY_OVERRIDE", "70"))
MAX_PUSH_SECONDS = float(os.getenv("SE_UNDOCK_MAX_PUSH_SECONDS", "45"))
RAMP_SECONDS = float(os.getenv("SE_UNDOCK_RAMP_SECONDS", "2.5"))
BRAKE_DISTANCE = float(os.getenv("SE_UNDOCK_BRAKE_DISTANCE", "15"))
STOP_WAIT_SECONDS = float(os.getenv("SE_UNDOCK_STOP_WAIT_SECONDS", "20"))
MIN_VECTOR_DOT = float(os.getenv("SE_UNDOCK_MIN_VECTOR_DOT", "0.65"))
LOCAL_AXIS_TOLERANCE = float(os.getenv("SE_UNDOCK_LOCAL_AXIS_TOLERANCE", "2.6"))
MIN_CLEARANCE_GAIN = float(os.getenv("SE_UNDOCK_MIN_CLEARANCE_GAIN", "0.5"))
FORCE_NOSE = os.getenv("SE_UNDOCK_FORCE_NOSE", "").strip().lower() in {"1", "true", "yes", "on"}


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def dot(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def length(v) -> float:
    return math.sqrt(dot(v, v))


def normalize(v):
    n = length(v)
    if n <= 1e-10:
        return None
    return (float(v[0]) / n, float(v[1]) / n, float(v[2]) / n)


def vec_sub(a, b):
    return (float(a[0]) - float(b[0]), float(a[1]) - float(b[1]), float(a[2]) - float(b[2]))


def vec_add(a, s, v):
    return (float(a[0]) + s * float(v[0]), float(a[1]) + s * float(v[1]), float(a[2]) + s * float(v[2]))


def get_vec3(value):
    if value is None:
        return None
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
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
        if len(parts) == 3:
            try:
                return (float(parts[0]), float(parts[1]), float(parts[2]))
            except ValueError:
                return None
    return None


def get_pos(telemetry):
    data = (telemetry or {}).get("pos") or (telemetry or {}).get("position")
    if isinstance(data, dict):
        return get_vec3(data)
    if isinstance(data, (list, tuple)):
        return get_vec3(data)
    return None


def safe_name(device) -> str:
    name = getattr(device, "name", None)
    if name:
        return str(name)
    return str(getattr(device, "device_id", "unknown"))


def read_json_from_redis(redis_client, key: str):
    try:
        if hasattr(redis_client, "get_json"):
            return redis_client.get_json(key)
    except Exception:
        pass

    try:
        raw = redis_client.client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, dict):
            return raw
    except Exception:
        return None
    return None


def scan_existing_telemetry(device):
    """Read live telemetry even when BaseDevice.telemetry_key is stale/wrong."""
    redis_client = getattr(device, "redis", None)
    if redis_client is None:
        return None

    grid = getattr(device, "grid", None)
    owner_id = getattr(grid, "owner_id", None)
    grid_id = getattr(device, "grid_id", None) or getattr(grid, "grid_id", None)
    device_id = str(getattr(device, "device_id", ""))

    candidates = []
    telemetry_key = getattr(device, "telemetry_key", None)
    if telemetry_key:
        candidates.append(str(telemetry_key))

    try:
        resolved = device._resolve_existing_telemetry_key()
        if resolved:
            candidates.append(str(resolved))
    except Exception:
        pass

    patterns = []
    if owner_id and grid_id and device_id:
        patterns.append(f"se:{owner_id}:grid:{grid_id}:*:{device_id}:telemetry")
    if owner_id and device_id:
        patterns.append(f"se:{owner_id}:grid:*:*:{device_id}:telemetry")
    if device_id:
        patterns.append(f"*:{device_id}:telemetry")

    try:
        client = getattr(redis_client, "client", None)
        if client is not None:
            for pattern in patterns:
                for key in client.scan_iter(match=pattern, count=200):
                    if isinstance(key, bytes):
                        key = key.decode("utf-8", "replace")
                    candidates.append(str(key))
    except Exception:
        pass

    seen = set()
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        data = read_json_from_redis(redis_client, key)
        if isinstance(data, dict) and data:
            try:
                device.telemetry = data
            except Exception:
                pass
            return data

    return None


def refresh_device(device, wait: float = 0.15):
    try:
        device.update()
    except Exception:
        pass

    if wait > 0:
        time.sleep(wait)

    data = scan_existing_telemetry(device)
    if isinstance(data, dict) and data:
        return data

    try:
        return device.telemetry or {}
    except Exception:
        return {}


def refresh_many(devices: Iterable, wait_after: float = 0.25):
    for device in devices:
        try:
            device.update()
        except Exception:
            pass
    if wait_after > 0:
        time.sleep(wait_after)
    for device in devices:
        scan_existing_telemetry(device)


def check_connector(connector):
    telemetry = refresh_device(connector, wait=0.05)
    return (
        bool(telemetry.get("connectorIsConnected", False)),
        str(telemetry.get("connectorStatus", "")),
        telemetry.get("otherConnectorId"),
    )


def choose_ship_connector(ship_grid):
    connectors = ship_grid.find_devices_by_type(ConnectorDevice)
    if not connectors:
        return None

    for connector in connectors:
        connected, _, _ = check_connector(connector)
        if connected:
            return connector

    return connectors[0]


def choose_base_connector(base_grid, other_connector_id):
    connectors = base_grid.find_devices_by_type(ConnectorDevice)
    if not connectors:
        return None

    if other_connector_id is not None:
        target = str(other_connector_id)
        for connector in connectors:
            if str(connector.device_id) == target:
                return connector

    return connectors[0]


def signed_clearance(ship_connector, base_connector, escape_dir):
    sc_pos = get_pos(refresh_device(ship_connector, wait=0.02))
    tc_pos = get_pos(refresh_device(base_connector, wait=0.02))
    if sc_pos is None or tc_pos is None:
        return None
    return dot(vec_sub(sc_pos, tc_pos), escape_dir)


def get_thruster_direction(thruster):
    telemetry = refresh_device(thruster, wait=0.02)

    direction = normalize(get_vec3(telemetry.get("thrustDirection")) or (0.0, 0.0, 0.0))
    if direction is not None:
        return direction, "thrustDirection"

    orientation = telemetry.get("orientation") or {}
    forward = normalize(get_vec3(orientation.get("forward")) or (0.0, 0.0, 0.0))
    if forward is not None:
        return (-forward[0], -forward[1], -forward[2]), "-orientation.forward"

    return None, "missing"


def get_block_for_device(grid, device):
    try:
        block = grid.get_block(device.device_id)
        if block is not None:
            return block
    except Exception:
        pass

    try:
        return grid.get_block(int(device.device_id))
    except Exception:
        return None


def get_block_local_pos(grid, device):
    block = get_block_for_device(grid, device)
    if block is None:
        return None

    local_pos = getattr(block, "local_position", None)
    if local_pos is not None:
        return tuple(float(v) for v in local_pos)

    extra = getattr(block, "extra", None)
    if isinstance(extra, dict):
        value = extra.get("local_pos") or extra.get("localPos") or extra.get("localPosition")
        return get_vec3(value)

    return None


def explicit_thruster_selection(thrusters):
    text = os.getenv("SE_UNDOCK_THRUSTER_IDS", "").strip()
    if not text:
        return []

    wanted = {part.strip() for part in text.replace(";", ",").split(",") if part.strip()}
    selected = [thruster for thruster in thrusters if str(thruster.device_id) in wanted]
    return selected


def select_thrusters_by_vector(thrusters, escape_dir):
    selected = []
    stats = {"thrustDirection": 0, "-orientation.forward": 0, "missing": 0}
    scored = []

    for thruster in thrusters:
        direction, source = get_thruster_direction(thruster)
        stats[source] = stats.get(source, 0) + 1
        if direction is None:
            continue

        score = dot(direction, escape_dir)
        scored.append((score, source, thruster, direction))
        if score >= MIN_VECTOR_DOT:
            selected.append(thruster)

    scored.sort(key=lambda item: item[0], reverse=True)

    print(
        "  Direction sources: "
        f"thrustDirection={stats.get('thrustDirection', 0)}, "
        f"orientationFallback={stats.get('-orientation.forward', 0)}, "
        f"missing={stats.get('missing', 0)}"
    )

    if scored:
        print("  Top vector candidates:")
        for score, source, thruster, direction in scored[:10]:
            print(
                f"    score={score:+.3f} source={source:>20} "
                f"id={thruster.device_id} name={safe_name(thruster)} "
                f"dir=({direction[0]:+.3f},{direction[1]:+.3f},{direction[2]:+.3f})"
            )

    return selected


def select_nose_thrusters_by_local_grid(ship_grid, thrusters, ship_connector):
    connector_pos = get_block_local_pos(ship_grid, ship_connector)
    if connector_pos is None:
        print("  WARN: cannot read connector local_pos; nose fallback is unavailable")
        return []

    axis = max(range(3), key=lambda i: abs(connector_pos[i]))
    connector_axis_value = connector_pos[axis]
    direction_sign = -1.0 if connector_axis_value < 0 else 1.0

    entries = []
    for thruster in thrusters:
        local_pos = get_block_local_pos(ship_grid, thruster)
        if local_pos is None:
            continue
        entries.append((thruster, local_pos, local_pos[axis]))

    if not entries:
        print("  WARN: no thruster local_pos data found in grid blocks")
        return []

    if direction_sign < 0:
        extreme = min(value for _, _, value in entries)
        selected_entries = [entry for entry in entries if entry[2] <= extreme + LOCAL_AXIS_TOLERANCE]
    else:
        extreme = max(value for _, _, value in entries)
        selected_entries = [entry for entry in entries if entry[2] >= extreme - LOCAL_AXIS_TOLERANCE]

    selected = [entry[0] for entry in selected_entries]

    axis_name = "XYZ"[axis]
    print(
        f"  Nose fallback: connector local={connector_pos}, axis={axis_name}, "
        f"connector_axis={connector_axis_value:.1f}, thruster_extreme={extreme:.1f}, "
        f"selected={len(selected)}"
    )

    for thruster, local_pos, _ in selected_entries[:20]:
        print(f"    nose id={thruster.device_id} name={safe_name(thruster)} local={local_pos}")

    return selected


def clear_thrusters(thrusters):
    for thruster in thrusters:
        try:
            thruster.set_thrust(override=0.0, enabled=True)
        except Exception:
            try:
                thruster.clear_override()
            except Exception:
                pass


def set_thrusters(thrusters, override_pct: float):
    sent = 0
    value = clamp(float(override_pct), 0.0, 100.0)
    for thruster in thrusters:
        try:
            sent += thruster.set_thrust(override=value, enabled=True)
        except Exception as exc:
            print(f"  WARN: failed to set thrust on {safe_name(thruster)}: {exc}")
    return sent


def get_speed(rc):
    telemetry = refresh_device(rc, wait=0.02)
    for key in ("speed", "linearSpeed", "velocityLength"):
        if key in telemetry:
            try:
                return abs(float(telemetry[key]))
            except (TypeError, ValueError):
                pass
    for key in ("velocity", "linearVelocity", "linear_velocity"):
        velocity = get_vec3(telemetry.get(key))
        if velocity is not None:
            return length(velocity)
    return None


def verify_override_applied(thrusters, expected_pct: float):
    if not thrusters:
        return

    sample = thrusters[0]
    telemetry = refresh_device(sample, wait=0.3)
    override_pct = telemetry.get("overridePct")
    current_thrust = telemetry.get("currentThrust")
    max_thrust = telemetry.get("maxThrust")

    print(
        f"  Override check on {safe_name(sample)}: "
        f"overridePct={override_pct}, currentThrust={current_thrust}, maxThrust={max_thrust}"
    )

    try:
        actual = float(override_pct)
        if actual < expected_pct * 0.5:
            print("  WARN: overridePct is much lower than requested; check C# ThrusterDevice override handler")
    except (TypeError, ValueError):
        print("  WARN: cannot read overridePct after command")


def wait_updates(*devices, seconds: float = 0.3):
    for device in devices:
        try:
            device.update()
        except Exception:
            pass
    time.sleep(seconds)
    for device in devices:
        scan_existing_telemetry(device)


def main() -> int:
    print("=" * 60)
    print("SAFE NOSE-THRUSTER UNDOCK")
    print("=" * 60)

    print("\n[LOAD] Loading grids...")
    ship = prepare_grid(SHIP)
    time.sleep(1.0)
    base = prepare_grid(BASE)
    time.sleep(1.0)

    rc = ship.get_first_device(RemoteControlDevice)
    sc = choose_ship_connector(ship)

    if rc is None:
        print("ERROR: no Remote Control on ship")
        return 1
    if sc is None:
        print("ERROR: no ship connector")
        return 1

    is_connected, status, other_id = check_connector(sc)
    tc = choose_base_connector(base, other_id)

    if tc is None:
        print("ERROR: no base connector")
        return 1

    thrusters = ship.find_devices_by_type(ThrusterDevice)
    gyros = ship.find_devices_by_type(GyroDevice)

    print(f"  Ship: {ship.name} ({ship.grid_id})")
    print(f"  Base: {base.name} ({base.grid_id})")
    print(f"  Ship connector: {safe_name(sc)} ({sc.device_id})")
    print(f"  Base connector: {safe_name(tc)} ({tc.device_id})")
    print(f"  Thrusters: {len(thrusters)}")
    print(f"  Gyros: {len(gyros)}")
    print(f"  Connected: {is_connected}, status={status}, other={other_id}")

    if not is_connected:
        print("ERROR: ship is not connected")
        return 1
    if not thrusters:
        print("ERROR: no thrusters found")
        return 1

    print("\n[INIT] Updating connector and thruster telemetry...")
    refresh_many([rc, sc, tc], wait_after=0.4)
    refresh_many(thrusters, wait_after=0.8)

    sc_pos = get_pos(refresh_device(sc, wait=0.05))
    tc_pos = get_pos(refresh_device(tc, wait=0.05))

    if sc_pos is None or tc_pos is None:
        print("ERROR: cannot read connector world positions")
        return 1

    escape_dir = normalize(vec_sub(sc_pos, tc_pos))
    if escape_dir is None:
        print("ERROR: cannot compute escape direction")
        return 1

    start_clearance = signed_clearance(sc, tc, escape_dir)
    if start_clearance is None:
        print("ERROR: cannot compute start clearance")
        return 1

    target_clearance = start_clearance + max(5.0, DISTANCE)
    target_point = vec_add(tc_pos, target_clearance, escape_dir)

    print("\n[PLAN]")
    print(f"  Escape dir: ({escape_dir[0]:+.3f}, {escape_dir[1]:+.3f}, {escape_dir[2]:+.3f})")
    print(f"  Start clearance: {start_clearance:.2f}m")
    print(f"  Target clearance: {target_clearance:.2f}m")
    print(f"  Target point: ({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})")
    print(f"  Push override: {PUSH_OVERRIDE:.1f}%")
    print(f"  Emergency override: {EMERGENCY_OVERRIDE:.1f}%")

    print("\n[THRUSTERS] Selecting departure thrusters...")
    selected = explicit_thruster_selection(thrusters)
    if selected:
        print(f"  Explicit selection from SE_UNDOCK_THRUSTER_IDS: {len(selected)}")
    elif not FORCE_NOSE:
        selected = select_thrusters_by_vector(thrusters, escape_dir)

    if not selected:
        print("  Vector selection unavailable or empty; using nose local-position fallback...")
        selected = select_nose_thrusters_by_local_grid(ship, thrusters, sc)

    if not selected:
        print("ERROR: cannot select departure thrusters")
        return 1

    selected_ids = {str(t.device_id) for t in selected}
    print(f"  Selected thrusters: {len(selected)}")
    for thruster in selected[:30]:
        block_pos = get_block_local_pos(ship, thruster)
        print(f"    use id={thruster.device_id} name={safe_name(thruster)} local={block_pos}")
    if len(selected) > 30:
        print(f"    ... +{len(selected) - 30} more")

    print("\n[INIT] Preparing ship controls...")
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
        rc.dampeners_on()
    except Exception:
        pass

    for gyro in gyros:
        try:
            gyro.clear_override()
            gyro.enable()
        except Exception:
            pass

    clear_thrusters(thrusters)
    time.sleep(0.5)

    print("\n[UNDOCK] Releasing connector and immediately pushing nose thrusters...")

    try:
        ship.park_off()
    except Exception:
        pass

    try:
        sc.disconnect()
    except Exception as exc:
        print(f"  WARN: disconnect command failed: {exc}")

    time.sleep(0.15)

    try:
        sc.set_state(enabled=False)
        print("  Ship connector disabled to prevent magnetic re-lock")
    except Exception as exc:
        print(f"  WARN: cannot disable connector: {exc}")

    try:
        rc.dampeners_off()
    except Exception:
        pass

    # First kick happens before waiting for status; this uses the short no-magnet window.
    initial_kick = max(PUSH_OVERRIDE, 30.0)
    set_thrusters(selected, initial_kick)
    time.sleep(0.35)
    verify_override_applied(selected, initial_kick)

    is_connected, status, _ = check_connector(sc)
    print(f"  Connector status after release: connected={is_connected}, status={status}")

    if is_connected or status.lower() == "connected":
        print("  First disconnect did not release, retrying while thrust is already applied...")
        try:
            sc.disconnect()
        except Exception:
            pass
        time.sleep(0.5)
        try:
            sc.set_state(enabled=False)
        except Exception:
            pass
        is_connected, status, _ = check_connector(sc)
        print(f"  Connector status after retry: connected={is_connected}, status={status}")

    if is_connected or status.lower() == "connected":
        clear_thrusters(thrusters)
        print("ERROR: connector is still connected")
        return 1

    print("\n[PUSH] Moving away without autopilot...")
    start = time.time()
    last_print = -999.0
    last_clearance = start_clearance
    no_motion_since = start
    used_emergency = False

    try:
        while time.time() - start < MAX_PUSH_SECONDS:
            elapsed = time.time() - start
            wait_updates(sc, tc, rc, seconds=0.2)

            clearance = signed_clearance(sc, tc, escape_dir)
            if clearance is None:
                continue

            remaining = target_clearance - clearance
            gained = clearance - start_clearance

            if remaining <= 0.0:
                print(f"  Target clearance reached: {clearance:.2f}m")
                break

            if clearance > last_clearance + 0.05:
                last_clearance = clearance
                no_motion_since = time.time()

            no_motion_time = time.time() - no_motion_since
            if no_motion_time > 4.0 and gained < MIN_CLEARANCE_GAIN and not used_emergency:
                used_emergency = True
                print(
                    f"  WARN: no visible movement after {no_motion_time:.1f}s, "
                    f"raising override to {EMERGENCY_OVERRIDE:.1f}%"
                )

            base_override = EMERGENCY_OVERRIDE if used_emergency else PUSH_OVERRIDE
            ramp = clamp(elapsed / max(0.1, RAMP_SECONDS), 0.25, 1.0)
            brake = clamp(remaining / max(1.0, BRAKE_DISTANCE), 0.20, 1.0)
            override = base_override * ramp * brake

            set_thrusters(selected, override)

            if elapsed - last_print >= 1.0:
                speed = get_speed(rc)
                speed_text = f", speed={speed:.2f}m/s" if speed is not None else ""
                print(
                    f"  [{elapsed:5.1f}s] "
                    f"clearance={clearance:7.2f}m, gained={gained:6.2f}m, "
                    f"remaining={remaining:7.2f}m, override={override:5.1f}%"
                    f"{speed_text}"
                )
                last_print = elapsed
        else:
            print("  WARN: push timeout reached")
    finally:
        clear_thrusters(thrusters)

    print("\n[STOP] Enabling dampeners to stop drift...")
    try:
        rc.dampeners_on()
    except Exception:
        pass

    stop_start = time.time()
    while time.time() - stop_start < STOP_WAIT_SECONDS:
        wait_updates(rc, sc, tc, seconds=0.5)
        speed = get_speed(rc)
        clearance = signed_clearance(sc, tc, escape_dir)
        speed_text = "unknown" if speed is None else f"{speed:.2f}m/s"
        clearance_text = "unknown" if clearance is None else f"{clearance:.2f}m"
        print(f"  speed={speed_text}, clearance={clearance_text}")
        if speed is None or speed < 0.25:
            break

    final_clearance = signed_clearance(sc, tc, escape_dir)

    if final_clearance is not None and final_clearance > 10.0:
        try:
            sc.set_state(enabled=True)
            print("  Ship connector re-enabled after safe clearance")
        except Exception:
            pass
    else:
        print("  Ship connector left disabled because final clearance is too small")

    try:
        rc.disable()
    except Exception:
        pass
    try:
        rc.dampeners_on()
    except Exception:
        pass
    clear_thrusters(thrusters)

    print("\n[DONE]")
    if final_clearance is not None:
        print(f"  Final clearance: {final_clearance:.2f}m")
    print("  Autopilot was not used; no nose-to-target rotation was commanded.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
