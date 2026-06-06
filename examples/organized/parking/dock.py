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
import argparse
from pathlib import Path

# --- Locate repository root and load .env (handles \r\n) ---
def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root(Path(__file__).resolve())
env_path = REPO_ROOT / ".env"
if env_path.exists():
    with env_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

src_path = REPO_ROOT / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

try:
    from secontrol.common import prepare_grid, get_all_grids
except ImportError:
    from secontrol.common import prepare_grid
    get_all_grids = None
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.gyro_device import GyroDevice


def parse_args():
    parser = argparse.ArgumentParser(
        description="Automated docking with mandatory free target connector selection"
    )
    parser.add_argument("ship", nargs="?", default="104571351454649539", help="Ship grid name or ID")
    parser.add_argument("target", nargs="?", default="84360909276756422", help="Target grid name or ID")
    parser.add_argument("approach_distance", nargs="?", type=float, default=100.0, help="Approach distance in meters")
    parser.add_argument("--ship-connector-id", help="Use exact ship connector entity ID")
    parser.add_argument("--ship-connector-name", help="Use ship connector whose name contains this text")
    parser.add_argument("--target-connector-id", help="Use exact target connector entity ID; it must be free")
    parser.add_argument("--target-connector-name", help="Use free target connector whose name contains this text")
    parser.add_argument("--list-connectors", action="store_true", help="Print connector states and exit")
    parser.add_argument("--connector-check-retries", type=int, default=4, help="Telemetry refresh attempts before connector selection")
    parser.add_argument("--connector-check-delay", type=float, default=0.35, help="Delay between connector telemetry refreshes")

    # Physical port occupancy check.
    # ConnectorStatus can say "Unconnected" when another ship is being welded in
    # front of the port and its connector is disabled. Therefore a target port is
    # considered free only when its connector state is free AND the physical
    # corridor in front of it has no foreign connector.
    parser.add_argument("--port-occupancy-check", dest="port_occupancy_check", action="store_true", default=True, help="Check the physical corridor in front of target connectors; enabled by default")
    parser.add_argument("--no-port-occupancy-check", dest="port_occupancy_check", action="store_false", help="Disable physical connector-corridor occupancy check")
    parser.add_argument("--port-occupancy-depth", type=float, default=10.0, help="Depth in meters in front of a target connector that is treated as occupied")
    parser.add_argument("--port-occupancy-radius", type=float, default=4.0, help="Radius in meters around the target connector axis that is treated as occupied")
    parser.add_argument("--port-occupancy-max-grids", type=int, default=40, help="Maximum additional grids to inspect for blocking connectors")

    # Long-range pre-approach. If the ship is far from the base connector, first fly
    # to a 500m staging point with SpaceNavigatorController v5, then start the
    # existing precise connector docking phases.
    parser.add_argument("--long-approach", dest="long_approach", action="store_true", default=True, help="Use v5 navigation to a far staging point before precise docking; enabled by default")
    parser.add_argument("--no-long-approach", dest="long_approach", action="store_false", help="Disable v5 long-range pre-approach and use only the legacy precise approach")
    parser.add_argument("--long-approach-distance", type=float, default=500.0, help="Staging distance in front of the target connector, meters")
    parser.add_argument("--long-approach-threshold", type=float, default=700.0, help="Use v5 pre-approach only if the ship is farther than this from the 500m staging point")
    parser.add_argument("--long-approach-arrival", type=float, default=80.0, help="v5 arrival radius for the long-range staging point")
    parser.add_argument("--long-approach-max-speed", type=float, default=95.0, help="v5 open-space max speed")
    parser.add_argument("--long-approach-far-speed", type=float, default=75.0, help="v5 far speed")
    parser.add_argument("--long-approach-medium-speed", type=float, default=35.0, help="v5 medium speed")
    parser.add_argument("--long-approach-close-speed", type=float, default=8.0, help="v5 close speed")
    parser.add_argument("--long-approach-max-steps", type=int, default=200, help="v5 max scan/fly iterations for the pre-approach")
    parser.add_argument("--continue-after-long-approach-failure", action="store_true", help="Continue legacy docking even if v5 pre-approach fails; unsafe unless you know the path is clear")

    # Final retry loop. At the last meters the connector can miss the port even
    # after a good approach because the ship drifts, clips the connector rim, or
    # the RC autopilot stops before magnetic lock. In that case back out to a
    # clean line-up point and retry the final push a limited number of times.
    parser.add_argument("--final-dock-retries", type=int, default=5, help="Maximum final-stage backoff-and-retry attempts after a crooked or failed lock")
    parser.add_argument("--final-retry-distance", type=float, default=16.0, help="Distance in front of target connector for final retry backoff, meters")
    return parser.parse_args()


ARGS = parse_args()
SHIP = ARGS.ship
TARGET = ARGS.target
APPROACH_DIST = float(ARGS.approach_distance)

