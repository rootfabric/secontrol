[← Parent skill: secontrol-space-engineers](../SKILL.md)

# Nanobot Drill System — Debugging Reference

> **See also**: `nanobot-drill-mining-workflow.md` for the complete mining workflow (navigate → configure → mine).

## Critical: ScriptControlled setting

| ScriptControlled | Behavior |
|---|---|
| `True` | Drill reports targets but `CurrentDrillTarget` stays `None` — NO auto-mining |
| `False` | Drill auto-selects and mines targets — ore accumulates |

**Always set `ScriptControlled=False` for mining.** Without this, `turn_on()` + `start_drilling()` will show targets but never mine them.

## Critical: start_drilling() required

`turn_on()` alone powers the drill but does NOT start mining. You MUST call:
```python
drill.set_property("ScriptControlled", False)
drill.turn_on()
drill.start_drilling()  # ← REQUIRED
```

## Work Mode Bug (v0.3.0)

`set_work_mode()` in `NanobotDrillSystemDevice` has **swapped drill/collect values**:

```python
# WRONG (in set_work_mode):
mode_map = {"drill": 1, "collect": 2, "fill": 0}

# CORRECT (in get_work_mode):
mode_map = {0: "Fill", 1: "Collect", 2: "Drill"}
```

**Fix:** Use raw command:
```python
drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})
# 0 = Fill, 1 = Collect, 2 = Drill
```

## Telemetry keys to check

| Key | Meaning |
|---|---|
| `drill_workmode` | 0=Fill, 1=Collect, 2=Drill |
| `drill_possibledrilltargets` | List of detected voxel targets (empty = nothing in area) |
| `drill_currentdrilltarget` | Currently targeted voxel |
| `drill_areaoffsetupdown` | Vertical offset (negative = down) |
| `drill_areawidth/height/depth` | Area dimensions (default 25m each) |
| `drill_scriptcontrolled` | If True, mod waits for external commands |
| `drill_componentclasslist` | `['1;False', '2;True', ...]` — class 1 may be stone/gravel |
| `drill_drillprioritylist` | `['1137917536;True', ...]` — ore hashes with enabled flag |
| `terrainclearingmode` | Terrain clearing mode |

## Ore Hashes (FNV-1a 32-bit)

| Ore | Hash |
|---|---|
| stone | 1137917536 |
| ice | 1579040667 |
| iron | 2112235764 |
| nickel | -723128632 |
| silicon | -122448462 |
| cobalt | -2115209756 |
| magnesium | 2104309205 |
| silver | 1033257407 |
| gold | -496794321 |
| platinum | -510410391 |
| uranium | 1880922462 |

## Diagnostic script

```python
import sys, os, time
sys.path.insert(0, '/workspace/src')
os.environ['REDIS_USERNAME'] = '...'
os.environ['REDIS_PASSWORD'] = '...'

from secontrol.common import prepare_grid
import math

grid = prepare_grid('GRID_NAME')
drill = next((d for d in grid.devices.values() if d.device_type == 'nanobot_drill_system'), None)
rc = next((d for d in grid.devices.values() if d.device_type == 'remote_control'), None)

# 1. Check altitude
if rc:
    t = rc.telemetry
    pos, planet = t['position'], t['planetPosition']
    dist = math.sqrt(sum((pos[k] - planet[i])**2 for i, k in enumerate(['x','y','z'])))
    print(f"Altitude: {dist - 30000:.0f}m (negative = below surface)")

# 2. Check drill state
telemetry = drill.telemetry or {}
print(f"WorkMode: {telemetry.get('drill_workmode')} (0=Fill,1=Collect,2=Drill)")
print(f"Enabled: {drill.is_enabled()}")
print(f"ScriptControlled: {telemetry.get('drill_scriptcontrolled')}")
print(f"TerrainClearing: {telemetry.get('terrainclearingmode')}")
print(f"PossibleDrillTargets: {telemetry.get('drill_possibledrilltargets')}")
print(f"Area: {telemetry.get('drill_areawidth')}x{telemetry.get('drill_areaheight')}x{telemetry.get('drill_areadepth')}")
print(f"AreaOffsetUpDown: {telemetry.get('drill_areaoffsetupdown')}")

# 3. Check ore filters
print(f"Ore filters: {drill.debug_get_enabled_known_ores()}")

# 4. Check component classes
print(f"ComponentClassList: {telemetry.get('drill_componentclasslist')}")
```

## PossibleDrillTargets empty — troubleshooting steps

1. Verify drone altitude (must be ≤ 0 for surface contact)
2. Ensure WorkMode = 2 (Drill) — use raw `send_command`, NOT `set_work_mode()`
3. Set `ScriptControlled = False` (let mod auto-detect)
4. Try `set_terrain_clearing_mode(True)`
5. **Project gravity vector onto ship axes** to calculate area offset (see below)
6. If still empty after offset, try `increase_area_width()` etc. to expand area
7. If still empty, the grid may genuinely not be near any voxels

## Area offset via gravity vector projection

When PossibleDrillTargets is empty, the drill area (25×25×25m, ship-centered) may not
intersect the voxel surface. The solution is to offset the area along the gravity vector.

### Step 1: Get gravity and orientation from RemoteControl

```python
rc = next(d for d in grid.devices.values() if d.device_type == 'remote_control')
t = rc.telemetry

# Gravity vector in world coordinates
grav = t.get('gravitationalVector', {})
gx, gy, gz = grav['x'], grav['y'], grav['z']
g_mag = math.sqrt(gx**2 + gy**2 + gz**2)  # ~8.83 for Mars

# Ship orientation vectors (world coords)
orient = t.get('orientation', {})
fwd = orient['forward']   # ship's forward in world
up  = orient['up']        # ship's up in world
left = orient['left']     # ship's left in world
```

