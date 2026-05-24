#!/usr/bin/env python3
"""
=== UNDOCK AND FLY AWAY (smooth, one script) ===

Отстыковывает корабль и плавно улетает от базы на заданное расстояние.

Usage:
  python fly_direction.py <grid> <base> [distance]

Пример:
  python fly_direction.py skynet-baza0 skynet-farpost0 50
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
from secontrol.common import prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.connector_device import ConnectorDevice

SHIP = sys.argv[1] if len(sys.argv) > 1 else None
BASE = sys.argv[2] if len(sys.argv) > 2 else None
DISTANCE = float(sys.argv[3]) if len(sys.argv) > 3 else 50.0
SPEED = 3.0

def dist3(a, b):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))

def normalize(v):
    l = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    return (v[0]/l, v[1]/l, v[2]/l) if l > 1e-10 else (0, 0, 0)

def get_vec3(data):
    if not data: return None
    return (float(data.get("x",0)), float(data.get("y",0)), float(data.get("z",0)))

def get_pos(telemetry):
    d = telemetry.get("worldPosition") or telemetry.get("position") or telemetry.get("pos")
    if not d: return None
    return (float(d["x"]), float(d["y"]), float(d["z"]))

def vec_add(a, s, v):
    return (a[0]+s*v[0], a[1]+s*v[1], a[2]+s*v[2])

if not SHIP:
    print("Usage: python fly_direction.py <ship> <base> [distance]")
    sys.exit(1)

print("=" * 60)
print("UNDOCK AND FLY AWAY")
print("=" * 60)

print(f"\n[LOAD] Loading grids...")
ship_grid = prepare_grid(SHIP)
time.sleep(1)

rc = ship_grid.get_first_device(RemoteControlDevice)
sc = ship_grid.find_devices_by_type(ConnectorDevice)[0]

if not rc:
    print("ERROR: no RemoteControl"); sys.exit(1)

# Find base if not specified
if BASE:
    base_grid = prepare_grid(BASE)
    time.sleep(1)
else:
    from secontrol.common import get_all_grids
    grids = get_all_grids()
    base_grid = None
    for gid, gname in grids:
        if str(gid) == str(ship_grid.grid_id): continue
        g = prepare_grid(str(gid))
        time.sleep(0.5)
        if g.find_devices_by_type(ConnectorDevice):
            base_grid = g; break
    if not base_grid:
        print("ERROR: no base found"); sys.exit(1)

tc = base_grid.find_devices_by_type(ConnectorDevice)[0]

print(f"  Ship: {ship_grid.name}")
print(f"  Base: {base_grid.name}")
print(f"  Target distance: {DISTANCE:.0f}m")

# --- Calculate target ---
t_pos = get_pos(tc.telemetry or {})
t_orient = (tc.telemetry or {}).get("orientation", {})
t_fwd = normalize(get_vec3(t_orient.get("forward")) or (0,0,0))

if not t_pos:
    print("ERROR: no target position"); sys.exit(1)

target_point = vec_add(t_pos, DISTANCE, t_fwd)
print(f"\n[TRG] Target: ({target_point[0]:.1f}, {target_point[1]:.1f}, {target_point[2]:.1f})")

# --- Undock ---
ship_grid.park_off()
rc.enable(); rc.gyro_control_on(); rc.thrusters_on(); rc.dampeners_on()
time.sleep(0.5)

sc.update()
is_docked = (sc.telemetry or {}).get("connectorIsConnected", False)
if is_docked:
    print(f"\n[UNDOCK] Disconnecting...")
    sc.disconnect()
    time.sleep(2)
    sc.update()
    status = (sc.telemetry or {}).get("connectorStatus", "")
    print(f"  Status: {status}")
    if (sc.telemetry or {}).get("connectorIsConnected"):
        print("  Retry..."); sc.disconnect(); time.sleep(1)
    if not (sc.telemetry or {}).get("connectorIsConnected"):
        print("  Disabling magnet...")
        sc.set_state(enabled=False)
    print(f"  Done")
else:
    print(f"\n[UNDOCK] Already free")

# --- Fly (autopilot handles rotation + flight together) ---
gps = f"GPS:away:{target_point[0]:.1f}:{target_point[1]:.1f}:{target_point[2]:.1f}:"
print(f"\n[FLY] Departing {DISTANCE:.0f}m at {SPEED:.0f} m/s...")
rc.set_mode("oneway")
rc.set_collision_avoidance(False)
rc.goto(gps, speed=SPEED, gps_name="away")
time.sleep(1)

start = time.time()
start_pos = get_pos(rc.telemetry or {})
while time.time() - start < 300:
    time.sleep(3)
    cur = get_pos(rc.telemetry or {})
    if not cur: continue

    d = dist3(cur, target_point)
    travelled = dist3(start_pos, cur) if start_pos else 0
    ap = (rc.telemetry or {}).get("autopilotEnabled", False)
    speed = float((rc.telemetry or {}).get("speed", 0))

    print(f"  [{time.time()-start:.0f}s] to_target={d:.1f}m  travelled={travelled:.1f}m  speed={speed:.1f}")

    if d < 5.0: break
    if not ap and d < 20.0: break
    if not ap and time.time() - start > 20: break

rc.disable()
rc.dampeners_on()
time.sleep(0.5)

print(f"\n[DONE]")

ship_grid.close()
base_grid.close()