# Filled after grids are loaded. Used by target connector availability checks.
PORT_OCCUPANCY_CONNECTORS = None

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
# If we are already in the magnetic zone and lateral/angle error starts growing,
# the ship has missed the port. Do not keep pushing. Stop, back out to the
# stable line in front of the connector, then let Phase 3 retry the approach.
FINAL_PUSH_MISS_AXIAL_DISTANCE = 4.0
FINAL_PUSH_MISS_LATERAL_LIMIT = 0.85
FINAL_PUSH_MISS_ANGLE_LIMIT_DEG = 10.0
FINAL_PUSH_RECOVERY_DISTANCE = 14.0
FINAL_PUSH_RECOVERY_SPEED = 1.8
FINAL_PUSH_RECOVERY_TIMEOUT = 45.0
FINAL_RETRY_SAFE_DISTANCE_MIN_RATIO = 0.70
FINAL_RETRY_SAFE_DISTANCE_MAX_RATIO = 1.80
FINAL_RETRY_SAFE_LATERAL = 1.25
FINAL_RETRY_SAFE_ANGLE_DEG = 15.0
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


def normalize_entity_id(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if int(value) == 0:
            return None
        return str(int(value))
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "0"}:
        return None
    try:
        return str(int(float(text)))
    except Exception:
        return text


def same_entity_id(left, right):
    left_id = normalize_entity_id(left)
    right_id = normalize_entity_id(right)
    return left_id is not None and right_id is not None and left_id == right_id


def connector_entity_id(connector):
    return normalize_entity_id(getattr(connector, "device_id", None))


def connector_display_name(connector):
    name = getattr(connector, "name", None) or "Connector"
    return f"{name} ({getattr(connector, 'device_id', 'unknown')})"


def connector_status_text(connector):
    t = connector.telemetry or {}
    is_conn, status, other_id = check_connector(connector)
    return (
        f"status={status or 'N/A'} "
        f"connected={is_conn} "
        f"other={normalize_entity_id(other_id) or '-'} "
        f"enabled={t.get('enabled', 'N/A')} "
        f"functional={t.get('isFunctional', 'N/A')} "
        f"working={t.get('isWorking', 'N/A')}"
    )


def telemetry_bool(telemetry, key, default=True):
    if not isinstance(telemetry, dict):
        return default
    if key not in telemetry or telemetry.get(key) is None:
        return default
    return bool(telemetry.get(key))


def connector_is_powered_and_functional(connector):
    t = connector.telemetry or {}
    if not telemetry_bool(t, "enabled", True):
        return False, "disabled"
    if not telemetry_bool(t, "isFunctional", True):
        return False, "not functional"
    if not telemetry_bool(t, "isWorking", True):
        return False, "not working"
    return True, "available"


def connector_has_pose(connector):
    pos = get_pos(connector.telemetry or {})
    fwd = get_connector_forward(connector)
    if not pos:
        return False, "no position telemetry"
    if fwd == (0.0, 0.0, 0.0):
        return False, "no forward vector telemetry"
    return True, "pose available"


def ship_connector_is_usable(connector):
    ok, reason = connector_is_powered_and_functional(connector)
    if not ok:
        return False, reason

    pose_ok, pose_reason = connector_has_pose(connector)
    if not pose_ok:
        return False, pose_reason

    is_conn, status, other_id = check_connector(connector)
    status_norm = (status or "").strip().lower()
    if is_conn or status_norm == "connected":
        return False, f"already connected to {normalize_entity_id(other_id) or 'unknown connector'}"

    return True, "usable"


def target_connector_is_available(
    connector,
    ship_connector=None,
    *,
    allow_ship_connectable=False,
    occupancy_connectors=None,
    occupancy_depth=None,
    occupancy_radius=None,
):
    if occupancy_depth is None:
        occupancy_depth = ARGS.port_occupancy_depth
    if occupancy_radius is None:
        occupancy_radius = ARGS.port_occupancy_radius

    ok, reason = connector_is_powered_and_functional(connector)
    if not ok:
        return False, reason

    pose_ok, pose_reason = connector_has_pose(connector)
    if not pose_ok:
        return False, pose_reason

    is_conn, status, other_id = check_connector(connector)
    status_norm = (status or "").strip().lower()
    other = normalize_entity_id(other_id)
    ship_id = connector_entity_id(ship_connector) if ship_connector is not None else None

    if is_conn or status_norm == "connected":
        if allow_ship_connectable and same_entity_id(other, ship_id):
            return True, "already connected to selected ship connector"
        return False, f"occupied: connected to {other or 'unknown connector'}"

    if other is not None:
        if allow_ship_connectable and same_entity_id(other, ship_id):
            return True, "reserved by selected ship connector"
        return False, f"occupied/reserved by {other}"

    if status_norm == "connectable":
        return False, "connectable but otherConnectorId is missing; cannot prove it is our connector"

    # Second-level physical occupancy check.
    # This catches disabled/offline connectors created by projector/welding in
    # front of a base connector. Such connectors may not appear in otherConnectorId
    # and may keep ConnectorStatus as Unconnected, but the docking port is still
    # physically occupied.
    if occupancy_connectors is None:
        occupancy_connectors = PORT_OCCUPANCY_CONNECTORS

    if occupancy_connectors is not None:
        port_free, port_reason = target_port_is_physically_free(
            connector,
            ship_connector,
            occupancy_connectors,
            depth=occupancy_depth,
            radius=occupancy_radius,
            allow_ship_connector=True,
        )
        if not port_free:
            return False, port_reason

    return True, "free"

def connector_world_position(connector):
    return get_pos(connector.telemetry or {})


