---
name: secontrol-space-engineers
description: >
  Use the secontrol Python library to interact with Space Engineers servers via Redis.
  Query grids, inspect devices, read inventories, load blueprints, control production.
  Covers grid discovery, device enumeration, inventory analysis, projector/blueprint workflows,
  and construction planning for base development.
version: 1.0.0
metadata:
  hermes:
    tags: [gaming, space-engineers, redis, secontrol, automation, drones]
    related_skills: [game-server-automation]
---

# secontrol — Space Engineers Python SDK

Use when the user asks about Space Engineers grids, devices, inventories, blueprints, drones, or base automation.

## Project location

Typical path: `/workspace/src/secontrol/` (adjust per repo). Check `AGENTS.md` and `ARCHITECTURE.md` first.

**⚠️ `execute_code` sandbox does NOT have `secontrol` installed.** Always run secontrol scripts via `terminal`, not `execute_code`.

## Documentation (docs/)

The project has comprehensive docs. Read these before writing new code:

| File | Purpose |
|---|
| `AGENTS.md` | Quick-start, commands, source layout |
| `ARCHITECTURE.md` | Module map, dependency diagram |
| `docs/API_REFERENCE.md` | Full public API — Grid, BaseDevice, RedisEventClient, etc. |
| `docs/DEVICE_REFERENCE.md` | All 26 device classes with methods |
| `docs/EXAMPLES.md` | **141 examples catalog** — 22 categories, basic/intermediate/advanced |
| `docs/WORKFLOWS.md` | Common patterns and recipes |
| `docs/design-docs/index.md` | Design decisions log |
| `docs/exec-plans/tech-debt-tracker.md` | Known technical debt |
| `CHANGELOG.md` | Version history |

## Environment setup

Requires `.env` with `REDIS_USERNAME`, `REDIS_PASSWORD`, `REDIS_URL`. Install deps:

```python
import subprocess, sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'redis', 'python-dotenv'], timeout=30)
```

