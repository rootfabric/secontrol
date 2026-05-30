---
name: game-server-automation
description: "Automate Space Engineers and other game servers via Redis pub/sub gateways. Focus on secontrol Python SDK for Space Engineers."
version: 1.0.0
tags: [space-engineers, redis, game-server, secontrol, telemetry, automation, pubsub]
platforms: [linux]
---

# Game Server Automation via Redis

Automate game servers that expose telemetry and control via a Redis pub/sub gateway.

## When to use

- User wants to control a Space Engineers server programmatically
- User asks about drones, robots, ship automation in Space Engineers
- User needs to query grids, devices, inventory, radar in Space Engineers
- User asks about game server telemetry / control APIs

## Key Concept

Many game servers (notably **Space Engineers** by Keen Software House) run a Redis gateway alongside the game. The gateway:
- **Publishes** telemetry (grid state, device data, damage events, inventory) to Redis channels
- **Subscribes** to command channels — you publish commands there and the server executes them

```
Space Engineers game server
        │
        │ Redis pub/sub
        ▼
secontrol (Python SDK)   ← you write code here
        │
        ├── Read: grid state, device telemetry, radar, inventory
        └── Write: commands (move, fire, weld, refuel, etc.)
```

## secontrol Quick Reference

**Package:** `pip install secontrol` (or `pip install -e .` from workspace)

**Required env vars** (from https://www.outenemy.ru/se/):
```
REDIS_USERNAME=<owner_id>
REDIS_PASSWORD=<auth_password>
REDIS_URL=redis://<host>:6379/0
```

**Core API:**
```python
from secontrol.common import prepare_grid, get_all_grids, close

# List all available grids
grids = get_all_grids()  # returns list of (grid_id, grid_name)

# Connect to a grid by name or ID
grid = prepare_grid("MyShip")       # by name (search)
grid = prepare_grid("1234567890")   # by ID

# Devices on the grid
for device_id, device in grid.devices.items():
    print(f"  {device.name or device_id}: {device.device_type}")

# Send a command
grid.send_grid_command("wake")

# Close
close(grid)
```

**Key classes:**
- `Grid` — one ship/station; has `.devices`, `.blocks`, `.send_grid_command()`
- `BaseDevice` — base for all blocks; `.name`, `.device_type`, `.custom_name`
- Specific devices: `LampDevice`, `ThrusterDevice`, `WeaponDevice`, `BatteryDevice`, `RadarController`, `AIDevice`, etc.
- `Grids` — monitors all grids for an owner
- `InventorySnapshot` — typed inventory state

## Check Available Grids

```python
from secontrol.common import get_all_grids, resolve_owner_id

owner = resolve_owner_id()
print(f"Owner ID: {owner}")
grids = get_all_grids()
for gid, gname in grids:
    print(f"  {gid}  {gname}")
```

## Device Pattern

```python
grid = prepare_grid("MyGrid")
for did, dev in grid.devices.items():
    print(f"{dev.name or did}: {dev.device_type}")
    # Each device has type-specific properties
    if dev.device_type == "lamp":
        print(f"  On: {dev.get_custom_property('Enabled')}")
```

## Event Subscriptions

```python
grid.on("devices", lambda g, event, src: print(f"Devices changed: {event}"))
grid.on("damage",  lambda g, event, src: print(f"Damage: {event}"))
grid.on("integrity", lambda g, event, src: print(f"Integrity: {event}"))
```

## Gotcha: execute_code sandbox vs subprocess

The `execute_code` sandbox (`/tmp/hermes_sandbox_*/script.py`) does NOT have project dependencies installed. `import redis` will fail there even if it's installed on the host.

**Solution:** Use subprocess to invoke system Python:
```python
import subprocess, sys, os
os.environ['REDIS_USERNAME'] = '...'
os.environ['REDIS_PASSWORD'] = '...'
os.environ['REDIS_URL'] = 'redis://192.168.0.15:6379/0'

result = subprocess.run(
    [sys.executable, '-c', '''
import sys
sys.path.insert(0, '/workspace/src')
# now import secontrol normally
from secontrol.common import get_all_grids
grids = get_all_grids()
for g in grids: print(g)
'''],
    capture_output=True, text=True, timeout=20
)
print(result.stdout)
```

> See `references/secontrol-grids.md` for session transcript with verified grid data.

## Parking / Docking System

Space Engineers servers often run a separate **parking subsystem** (found at `<workspace>/parking/` on the game server). This handles automatic docking/station-keeping:
- `parking/<name>.py` — main entry (example pattern)
- `parking/<name>.py` — docking logic (example pattern)
- `parking/<name>.py` — final approach (example pattern)
- `parking/<name>.py` — point calculation (example pattern)
- `parking/<name>.py` — utilities (example pattern)

> Actual parking scripts in this repo: `examples/organized/parking/` (see `final_park.py`, `dock.py`, etc.)

## Known Grids (this installation)

Currently accessible grids (from Redis at `192.168.0.15:6379`):
- `134540402238780591` — DroneBase 2
- `138748817302648345` — DroneBase
- `74055729860857332` — taburet3
- `82069157247683112` — Respawn Rover
- `98945391841930411` — taburet2

> See `references/secontrol-grids.md` for verified grid data from this installation (IDs, names, connection details).

## Support Files

- `references/secontrol-grids.md` — session transcript: verified grid IDs/names, Redis connection info, subprocess query technique

## Further Reading

- [secontrol wiki](https://github.com/rootfabric/secontrol/wiki/home)
- [secontrol ARCHITECTURE.md](ARCHITECTURE.md)
- [secontrol AGENTS.md](AGENTS.md)
- `examples/organized/` — 113+ usage examples organized by device type and complexity