def connector_enabled_text(connector):
    telemetry = connector.telemetry or {}
    enabled = telemetry.get("enabled", telemetry.get("Enabled", telemetry.get("isEnabled")))
    functional = telemetry.get("functional", telemetry.get("Functional", telemetry.get("isFunctional")))
    return f"enabled={enabled}, functional={functional}"


def is_connector_in_target_port_corridor(
    target_connector,
    candidate_connector,
    *,
    depth=10.0,
    radius=4.0,
):
    target_id = connector_entity_id(target_connector)
    candidate_id = connector_entity_id(candidate_connector)

    if same_entity_id(target_id, candidate_id):
        return False, None

    target_pos = connector_world_position(target_connector)
    candidate_pos = connector_world_position(candidate_connector)

    if not target_pos or not candidate_pos:
        return False, None

    orient = (target_connector.telemetry or {}).get("orientation", {})
    target_fwd = normalize(get_vec3(orient.get("forward")) or (0.0, 0.0, 0.0))

    if target_fwd == (0.0, 0.0, 0.0):
        return False, None

    rel = vec_sub(candidate_pos, target_pos)
    axial = dot(rel, target_fwd)

    if axial < 0.25 or axial > float(depth):
        return False, None

    lateral_vec = vec_add(rel, -axial, target_fwd)
    lateral = vec_len(lateral_vec)

    if lateral > float(radius):
        return False, None

    info = {
        "candidate_id": candidate_id,
        "candidate_name": getattr(candidate_connector, "name", None) or "Connector",
        "axial": axial,
        "lateral": lateral,
        "state": connector_enabled_text(candidate_connector),
    }
    return True, info


def collect_connectors_for_occupancy(ship_grid, target_grid, *, max_grids=40):
    connectors = []

    def add_grid_connectors(grid):
        try:
            grid_connectors = grid.find_devices_by_type(ConnectorDevice)
        except Exception:
            return

        for connector in grid_connectors:
            try:
                connector.update()
            except Exception:
                pass
            connectors.append(connector)

    add_grid_connectors(ship_grid)
    add_grid_connectors(target_grid)

    if get_all_grids is None:
        print("  WARNING: get_all_grids is not available; port occupancy check is limited to ship and target grids")
        return connectors

    try:
        try:
            all_grids = get_all_grids(exclude_subgrids=False)
        except TypeError:
            all_grids = get_all_grids()
    except Exception as exc:
        print(f"  WARNING: cannot list all grids for port occupancy check: {exc}")
        return connectors

    seen_grid_ids = {str(ship_grid.grid_id), str(target_grid.grid_id)}
    loaded = 0

    for grid_id, grid_name in all_grids:
        grid_id = str(grid_id)

        if grid_id in seen_grid_ids:
            continue

        if loaded >= int(max_grids):
            print(f"  WARNING: port occupancy scan reached max grids limit: {max_grids}")
            break

        try:
            grid = prepare_grid(grid_id)
            time.sleep(0.05)
            add_grid_connectors(grid)
            seen_grid_ids.add(grid_id)
            loaded += 1
        except Exception as exc:
            print(f"  WARNING: cannot inspect grid {grid_name} ({grid_id}) for connectors: {exc}")

    return connectors


def target_port_is_physically_free(
    target_connector,
    ship_connector,
    occupancy_connectors,
    *,
    depth=10.0,
    radius=4.0,
    allow_ship_connector=True,
):
    ship_id = connector_entity_id(ship_connector)

    for candidate in occupancy_connectors or []:
        candidate_id = connector_entity_id(candidate)

        if same_entity_id(candidate_id, connector_entity_id(target_connector)):
            continue

        if allow_ship_connector and same_entity_id(candidate_id, ship_id):
            continue

        blocked, info = is_connector_in_target_port_corridor(
            target_connector,
            candidate,
            depth=depth,
            radius=radius,
        )

        if not blocked:
            continue

        return False, (
            "port corridor blocked by "
            f"{info['candidate_name']} ({info['candidate_id']}), "
            f"axial={info['axial']:.2f}m, lateral={info['lateral']:.2f}m, "
            f"{info['state']}"
        )

    return True, "port corridor is clear"

def print_connector_table(title, connectors, *, ship_connector=None, target_mode=False):
    print(title)
    if not connectors:
        print("  <none>")
        return

    for connector in connectors:
        if target_mode:
            ok, reason = target_connector_is_available(connector, ship_connector, allow_ship_connectable=True, occupancy_connectors=PORT_OCCUPANCY_CONNECTORS, occupancy_depth=ARGS.port_occupancy_depth, occupancy_radius=ARGS.port_occupancy_radius)
        else:
            ok, reason = ship_connector_is_usable(connector)
        mark = "OK" if ok else "BUSY"
        print(f"  [{mark}] {connector_display_name(connector)} — {connector_status_text(connector)} — {reason}")


def refresh_connector_lists(sc_list, tc_list, retries=4, delay=0.35):
    devices = list(sc_list) + list(tc_list)
    for _ in range(max(1, int(retries))):
        refresh_devices(*devices, delay=delay)


def connector_matches_filter(connector, *, connector_id=None, name=None):
    if connector_id and not same_entity_id(connector_entity_id(connector), connector_id):
        return False
    if name:
        needle = str(name).strip().lower()
        haystack = str(getattr(connector, "name", "") or "").lower()
        if needle not in haystack:
            return False
    return True


