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
print(f"  Target connector: ({t_pos[0]:.1f}, {t_pos[1]:.1f}, {t_pos[2]:.1f})")
print(f"  Approach point ({APPROACH_DIST}m): ({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})")

rc.enable()
rc.thrusters_on()
rc.dampeners_on()
time.sleep(1)

gps = f"GPS:Approach:{target_point[0]:.1f}:{target_point[1]:.1f}:{target_point[2]:.1f}:"
print(f"  Flying to approach point...")
rc.goto(gps, speed=10.0, gps_name="Approach")
time.sleep(2)

start = time.time()
while time.time() - start < 300:
    time.sleep(3)
    cur = get_pos(rc.telemetry or {})
    if not cur: continue
    d = dist3(cur, target_point)
    ap = (rc.telemetry or {}).get("autopilotEnabled", False)
    print(f"  [{time.time()-start:.0f}s] dist={d:.1f}m")
    if d < 5.0: break
    if not ap and d < 20.0: break
    if not ap and time.time() - start > 15 and d > 20.0: break

rc.disable()
rc.dampeners_on()
time.sleep(1)
print(f"  Phase 1 complete.")

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
# PHASE 3: Connector-axis approach + auto-lock
# =====================================================================
print("\n" + "=" * 60)
print("PHASE 3: CONNECTOR APPROACH + LOCK")
print("=" * 60)

step = 0
stuck_count = 0
prev_dist = float('inf')
connected = False

while True:
    step += 1

    sc_pos = get_pos(sc.telemetry or {})
    tc_pos = get_pos(tc.telemetry or {})
    if not sc_pos or not tc_pos:
        time.sleep(1); continue

    axis_vec = vec_sub(tc_pos, sc_pos)
    axis_dist = math.sqrt(axis_vec[0]**2 + axis_vec[1]**2 + axis_vec[2]**2)
    axis_dir = normalize(axis_vec)

    # Check connector lock
    if try_connect(sc, "", axis_dist):
        connected = True; break

    # Sub-phase
    if axis_dist > 20:
        step_size, speed, timeout = PHASE3_STEP_FAST, PHASE3_SPEED_FAST, 30
        phase = "FAST"
    elif axis_dist > 5:
        step_size, speed, timeout = PHASE3_STEP_SLOW, PHASE3_SPEED_SLOW, 20
        phase = "SLOW"
    else:
        step_size, speed, timeout = PHASE3_STEP_CREEP, PHASE3_SPEED_CREEP, 15
        phase = "CREEP"

    print(f"\n  [Step {step}] {phase} | dist={axis_dist:.1f}m")

    # Stuck detection
    if abs(axis_dist - prev_dist) < 0.3:
        stuck_count += 1
    else:
        stuck_count = 0
    prev_dist = axis_dist

    if stuck_count >= 5:
        print(f"  STUCK — trying connect() + big step")
        if try_connect(sc, "  ", axis_dist):
            connected = True; break
        step_size = max(2.5, axis_dist - DOCK_DISTANCE + 0.5)
        stuck_mode = True
    else:
        stuck_mode = False

    # Correct orientation
    sc_orient = (sc.telemetry or {}).get("orientation", {})
    sc_fwd = normalize(get_vec3(sc_orient.get("forward")) or (0,0,0))
    angle_err = math.acos(max(-1.0, min(1.0, dot(sc_fwd, axis_dir))))
    if angle_err > ALIGN_TOLERANCE:
        print(f"  Correcting: {math.degrees(angle_err):.1f}°")
        correct_orientation(rc, sc, gyros, axis_dir, timeout=5)
        for g in gyros: g.clear_override()
        time.sleep(0.3)

    # Move
    if stuck_mode:
        move_dist = step_size
    else:
        move_dist = min(step_size, max(0, axis_dist - DOCK_DISTANCE + 0.5))
    if move_dist < 0.1:
        if try_connect(sc, "  ", axis_dist):
            connected = True; break
        move_dist = 0.5; speed = 0.5

    ship_target = compute_ship_target(rc, sc, axis_dir, move_dist)
    if not ship_target:
        time.sleep(1); continue

    gps = f"GPS:D{step}:{ship_target[0]:.1f}:{ship_target[1]:.1f}:{ship_target[2]:.1f}:"
    rc.goto(gps, speed=speed, gps_name=f"D{step}")
    time.sleep(1)

    step_start = time.time()
    while time.time() - step_start < timeout:
        time.sleep(1)
        if check_connector(sc)[0]:
            print(f"  >> CONNECTED IN FLIGHT!")
            connected = True; break
        cur = get_pos(rc.telemetry or {})
        if cur:
            d = dist3(cur, ship_target)
            ap = (rc.telemetry or {}).get("autopilotEnabled", False)
            if d < 2.0 or (not ap and d < 5.0): break

    if connected: break

    rc.disable()
    rc.dampeners_on()
    time.sleep(0.3)

# =====================================================================
# FINAL
# =====================================================================
print("\n" + "=" * 60)
print("FINAL")
print("=" * 60)

rc.disable()
rc.dampeners_on()
for g in gyros: g.clear_override()
time.sleep(0.5)

sc_pos = get_pos(sc.telemetry or {})
tc_pos = get_pos(tc.telemetry or {})
is_conn, status, other_id = check_connector(sc)

if sc_pos and tc_pos:
    print(f"  Connector distance: {dist3(sc_pos, tc_pos):.1f}m")
print(f"  Connected: {is_conn}")
print(f"  Status: {status}")
print(f"  Other connector: {other_id}")

if is_conn:
    print("\n✅ DOCKING COMPLETE")
else:
    print("\n❌ DOCKING INCOMPLETE")

print("[DONE]")