When running secontrol from `execute_code` sandbox, add `sys.path.insert(0, '/workspace/src')` **and** set env vars explicitly in `os.environ` (the sandbox doesn't auto-load `.env`).

## Core API quick reference

```python
from secontrol.common import get_all_grids, prepare_grid, resolve_owner_id
import time

# List all grids
grids = get_all_grids()  # list of (grid_id, grid_name)

# Connect (ALWAYS pass STRING, never int!)
grid = prepare_grid('GridName_or_GridID')  # by name or ID, auto-wakes

# Enumerate devices (type names are lowercase singular)
for dev in grid.find_enabled_devices():
    print(f"  {dev.device_type}: {dev.name or 'unnamed'} (id={dev.device_id})")

# Find by type
projectors = grid.find_devices_by_type("projector")
welder = grid.get_device_any("welder")  # fuzzy find by name

# Inspect all blocks
for block_id, block in sorted(grid.blocks.items(), key=lambda x: x[1].block_type or ''):
    functional = "✓" if block.state.get('functional') else "✗"
    enabled = "ON" if block.state.get('enabled') else "OFF"
    print(f"  [{block.block_type}] '{block.subtype}' | {functional} {enabled}")

# Find specific block by type
for bid, block in grid.blocks.items():
    if block.block_type == 'MyObjectBuilder_Refinery':
        print(f"  {block.name}: pos={block.local_position}")

# Block coordinates: local_position is in METERS (large grid: 1 block = 2.5m)
block_pos = tuple(round(v / 2.5) for v in block.local_position)

# Grid commands
grid.send_grid_command('wake')    # activate telemetry
grid.park_on() / grid.park_off()  # parking mode

# Device control
dev.enable() / dev.disable()      # toggle on/off
dev.toggle_enabled()              # flip state
```

**Device type name quirks**: `ShipWelderDevice` → `ship_welder`. Survival Kit → `survivalkit`. Solar → `solarpanel`. Ore detector → `ore_detector`.

**Block attributes**: `block.block_id` (NOT `block.id`), `block.block_type` (NOT `block.type`), `block.subtype`, `block.local_position`, `block.bounding_box`, `block.state`, `block.is_damaged`.

→ **Full API patterns + code examples**: [references/core-api-patterns.md](references/core-api-patterns.md)
→ **Russian → English block name mapping**: [references/core-api-patterns.md](references/core-api-patterns.md) (section "Соответствие русских и английских названий")

## Inventory quick reference

```python
# Container inventory (items are objects with attributes)
for dev in grid.find_devices_containers():
    for inv in dev.inventories():
        if inv.items:
            for item in inv.items:
                print(f'  {item.display_name}: {item.amount}')

# Refinery/assembler inventory (items are plain dicts with string keys!)
t = refinery.telemetry or {}
for item in t.get('inputInventory', {}).get('items', []):
    print(f'  {item["displayName"]}: {item["amount"]}')
```

→ **Full inventory patterns + pitfalls**: [references/inventory-patterns.md](references/inventory-patterns.md)

## Blueprint & Projection quick reference

```python
# Projector lookup
proj = next(d for d in grid.devices.values() if d.device_type == 'projector')

# Load prefab / export blueprint
proj.load_prefab('LargeAssembler')
proj.request_grid_blueprint(include_connected=False); time.sleep(5)
bp = proj.blueprint_snapshot()  # dict with keys: xml, gridName, gridCount, ok
xml = bp['xml']

# Load custom XML
proj.load_blueprint_xml(xml, keep=False)

# Check projection status
proj.remaining_blocks()   # blocks left to build
proj.total_blocks         # total in projection (from telemetry)
proj.is_enabled           # projection active?
```

**Critical: Blueprint XML must be stripped to minimal form before loading.** ComponentContainer data inflates XML (41KB → 786KB), causing `remainingBlocks == totalBlocks` for all offsets. Strip non-essential tags.

**Critical: `set_offset()` / `set_rotation()` are RELATIVE (DELTA) commands.** `set_offset(0,0,0)` = "don't move", NOT "set to origin".

**Critical: `set_offset()` / `set_rotation()` do NOT affect projection after `load_blueprint_xml()`.** Embed values in XML projector block before loading.

**Adding a new block to existing grid**: export → strip → insert block XML into `<CubeBlocks>` → embed offset/rotation → load → verify `remainingBlocks` → weld.

→ **Full projection alignment + brute-force workflow**: [references/projection-alignment.md](references/projection-alignment.md)
→ **Blueprint editing + XML templates**: [references/blueprint-editing.md](references/blueprint-editing.md)

## Navigation & Flight quick reference

**RemoteControlDevice** (`remote_control`):
- `rc.enable()` → enables **autopilot** (NOT the block itself!)
- `rc.set_enabled(True)` → enables the **block** (on/off). May not persist for RC/Cockpit/Conveyors.
- `rc.goto(gps, speed=N, dock=True/False)` → fly to GPS point. Returns immediately; autopilot engages async.
- `rc.gyro_control_on()` / `rc.thrusters_on()` / `rc.dampeners_on()` — REQUIRED before autopilot works
- `rc.set_collision_avoidance(True/False)` — SE's built-in voxel avoidance
- `rc.set_mode("oneway")` / `"patrol"` / `"circle"` — flight mode

**GyroDevice** (`gyro`):
- `gyro.set_override(pitch=0.0, yaw=0.0, roll=0.0)` — keyword-only, values -1.0 to 1.0
- `gyro.aim_vector({"x": dx, "y": dy, "z": dz})` — aim ship's forward at world vector

**ThrusterDevice** (`thruster`):
- `thruster.set_thrust(override=0.5)` — keyword-only, 0.0 to 1.0
- NO `set_override()` method — use `set_thrust(override=N)`

**ConnectorDevice** (`connector`):
- `conn.connect()` / `conn.disconnect()` — explicit lock/unlock
- Telemetry: `connectorStatus`, `connectorIsConnected`, `nearbyConnectors`, `otherConnectorId`

```python
# Quick fly to GPS
rc = grid.get_first_device(RemoteControlDevice)
rc.enable(); rc.gyro_control_on(); rc.thrusters_on(); rc.dampeners_on()
time.sleep(1)
rc.set_mode("oneway"); rc.set_collision_avoidance(False)
rc.goto("GPS:Target:123.45:678.90:0.00:", speed=10.0, gps_name="Target")
```

**⚠️ RC enable sequence is REQUIRED.** Without `gyro_control_on()` + `thrusters_on()` before `goto()`, the autopilot engages but the ship doesn't move.

**⚠️ Thrusters REQUIRE a pilot or RemoteControl.** `cockpit.telemetry.get('hasPilot')` must be `True`, or a `RemoteControlDevice` must exist on the grid.

→ **Full navigation API**: [references/navigation-and-flight.md](references/navigation-and-flight.md)
→ **Manual flight controller (gyro+thruster, no RC)**: [references/manual-flight-controller.md](references/manual-flight-controller.md)
→ **Asteroid flight pattern**: [references/asteroid-flight-pattern.md](references/asteroid-flight-pattern.md)
→ **Space docking**: [references/space-docking.md](references/space-docking.md)

## Ore Detector & Radar quick reference

```python
# Asteroid scanning (via send_command — OreDetectorDevice has no dedicated method)
from secontrol.devices.ore_detector_device import OreDetectorDevice
radar = grid.get_first_device(OreDetectorDevice)
radar.send_command({
    "cmd": "asteroids",
    "targetId": int(radar.device_id),
    "state": {"radius": 50000.0, "limit": 320, "includePlanets": False},
})
# Poll telemetry for asteroidIndex with ready=True

# RadarController ore-only scan (v0.3.1+)
from secontrol.controllers.radar_controller import RadarController
ore_ctrl = RadarController(radar, ore_only=True, radius=1000, cell_size=10, boundingBoxY=1000)
solid, meta, contacts, ore_cells = ore_ctrl.scan_voxels()

# Ore deposit scanning (ready-to-use script)
# python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 1000
# python examples/organized/radar/ore_deposit_scanner.py --find Gold
```

**⚠️ ALWAYS use `ore_only=True` for ore scanning.** Without it, Stone fills the 256-cell buffer.

**Ore Detector telemetry keys**: `scan.includePlayers`, `scan.includeGrids`, `scan.includeVoxels`, `players`, `detectedgrids`, `detectedores`, `gravityVector`.

**`asteroidIndex` is auto-populated** in ore detector telemetry — no explicit command needed. `surfaceDistance=0` means the grid IS on the asteroid.

→ **Full asteroid scanning**: [references/asteroid-scanning.md](references/asteroid-scanning.md)
→ **Voxel distance diagnostics**: [references/voxel-distance-diagnostics.md](references/voxel-distance-diagnostics.md)

## Monitoring pipeline quick reference

```
se_player_scan.py    (cron: every 5m, no_agent=True)
  └─→ scans all grids via OreDetector telemetry
       ├─ writes `logs/scan_YYYY-MM-DD.jsonl` (runtime path)
       ├─ writes `logs/active_alert.json` (runtime path)
       └─ reads OWN_GRID_IDS to classify detected grids as foreign

se_alert_watcher.py  (cron: every 1m, no_agent=True)
  └─→ reads active_alert.json → spawns se_alert_agent.py if threats present

se_alert_agent.py    (runs on-demand, WITH agent)
  └─→ assess_risk(), gather grid positions, write journal.jsonl
```

**Required env bootstrap** (cron scripts don't auto-load `.env`):
```python
import os, sys
WORKSPACE = "/workspace"
sys.path.insert(0, os.path.join(WORKSPACE, "src"))
dotenv_path = os.path.join(WORKSPACE, ".env")
if os.path.exists(dotenv_path):
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
```

→ **Full monitoring pipeline**: [references/monitoring-pipeline.md](references/monitoring-pipeline.md)

## Base readiness & Construction

**Base readiness checklist** (cross-reference against found blocks):

| Module | Required blocks | Critical? |
|--------|----------------|-----------|
| Respawning | SurvivalKit or MedicalRoom | 🔴 YES |
| Power | SolarPanel, Battery, Reactor, HydrogenEngine | 🔴 YES |
| Mining | NanobotDrillSystem or ShipDrill + OreDetector | 🟡 needed for resources |
| Refining | Refinery or SurvivalKit | 🟡 needed for ingots |
| Assembly | Assembler or SurvivalKit | 🟡 needed for components |
| Construction | Projector + ShipWelder/BARS | 🟢 for expansion |
| Life support | OxygenGenerator + OxygenTank/HydrogenTank | 🟡 planet-dependent |
| Storage | CargoContainer (must be ON) | 🟡 conveyor network depends on it |

**Safe welding sequence**:
1. Disable welder first
2. Take block snapshot (record all block IDs, types, positions)
3. Load blueprint with VERIFIED alignment
4. Verify `remainingBlocks` — must equal expected count
5. Enable welder → monitor → disable welder
6. Compare blocks against snapshot

**Disassembly mode** (Nanobot BARS): paint blocks with disassembly color → configure grind color in CustomData → enable welder. **BARS telemetry does NOT expose grind state** — all grind configuration must happen in-game.

→ **Construction planning details**: [references/construction-planning.md](references/construction-planning.md)

## Nanobot Drill quick reference

**Area reach formula**: `Max reach from block = (area_size / 2) + |offset|`

| Config | Area | Offset | Max reach from block |
|--------|------|--------|---------------------|
| Default | 75×75×75m | 0 | ~37.5m |
| Planet harvest | 75×75×75m | +50 (down) | ~87.5m |
| Extended | 250×250×250m | ±100 | ~225m |

**Key parameters**:
| Property | Methods | Default |
|----------|---------|---------|
| `Drill.AreaWidth` | `increase_area_width()` / `decrease_area_width()` | ~75m |
| `Drill.AreaOffsetUpDown` | `increase_area_offset_up_down()` / `decrease_area_offset_up_down()` | 0 |

All can be set via `drill.set_property("AreaOffsetUpDown", 50.0)`.

**Mining workflow** (space, asteroid ore):
1. Navigate to ore deposit (RC goto, disable at <40m)
2. Compute drill area offset (project ore→drill vector onto ship axes)
3. Configure drill: `set_property("AreaOffsetUpDown/LeftRight/FrontBack", value)`
4. Start mining: `set_property("ScriptControlled", False)` → `turn_on()` → `start_drilling()`
5. Monitor: `telemetry['drill_possibledrilltargets']`, `Drill.CurrentDrillTarget`

**⚠️ `ScriptControlled=True` prevents auto-mining.** Always set `False` for automatic ore mining.
**⚠️ `start_drilling()` is REQUIRED.** `turn_on()` alone is NOT sufficient.

**Diagnosis checklist** (when drill isn't collecting):
1. Check `ScriptControlled` — must be `False`
2. Check `WorkMode` — must be 2 (Drill). `set_work_mode()` has swapped values, use raw `send_command`
3. Check `PossibleDrillTargets` — if empty, no voxels in area
4. Check `start_drilling()` was called
5. Offset drill area along gravity vector

**Iron from stone**: Stone voxels contain iron. No special filter needed — just ensure drill is on surface and in Drill mode (WorkMode=2).

→ **Full drill mining workflow**: [references/nanobot-drill-mining-workflow.md](references/nanobot-drill-mining-workflow.md)
→ **Drill debugging**: [references/nanobot-drill-debugging.md](references/nanobot-drill-debugging.md)
→ **Drill quickstart**: [references/nanobot-drill-quickstart.md](references/nanobot-drill-quickstart.md)

## Top pitfalls (summary)

1. **`prepare_grid()` REQUIRES STRING arg** — passing int treats it as `existing_client`, resolves wrong grid
2. **`rc.enable()` enables AUTOPILOT, NOT the block** — use `rc.set_enabled(True)` for block power
3. **Projection alignment is per-grid brute-force** — NEVER guess offset values, wrong alignment corrupts base
4. **Welder MUST be disabled before loading projections** — BARS starts welding immediately
5. **`set_offset()`/`set_rotation()` are DELTA commands** — `set_offset(0,0,0)` = "don't move"
6. **Blueprint XML bloat breaks alignment** — always strip ComponentContainer before loading
7. **`ScriptControlled=True` prevents auto-mining** — always set `False` for automatic ore mining
8. **`start_drilling()` is REQUIRED** — `turn_on()` alone doesn't start mining
9. **`dev.telemetry` can be `None`** — ALWAYS guard: `t = dev.telemetry or {}` before `t.get(...)`
10. **Not all blocks can be enabled via API** — MergeBlock, CargoContainer, Cockpit, Conveyors require in-game terminal

→ **Full pitfalls reference (108 entries)**: [references/pitfalls.md](references/pitfalls.md)