def choose_ship_connector(connectors, *, connector_id=None, name=None):
    matches = [
        connector for connector in connectors
        if connector_matches_filter(connector, connector_id=connector_id, name=name)
    ]

    if not matches:
        return None, "no ship connector matched filter"

    rejected = []
    for connector in matches:
        ok, reason = ship_connector_is_usable(connector)
        if ok:
            return connector, "selected"
        rejected.append((connector, reason))

    details = "; ".join(f"{connector_display_name(c)}: {reason}" for c, reason in rejected)
    return None, details or "no usable ship connector"


def choose_target_connector(
    connectors,
    ship_connector,
    *,
    connector_id=None,
    name=None,
    occupancy_connectors=None,
    occupancy_depth=None,
    occupancy_radius=None,
):
    if occupancy_depth is None:
        occupancy_depth = ARGS.port_occupancy_depth
    if occupancy_radius is None:
        occupancy_radius = ARGS.port_occupancy_radius

    matches = [
        connector for connector in connectors
        if connector_matches_filter(connector, connector_id=connector_id, name=name)
    ]

    if not matches:
        return None, "no target connector matched filter"

    sc_pos = get_pos(ship_connector.telemetry or {})

    def sort_key(connector):
        pos = get_pos(connector.telemetry or {})
        distance = dist3(sc_pos, pos) if sc_pos and pos else float("inf")
        return (distance, str(getattr(connector, "name", "") or ""), str(getattr(connector, "device_id", "")))

    matches.sort(key=sort_key)

    rejected = []
    for connector in matches:
        ok, reason = target_connector_is_available(
            connector,
            ship_connector,
            allow_ship_connectable=bool(connector_id),
            occupancy_connectors=occupancy_connectors,
            occupancy_depth=occupancy_depth,
            occupancy_radius=occupancy_radius,
        )
        if ok:
            return connector, "selected"
        rejected.append((connector, reason))

    details = "; ".join(f"{connector_display_name(c)}: {reason}" for c, reason in rejected)
    return None, details or "no free target connector"

def ensure_target_connector_available(
    target_connector,
    ship_connector,
    context,
    *,
    allow_ship_connectable=True,
    occupancy_connectors=None,
    occupancy_depth=None,
    occupancy_radius=None,
):
    if occupancy_depth is None:
        occupancy_depth = ARGS.port_occupancy_depth
    if occupancy_radius is None:
        occupancy_radius = ARGS.port_occupancy_radius

    try:
        target_connector.update()
    except Exception:
        pass
    try:
        ship_connector.update()
    except Exception:
        pass

    # Refresh known blocking connectors as well. This catches state/position
    # changes of already known welded grids during a long docking sequence.
    if occupancy_connectors is None:
        occupancy_connectors = PORT_OCCUPANCY_CONNECTORS

    if occupancy_connectors:
        for candidate in occupancy_connectors:
            try:
                candidate.update()
            except Exception:
                pass

    ok, reason = target_connector_is_available(
        target_connector,
        ship_connector,
        allow_ship_connectable=allow_ship_connectable,
        occupancy_connectors=occupancy_connectors,
        occupancy_depth=occupancy_depth,
        occupancy_radius=occupancy_radius,
    )
    if ok:
        return True

    print(
        f"ERROR: target connector is not available during {context}: "
        f"{connector_display_name(target_connector)} — {connector_status_text(target_connector)} — {reason}"
    )
    return False

def connector_is_connected_to_target(ship_connector, target_connector):
    sc_connected, _, sc_other = check_connector(ship_connector)
    tc_connected, _, tc_other = check_connector(target_connector)
    return (
        sc_connected
        and tc_connected
        and same_entity_id(sc_other, connector_entity_id(target_connector))
        and same_entity_id(tc_other, connector_entity_id(ship_connector))
    )


def try_connect(sc, tc=None, label="", axis_dist=None):
    """
    Try to lock connector.

    Important:
    Physical contact is NOT treated as successful docking.
    Docking is successful only when connectorIsConnected becomes True.
    If target connector is provided, the lock is accepted only with that target.
    """
    is_conn, status, other_id = check_connector(sc)
    if is_conn:
        if tc is None or connector_is_connected_to_target(sc, tc):
            return True

        print(
            f"  {label}SAFETY: ship connector is connected to wrong connector "
            f"{normalize_entity_id(other_id) or 'unknown'}, expected {connector_entity_id(tc)}"
        )
        return False

    if tc is not None:
        if not ensure_target_connector_available(tc, sc, "connect attempt", allow_ship_connectable=True):
            return False

    if status == "Connectable":
        other = normalize_entity_id(other_id)
        if tc is not None and other is not None and not same_entity_id(other, connector_entity_id(tc)):
            print(
                f"  {label}SAFETY: ship connector sees wrong target "
                f"{other}, expected {connector_entity_id(tc)} — connect skipped"
            )
            return False

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
            if tc is not None:
                try:
                    tc.update()
                except Exception:
                    pass

            is_conn, status, other_id = check_connector(sc)
            if is_conn:
                if tc is None or connector_is_connected_to_target(sc, tc):
                    print(f"  {label}>> LOCKED!")
                    return True

                print(
                    f"  {label}SAFETY: locked to wrong connector "
                    f"{normalize_entity_id(other_id) or 'unknown'}, expected {connector_entity_id(tc)}"
                )
                try:
                    sc.disconnect()
                except Exception:
                    pass
                return False

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


