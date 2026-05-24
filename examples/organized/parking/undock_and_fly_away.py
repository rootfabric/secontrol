#!/usr/bin/env python3
"""
=== UNDOCK AND FLY AWAY ===

Отстыковывает корабль и плавно улетает от базы, сохраняя угол направления.

Точка отлёта: APPROACH_DIST метров вдоль forward вектора коннектора базы.
Корабль не меняет ориентацию — летит "как стоял", только в противоположную сторону.

Usage: python undock_and_fly_away.py [ship_id or name] [base_id or name] [distance]
  ship_id   — grid ID or name (default: first docked ship)
  base_id   — grid ID or name (default: first available base)
  distance  — meters along connector forward (default: 100)
"""
import sys, os, time, math

env_path = 'C:/secontrol/.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

sys.path.insert(0, "C:/secontrol/src")
from secontrol.common import prepare_grid, get_all_grids
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.connector_device import ConnectorDevice

SHIP = sys.argv[1] if len(sys.argv) > 1 else None
BASE = sys.argv[2] if len(sys.argv) > 2 else None
DISTANCE = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0

MAX_RATE = 0.3
GYRO_GAIN = 0.3
ALIGN_TOLERANCE = 0.1

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
    t = connector.telemetry or {}
    return (
        t.get("connectorIsConnected", False),
        t.get("connectorStatus", ""),
        t.get("otherConnectorId"),
    )

print("=" * 60)
print("UNDOCK AND FLY AWAY")
print("=" * 60)

# --- Find ship ---
if SHIP:
    ship_grid = prepare_grid(SHIP)
    time.sleep(1)
else:
    grids = get_all_grids()
    ship_grid = None
    for gid, gname in grids:
        g = prepare_grid(str(gid))
        time.sleep(0.5)
        conns = g.find_devices_by_type(ConnectorDevice)
        if conns:
            is_conn, status, _ = check_connector(conns[0])
            if is_conn:
                ship_grid = g
                break
    if not ship_grid:
        print("ERROR: no docked ship found"); sys.exit(1)

# --- Find base ---
if BASE:
    base_grid = prepare_grid(BASE)
    time.sleep(1)
else:
    grids = get_all_grids()
    base_grid = None
    for gid, gname in grids:
        if str(gid) == str(ship_grid.grid_id):
            continue
        g = prepare_grid(str(gid))
        time.sleep(0.5)
        conns = g.find_devices_by_type(ConnectorDevice)
        if conns:
            base_grid = g
            break
    if not base_grid:
        print("ERROR: no base found"); sys.exit(1)

rc = ship_grid.get_first_device(RemoteControlDevice)
sc = ship_grid.find_devices_by_type(ConnectorDevice)[0]
tc = base_grid.find_devices_by_type(ConnectorDevice)[0]

print(f"  Ship: {ship_grid.name} (ID: {ship_grid.grid_id})")
print(f"  Base: {base_grid.name} (ID: {base_grid.grid_id})")
print(f"  Ship connector: {sc.device_id}")
print(f"  Base connector: {tc.device_id}")

# --- Check docking ---
is_conn, status, other_id = check_connector(sc)
if not is_conn:
    print(f"  Ship is not connected (status={status}). Nothing to undock.")
    sys.exit(0)

print(f"\n[UNDOCK] Disconnecting...")
sc.disconnect()
time.sleep(2)
is_conn, status, _ = check_connector(sc)
print(f"  Status after disconnect: {status}")

# --- Calculate fly-away point ---
t_pos = get_pos(tc.telemetry or {})
t_orient = (tc.telemetry or {}).get("orientation", {})
t_fwd = normalize(get_vec3(t_orient.get("forward")) or (0,0,0))

if not t_pos:
    print("ERROR: cannot get target connector position"); sys.exit(1)

target_point = vec_add(t_pos, DISTANCE, t_fwd)
print(f"\n[FLY AWAY] Target point ({DISTANCE}m along forward):")
print(f"  Base connector: ({t_pos[0]:.1f}, {t_pos[1]:.1f}, {t_pos[2]:.1f})")
print(f"  Forward: ({t_fwd[0]:.3f}, {t_fwd[1]:.3f}, {t_fwd[2]:.3f})")
print(f"  Target: ({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})")

# --- Fly ---
rc.enable()
rc.thrusters_on()
rc.dampeners_on()
time.sleep(1)

gps = f"GPS:FlyAway:{target_point[0]:.1f}:{target_point[1]:.1f}:{target_point[2]:.1f}:"
print(f"\n[FLY] Sending to autopilot...")
rc.goto(gps, speed=10.0, gps_name="FlyAway")
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
time.sleep(0.5)

print("\n[DONE]")