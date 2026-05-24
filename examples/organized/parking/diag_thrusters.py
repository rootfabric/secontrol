"""Quick diagnostic: check thruster state on skynet-baza0."""
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
from secontrol.devices.thruster_device import ThrusterDevice
from secontrol.devices.connector_device import ConnectorDevice

grid = prepare_grid("skynet-baza0")
time.sleep(1)

rc = grid.get_first_device(RemoteControlDevice)
thrusters = grid.find_devices_by_type(ThrusterDevice)

print(f"Grid: {grid.name}")
print(f"RC: {rc.device_id if rc else 'NONE'}")
print(f"Thrusters: {len(thrusters)}")

# Check if docked
conns = grid.find_devices_by_type(ConnectorDevice)
if conns:
    c = conns[0]
    c.update()
    print(f"Connector: isConnected={c.telemetry.get('connectorIsConnected')} status={c.telemetry.get('connectorStatus')}")

if not rc:
    print("NO RC - abort")
    sys.exit(1)

# Enable systems - try without autopilot
grid.park_off()
time.sleep(0.5)

# Don't enable autopilot - try manual control
rc.gyro_control_on()
rc.dampeners_off()
time.sleep(0.5)

print(f"\nRC telemetry keys: {list((rc.telemetry or {}).keys())[:10]}")
print(f"RC enable: {rc.telemetry.get('enabled', '?')}")

# Check thruster state with fresh update
grid.refresh_devices()
time.sleep(1)

thrusters = grid.find_devices_by_type(ThrusterDevice)
print(f"\nThruster telemetry samples (after refresh):")
for t in thrusters[:3]:
    tel = t.telemetry or {}
    print(f"  Thruster {t.device_id}: keys={list(tel.keys())[:15]}")
    for k in ['enabled', 'override', 'currentThrust', 'maxThrust']:
        print(f"    {k}={tel.get(k, '?')}")

# Try firing ALL thrusters
if thrusters:
    print(f"\n--- Test: fire ALL {len(thrusters)} thrusters at 0.5 ---")

    pos_before = rc.telemetry.get("worldPosition") or rc.telemetry.get("position")
    vel_before = rc.telemetry.get("linearVelocity") or {}

    print(f"Before: pos=({pos_before['x']:.1f}, {pos_before['y']:.1f}, {pos_before['z']:.1f}) vel=({vel_before.get('x',0):.2f}, {vel_before.get('y',0):.2f}, {vel_before.get('z',0):.2f})")

    for t in thrusters:
        t.set_thrust(enabled=True, override=0.5)

    time.sleep(2.0)

    pos_after = rc.telemetry.get("worldPosition") or rc.telemetry.get("position")
    vel_after = rc.telemetry.get("linearVelocity") or {}

    print(f"After:  pos=({pos_after['x']:.1f}, {pos_after['y']:.1f}, {pos_after['z']:.1f}) vel=({vel_after.get('x',0):.2f}, {vel_after.get('y',0):.2f}, {vel_after.get('z',0):.2f})")

    dx = float(pos_after['x']) - float(pos_before['x'])
    dy = float(pos_after['y']) - float(pos_before['y'])
    dz = float(pos_after['z']) - float(pos_before['z'])
    dvx = float(vel_after.get('x', 0)) - float(vel_before.get('x', 0))
    dvy = float(vel_after.get('y', 0)) - float(vel_before.get('y', 0))
    dvz = float(vel_after.get('z', 0)) - float(vel_before.get('z', 0))
    print(f"Delta: pos=({dx:.2f}, {dy:.2f}, {dz:.2f}) vel=({dvx:.2f}, {dvy:.2f}, {dvz:.2f})")
    speed_change = math.sqrt(dvx**2 + dvy**2 + dvz**2)
    print(f"Speed change: {speed_change:.3f} m/s")

    for t in thrusters:
        t.set_thrust(override=0.0)

rc.dampeners_on()

print("\n[DONE]")
grid.close()