def get_target_connector_forward(tc):
    orient = (tc.telemetry or {}).get("orientation", {})
    return normalize(get_vec3(orient.get("forward")) or (0.0, 0.0, 0.0))


def get_stable_target_docking_axis(tc, fallback=None):
    """
    Return the fixed approach axis derived only from the target connector.

    This deliberately ignores the current ship position. After a missed final
    push the dynamic connector-to-connector vector can flip and make a backoff
    command drive the ship into the port again. Recovery/backoff must use this
    stable target-axis version.
    """
    target_fwd = get_target_connector_forward(tc)
    if target_fwd == (0.0, 0.0, 0.0):
        return normalize(fallback) if fallback is not None else (0.0, 0.0, 0.0)
    return normalize(vec_neg(target_fwd))


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


def run_v5_long_approach(grid_name, target_pos):
    """Fly to the far docking staging point with SpaceNavigatorController v5."""
    try:
        from secontrol.controllers.space_navigator_controller import (
            OpenSpaceBoostConfig,
            SpaceNavigatorController,
            SpeedZone,
        )
    except Exception as exc:
        print(f"  V5 PRE-APPROACH ERROR: cannot import SpaceNavigatorController v5: {exc}")
        return False

    print("\n" + "=" * 60)
    print("PHASE 0: V5 LONG-RANGE PRE-APPROACH")
    print("=" * 60)
    print(
        f"  v5 target: ({target_pos[0]:.1f}, {target_pos[1]:.1f}, {target_pos[2]:.1f}) "
        f"arrival={ARGS.long_approach_arrival:.1f}m"
    )

    speed_zone = SpeedZone(
        max_speed=ARGS.long_approach_max_speed,
        far_speed=ARGS.long_approach_far_speed,
        medium_speed=ARGS.long_approach_medium_speed,
        near_speed=(ARGS.long_approach_medium_speed + ARGS.long_approach_close_speed) / 2.0,
        close_speed=ARGS.long_approach_close_speed,
    )
    open_space_boost = OpenSpaceBoostConfig(
        enabled=True,
        open_space_radius=900.0,
        lookahead=3000.0,
        corridor_radius=140.0,
        min_target_distance=700.0,
        safety_margin=140.0,
        brake_accel=8.0,
        reaction_time=1.5,
        scan_max_age=3.0,
        coarse_only=True,
    )

    controller = None
    try:
        controller = SpaceNavigatorController(
            grid_name=str(grid_name),
            speed_zone=speed_zone,
            arrival_distance=ARGS.long_approach_arrival,
            max_steps=ARGS.long_approach_max_steps,
            target_is_obstacle=False,
            open_space_boost=open_space_boost,
        )
        result = controller.navigate_to(target_pos)
        print(
            f"  V5 PRE-APPROACH RESULT: status={result.status} "
            f"arrived={bool(result)} message={result.message or '-'}"
        )
        return bool(result)
    except Exception as exc:
        print(f"  V5 PRE-APPROACH ERROR: {exc}")
        return False
    finally:
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass


def final_push_miss_reason(cur_axial, cur_lateral, cur_angle, status):
    if str(status or "").strip().lower() == "connectable":
        return None

    if cur_axial <= -0.15:
        return f"passed target plane: axial={cur_axial:.2f}m"

    if cur_axial <= FINAL_PUSH_MISS_AXIAL_DISTANCE:
        if cur_lateral > FINAL_PUSH_MISS_LATERAL_LIMIT:
            return (
                f"miss detected near connector: axial={cur_axial:.2f}m, "
                f"lateral={cur_lateral:.2f}m > {FINAL_PUSH_MISS_LATERAL_LIMIT:.2f}m"
            )
        if cur_angle > FINAL_PUSH_MISS_ANGLE_LIMIT_DEG:
            return (
                f"miss detected near connector: axial={cur_axial:.2f}m, "
                f"angle={cur_angle:.1f}° > {FINAL_PUSH_MISS_ANGLE_LIMIT_DEG:.1f}°"
            )

    return None


