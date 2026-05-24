"""Check thruster metadata for orientation info."""
import sys, os, time, json

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
from secontrol.devices.thruster_device import ThrusterDevice

grid = prepare_grid("skynet-baza0")
time.sleep(1)

thrusters = grid.find_devices_by_type(ThrusterDevice)
print(f"Thrusters: {len(thrusters)}")

for i, t in enumerate(thrusters[:5]):
    print(f"\n--- Thruster {i+1}: id={t.device_id} ---")
    print(f"  name={t.name}")
    print(f"  telemetry keys={list((t.telemetry or {}).keys())}")

    if hasattr(t, 'metadata') and t.metadata:
        print(f"  metadata fields: {[a for a in dir(t.metadata) if not a.startswith('_')]}")
        for field in ['device_id', 'name', 'type', 'subtype', 'block_type', 'extra']:
            if hasattr(t.metadata, field):
                val = getattr(t.metadata, field)
                if isinstance(val, dict):
                    print(f"  metadata.{field}=dict keys={list(val.keys())}")
                    if len(str(val)) < 500:
                        print(f"    value={val}")
                else:
                    print(f"  metadata.{field}={val}")

    t.update()
    tel = t.telemetry or {}
    if tel:
        print(f"  telemetry (after update): {json.dumps({k: str(v)[:80] for k, v in tel.items()})}")

grid.close()