### Step 2: Project gravity onto ship-local axes

```python
# Dot products: how much gravity component aligns with each ship axis
g_up   = gx*up['x']   + gy*up['y']   + gz*up['z']    # typically NEGATIVE (gravity pulls down)
g_left = gx*left['x'] + gy*left['y'] + gz['left']['z']
g_fwd  = gx*fwd['x']  + gy*fwd['y']  + gz*fwd['z']

print(f"Gravity on Up axis:   {g_up:.3f}")   # e.g. -8.0 (down)
print(f"Gravity on Left axis: {g_left:.3f}") # near 0 if level
print(f"Gravity on Fwd axis:  {g_fwd:.3f}")  # near 0 if level
```

### Step 3: Set area offsets

```python
# AreaOffsetUpDown: POSITIVE = ship "up" direction
# Gravity on Up axis is NEGATIVE, so to move area toward ground:
drill.set_property("AreaOffsetUpDown", -g_up * 5)      # e.g. -(-8.0)*5 = +40.0

# Or use the action method repeatedly:
for _ in range(10):
    drill.increase_area_offset_up_down()

# Same logic for other axes if drone is on a slope
drill.set_property("AreaOffsetLeftRight", -g_left * 5)
drill.set_property("AreaOffsetFrontBack", -g_fwd * 5)
```

### Step 4: Verify and iterate

```python
time.sleep(3)  # wait for mod to recalculate
telemetry = drill.telemetry or {}
targets = telemetry.get('drill_possibledrilltargets', [])
print(f"Found {len(targets)} drill targets")
if targets:
    for t in targets:
        print(f"  Rock: min={t['min']}, max={t['max']}, dist={t.get('distance', '?')}")
```

### Example from real session (Mars, DroneBase taburet3)

```
Gravity magnitude: 8.829
Gravity on Up axis: -8.0 (approx)
Set AreaOffsetUpDown = +44 → found 8 MarsRocks at 30-59m distance
```

## Stone mining for resources

Stone voxels are valid targets for the Nanobot Drill. They yield:
- Iron Ore (primary)
- Nickel Ore, Silicon Ore, Cobalt Ore, Magnesium Ore (trace)

No special ore filter needed — stone (hash 1137917536) is index 0 in the priority list
and enabled by default. The drill just needs to be on the surface in Drill mode.

## Space drilling (asteroids, no gravity)

When the grid is in space (gravity=0) on an asteroid surface:

### Drill area is larger than documented

The Nanobot Drill System (large grid) uses a **75×75×75m** area by default (not 25×25×25m
as with planetary drills). This means the drill area extends significantly from the block.

### Enabling the drill

The drill starts **disabled** (`enabled=False`). It cannot be enabled via `send_command`
with `"cmd": "property"` or `"cmd": "set"`. The working method is:

```python
drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": True}})
```

Verified: `toggle` also works but flips state unpredictably. `set OnOff True` is explicit.

**The drill auto-disables periodically** — likely when power is insufficient or when no
targets are found for extended periods. Re-enable with the same command.

### Finding drill targets in space

When `drill_possibledrilltargets` is empty despite the grid being on an asteroid:

1. **Enable the drill first** — targets only appear when `enabled=True, isWorking=True`
2. **Wait 2-3 seconds** — the mod needs time to scan the area
3. **Targets appear as `SmallMoonRocks`** — these are stone voxels on the asteroid surface
4. **Target format**: `['MyVoxelMap {hash} Id=N MyObjectBuilder_VoxelMaterialDefinition/SmallMoonRocks=X.XXXX (Dist=XX.X, Min=[X:N, Y:N, Z:N], Max=[X:N, Y:N, Z:N])', 'MyVoxelMap {hash}', distance, 'SmallMoonRocks', content_value]`

### Area offset in space

In space (no gravity), there's no gravity vector to project. The drill area is centered on
the block. If targets are empty:

1. Try `AreaOffsetUpDown` sweep from -50 to +50 in steps of 10
2. Try `AreaOffsetFrontBack` and `AreaOffsetLeftRight` similarly
3. If still empty, increase area size: `Drill.AreaWidth/Height/Depth` to 100-250m

```python
# Sweep offsets
for axis in ['AreaOffsetUpDown', 'AreaOffsetFrontBack', 'AreaOffsetLeftRight']:
    for offset in range(-50, 55, 10):
        drill.send_command({"cmd": "set", "payload": {"property": f"Drill.{axis}", "value": float(offset)}})
        time.sleep(0.5)
        drill.update()
        targets = drill.telemetry.get('drill_possibledrilltargets', [])
        if targets:
            print(f"Found {len(targets)} targets at {axis}={offset}")
            break
```

### Drilling progress

When the drill is working and has targets:
- `drill_currentdrilltarget` shows the active target (None if idle)
- `currentVolume` / `fillRatio` show collected material
- `items` in drill telemetry shows what's in the drill's internal inventory
- Material transfers to the grid's cargo containers via conveyor system

**Confirmed**: drill mining stone on asteroid surface produced 35,000+ Stone in ~10 seconds
of active drilling. The stone appeared in the Large Cargo Container automatically.

### Power considerations

- Drill requires ~160 kW (from `detailedInfo`)
- Batteries may not report telemetry (storedPower=None) — check if drill `isWorking=True`
- Solar panels provide power in space but output varies with orientation
- If drill keeps disabling, check battery charge level and solar panel output