def recover_after_missed_final_push(
    rc,
    sc,
    tc,
    gyros,
    reason,
    *,
    distance=FINAL_PUSH_RECOVERY_DISTANCE,
):
    """
    Recover from a missed final push.

    The old behavior could keep pushing forward after the connector had already
    slipped sideways or passed the target plane. This routine stops the ship,
    backs the ship connector out to a fixed point in front of the target
    connector, re-aligns, and returns control to the main Phase 3 loop.
    """
    print(f"  MISS RECOVERY: {reason}")
    print(
        f"  MISS RECOVERY: backing out to stable line "
        f"{float(distance):.1f}m in front of target connector"
    )

    stop_ship(rc, gyros, settle=0.45)
    refresh_devices(rc, sc, tc, delay=0.15)

    tc_pos = get_pos(tc.telemetry or {})
    if not tc_pos:
        print("  MISS RECOVERY: no target connector position, cannot recover")
        return False

    stable_axis = get_stable_target_docking_axis(tc)
    if stable_axis == (0.0, 0.0, 0.0):
        print("  MISS RECOVERY: no stable target axis, cannot recover")
        return False

    connector_target = vec_add(tc_pos, -float(distance), stable_axis)

    ok = fly_connector_to_position(
        rc=rc,
        sc=sc,
        connector_target_pos=connector_target,
        speed=FINAL_PUSH_RECOVERY_SPEED,
        gps_name="MissRecoveryBackout",
        timeout=FINAL_PUSH_RECOVERY_TIMEOUT,
        stop_radius=0.9,
    )

    stop_ship(rc, gyros, settle=0.6)
    refresh_devices(rc, sc, tc, delay=0.2)

    if not ok:
        print("  MISS RECOVERY: backout command timed out, geometry will be re-evaluated")
        return False

    final_angle = correct_orientation(
        rc=rc,
        sc=sc,
        gyros=gyros,
        axis_dir=stable_axis,
        timeout=12,
        tolerance=FINAL_ALIGN_TOLERANCE,
    )

    refresh_devices(rc, sc, tc, delay=0.15)
    cur_sc = get_pos(sc.telemetry or {})
    cur_tc = get_pos(tc.telemetry or {})

    if cur_sc and cur_tc:
        axial, lateral, _, _ = compute_docking_geometry(cur_sc, cur_tc, stable_axis)
        print(
            f"  MISS RECOVERY: ready for retry, axial={axial:.2f}m, "
            f"lateral={lateral:.2f}m, angle={math.degrees(final_angle):.1f}°"
        )
    else:
        print(f"  MISS RECOVERY: ready for retry, angle={math.degrees(final_angle):.1f}°")

    return True


def get_final_retry_distance():
    try:
        return max(
            FINAL_PUSH_RECOVERY_DISTANCE,
            float(getattr(ARGS, "final_retry_distance", FINAL_PUSH_RECOVERY_DISTANCE)),
        )
    except Exception:
        return FINAL_PUSH_RECOVERY_DISTANCE


def prepare_final_dock_retry(rc, sc, tc, gyros, reason, retry_no, max_retries):
    """
    Prepare a clean repeated final docking attempt.

    This is deliberately separate from the inner FinalPush resume logic. The
    inner logic only retries the same continuous push while the approach is
    still clean. This routine handles the bad final state: the ship is too
    sideways, angled, has passed the connector plane, or failed to lock after
    hard contact. It backs out to a stable connector-axis point and re-aligns
    before the main Phase 3 loop tries the final push again.
    """
    print(
        f"  FINAL RETRY {retry_no}/{max_retries}: {reason}. "
        "Backing out and preparing another final lock attempt."
    )

    stop_ship(rc, gyros, settle=0.45)
    refresh_devices(rc, sc, tc, delay=0.2)

    if connector_is_connected_to_target(sc, tc):
        print("  FINAL RETRY: already locked after telemetry refresh")
        return True

    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})
    stable_axis = get_stable_target_docking_axis(tc)
    retry_distance = get_final_retry_distance()

    if sc_pos and tc_pos and stable_axis != (0.0, 0.0, 0.0):
        axial, lateral, _, _ = compute_docking_geometry(sc_pos, tc_pos, stable_axis)
        angle_deg = math.degrees(get_connector_angle(sc, stable_axis))
        min_safe = retry_distance * FINAL_RETRY_SAFE_DISTANCE_MIN_RATIO
        max_safe = retry_distance * FINAL_RETRY_SAFE_DISTANCE_MAX_RATIO

        if (
            min_safe <= axial <= max_safe
            and lateral <= FINAL_RETRY_SAFE_LATERAL
            and angle_deg <= FINAL_RETRY_SAFE_ANGLE_DEG
        ):
            print(
                f"  FINAL RETRY: ship is already backed out enough: "
                f"axial={axial:.2f}m lateral={lateral:.2f}m angle={angle_deg:.1f}°"
            )
            final_angle = correct_orientation(
                rc=rc,
                sc=sc,
                gyros=gyros,
                axis_dir=stable_axis,
                timeout=12,
                tolerance=FINAL_ALIGN_TOLERANCE,
            )
            print(f"  FINAL RETRY: angle after re-align {math.degrees(final_angle):.1f}°")
            return True

    recovered = recover_after_missed_final_push(
        rc=rc,
        sc=sc,
        tc=tc,
        gyros=gyros,
        reason=reason,
        distance=retry_distance,
    )
    return recovered or connector_is_connected_to_target(sc, tc)


def final_push_to_connector(rc, sc, tc, axis_dir, gyros):
    """
    Final docking movement.

    RC autopilot often ignores very small GPS shifts near the connector because
    its internal arrival radius is larger than our final correction. To avoid
    this, we give RC a target behind the target connector, but stop ourselves
    using connector telemetry and connector status.
    """
    refresh_devices(rc, sc, tc, delay=0.1)
    if not ensure_target_connector_available(tc, sc, "final push start", allow_ship_connectable=True):
        return False

    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})

    if not sc_pos or not tc_pos:
        return False

    axis_dir = get_stable_target_docking_axis(tc, fallback=axis_dir)
    if axis_dir == (0.0, 0.0, 0.0):
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

        if not ensure_target_connector_available(tc, sc, "final push", allow_ship_connectable=True):
            break

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

        miss_reason = final_push_miss_reason(cur_axial, cur_lateral, cur_angle, status)
        if miss_reason:
            recover_after_missed_final_push(rc, sc, tc, gyros, miss_reason)
            return False

        allowed_lateral_now = (
            FINAL_PUSH_LATERAL_TOLERANCE_NEAR
            if cur_axial <= SAFE_NEAR_DISTANCE
            else FINAL_PUSH_LATERAL_TOLERANCE_FAR
        )

        if cur_lateral > allowed_lateral_now * 2.0:
            recover_after_missed_final_push(
                rc,
                sc,
                tc,
                gyros,
                f"lateral error grew to {cur_lateral:.2f}m > {allowed_lateral_now * 2.0:.2f}m",
            )
            return False

        if cur_angle > SAFE_PANIC_ANGLE_DEG:
            recover_after_missed_final_push(
                rc,
                sc,
                tc,
                gyros,
                f"angle grew to {cur_angle:.1f}°",
            )
            return False

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
            sc.connect()
            for _ in range(8):
                time.sleep(0.25)
                refresh_devices(sc, delay=0)
                if check_connector(sc)[0]:
                    print("  FINAL PUSH: >> LOCKED!")
                    return True
            recover_after_missed_final_push(
                rc,
                sc,
                tc,
                gyros,
                f"connector passed target plane axial={cur_axial:.2f}m",
            )
            return False

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
                recover_after_missed_final_push(
                    rc,
                    sc,
                    tc,
                    gyros,
                    f"hard contact/no progress at axial={cur_axial:.2f}m",
                )
                return False

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

    stable_axis = get_stable_target_docking_axis(tc, fallback=axis_dir)
    if stable_axis == (0.0, 0.0, 0.0):
        stable_axis = axis_dir

    # Move away from the port using a fixed target connector axis. Do not use
    # the dynamic axis after a miss: it may flip and command another forward push.
    away_dir = vec_neg(stable_axis)

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

refresh_connector_lists(
    sc_list,
    tc_list,
    retries=ARGS.connector_check_retries,
    delay=ARGS.connector_check_delay,
)

if ARGS.list_connectors:
    print(f"  Ship: {ship.name} (ID: {ship.grid_id})")
    print(f"  Target: {target_grid.name} (ID: {target_grid.grid_id})")
    print_connector_table("\nShip connectors:", sc_list, target_mode=False)
    print_connector_table("\nTarget connectors:", tc_list, ship_connector=sc_list[0] if sc_list else None, target_mode=True)
    sys.exit(0)

sc, sc_reason = choose_ship_connector(
    sc_list,
    connector_id=ARGS.ship_connector_id,
    name=ARGS.ship_connector_name,
)
if not sc:
    print(f"ERROR: no usable ship connector: {sc_reason}")
    print_connector_table("\nShip connectors:", sc_list, target_mode=False)
    sys.exit(1)

if ARGS.port_occupancy_check:
    print("\n[CHECK] Scanning physical connector port occupancy...")
    PORT_OCCUPANCY_CONNECTORS = collect_connectors_for_occupancy(
        ship,
        target_grid,
        max_grids=ARGS.port_occupancy_max_grids,
    )
    print(f"  Known connectors for occupancy check: {len(PORT_OCCUPANCY_CONNECTORS)}")
else:
    PORT_OCCUPANCY_CONNECTORS = None
    print("\n[CHECK] Physical connector port occupancy check disabled")

tc, tc_reason = choose_target_connector(
    tc_list,
    sc,
    connector_id=ARGS.target_connector_id,
    name=ARGS.target_connector_name,
    occupancy_connectors=PORT_OCCUPANCY_CONNECTORS,
    occupancy_depth=ARGS.port_occupancy_depth,
    occupancy_radius=ARGS.port_occupancy_radius,
)
if not tc:
    print(f"ERROR: no free target connector: {tc_reason}")
    print_connector_table("\nTarget connectors:", tc_list, ship_connector=sc, target_mode=True)
    sys.exit(1)

print(f"  Ship: {ship.name} (ID: {ship.grid_id})")
print(f"  Target: {target_grid.name} (ID: {target_grid.grid_id})")
print(f"  Ship connector: {connector_display_name(sc)} — {connector_status_text(sc)}")
print(f"  Target connector: {connector_display_name(tc)} — {connector_status_text(tc)}")
print(
    "  Free target connectors: "
    f"{sum(1 for c in tc_list if target_connector_is_available(c, sc, allow_ship_connectable=False, occupancy_connectors=PORT_OCCUPANCY_CONNECTORS, occupancy_depth=ARGS.port_occupancy_depth, occupancy_radius=ARGS.port_occupancy_radius)[0])}/{len(tc_list)}"
)
print(f"  Gyros: {len(gyros)}")

# =====================================================================
# PHASE 1: Fly to approach point
# =====================================================================

print("\n" + "=" * 60)
print("PHASE 1: APPROACH POINT")
print("=" * 60)

refresh_devices(rc, sc, tc, delay=0.2)
if not ensure_target_connector_available(tc, sc, "Phase 1 approach planning", allow_ship_connectable=True):
    sys.exit(1)

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


def compute_approach_targets(approach_distance):
    rc_position = get_pos(rc.telemetry or {})
    sc_position = get_pos(sc.telemetry or {})

    if not rc_position:
        print("ERROR: no ship remote control position")
        sys.exit(1)

    if not sc_position:
        print("ERROR: no ship connector position")
        sys.exit(1)

    connector_offset_local = vec_sub(sc_position, rc_position)
    connector_target_point = vec_add(t_pos, -float(approach_distance), stable_axis_dir)
    remote_target_point = vec_sub(connector_target_point, connector_offset_local)
    return rc_position, sc_position, connector_target_point, remote_target_point


rc_pos, sc_pos, long_target_point, long_ship_target = compute_approach_targets(ARGS.long_approach_distance)
long_distance = dist3(rc_pos, long_ship_target)
base_distance = dist3(sc_pos, t_pos)

print(f"  Target connector: ({t_pos[0]:.1f}, {t_pos[1]:.1f}, {t_pos[2]:.1f})")
print(
    f"  Long staging point ({ARGS.long_approach_distance:.1f}m): "
    f"({long_target_point[0]:.1f}, {long_target_point[1]:.1f}, {long_target_point[2]:.1f})"
)
print(f"  Distance to target connector: {base_distance:.1f}m")
print(f"  Distance to long staging point: {long_distance:.1f}m")

if ARGS.long_approach and base_distance > ARGS.long_approach_threshold:
    ok = run_v5_long_approach(SHIP, long_ship_target)
    stop_ship(rc, gyros=None, settle=1.0)
    refresh_devices(rc, sc, tc, delay=0.5)

    if not ok:
        print(
            "ERROR: v5 long-range pre-approach failed. "
            "Precise docking from this distance is intentionally blocked for safety."
        )
        print("       Use --continue-after-long-approach-failure only if the path is known to be clear.")
        if not ARGS.continue_after_long_approach_failure:
            sys.exit(1)

    rc_pos, sc_pos, long_target_point, long_ship_target = compute_approach_targets(ARGS.long_approach_distance)
    long_distance = dist3(rc_pos, long_ship_target)
    base_distance = dist3(sc_pos, t_pos)
    print(f"  Distance to target connector after v5: {base_distance:.1f}m")
    print(f"  Distance to long staging point after v5: {long_distance:.1f}m")
else:
    if not ARGS.long_approach:
        print("  V5 long-range pre-approach disabled by --no-long-approach")
    else:
        print(
            f"  V5 long-range pre-approach skipped: "
            f"target connector distance {base_distance:.1f}m <= threshold {ARGS.long_approach_threshold:.1f}m"
        )

rc_pos, sc_pos, target_point, ship_target = compute_approach_targets(APPROACH_DIST)

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
        rc.start_autopilot()
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
if not ensure_target_connector_available(tc, sc, "Phase 2 rotation planning", allow_ship_connectable=True):
    sys.exit(1)

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
final_dock_retries_done = 0
max_final_dock_retries = max(0, int(getattr(ARGS, "final_dock_retries", 5)))
connected = False
aborted = False

while True:
    step += 1

    refresh_devices(rc, sc, tc, delay=0.1)
    if not ensure_target_connector_available(tc, sc, f"Phase 3 step {step}", allow_ship_connectable=True):
        aborted = True
        break

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

    if try_connect(sc, tc, "", raw_dist):
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

    if try_connect(sc, tc, "  ", raw_dist):
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

        refresh_devices(rc, sc, tc, delay=0.2)
        if connector_is_connected_to_target(sc, tc):
            connected = True
            break

        if final_dock_retries_done >= max_final_dock_retries:
            print(
                f"  SAFETY: final docking retry limit reached "
                f"({max_final_dock_retries}), aborting docking"
            )
            aborted = True
            break

        final_dock_retries_done += 1
        retry_ready = prepare_final_dock_retry(
            rc=rc,
            sc=sc,
            tc=tc,
            gyros=gyros,
            reason="final push failed or connector approached crookedly",
            retry_no=final_dock_retries_done,
            max_retries=max_final_dock_retries,
        )

        refresh_devices(rc, sc, tc, delay=0.2)
        if connector_is_connected_to_target(sc, tc):
            connected = True
            break

        if not retry_ready:
            print("  FINAL RETRY: recovery did not reach a clean retry position; geometry will be re-evaluated")

        previous_angle_deg = None
        continue

    remaining_before_final_push = signed_axial - FINAL_PUSH_START_DISTANCE
    move_dist = min(step_size, max(0.0, remaining_before_final_push))

    if signed_axial > NEAR_CREEP_DISTANCE and move_dist < 1.0:
        move_dist = min(1.0, remaining_before_final_push)

    if signed_axial > SAFE_NEAR_DISTANCE and move_dist < 1.5:
        move_dist = min(1.5, remaining_before_final_push)

    if move_dist < 0.05:
        if try_connect(sc, tc, "  ", raw_dist):
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
    rc.start_autopilot()

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

        if try_connect(sc, tc, "  ", cur_raw):
            connected = True
            break

        cur_angle = math.degrees(get_connector_angle(sc, cur_axis))
        cur_to_target = dist3(cur_sc, connector_target) if cur_sc else 999999.0
        ap = bool((rc.telemetry or {}).get("autopilotEnabled", False))

        if cur_axial <= CONNECT_ATTEMPT_DISTANCE:
            if try_connect(sc, tc, "  ", cur_axial):
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
