# Nanobot Drill — Complete Mining Workflow

Tested and verified on skynet-baza0 (large grid, Mars orbit/asteroid field) on 2026-05-17.

## Problem: Mining gold ore at a known deposit

Given: ore deposit coordinates from OreDetector scan (world coords).
Goal: fly to the deposit, configure drill area, mine ore.

## Step 1: Find the asteroid

Use OreDetector `asteroids` command to find nearby asteroids and correlate with ore position:

```python
ore_det.send_command({
    "cmd": "asteroids",
    "targetId": int(ore_det.device_id),
    "state": {"radius": 50000.0, "limit": 320, "includePlanets": False},
})
# Wait for asteroidIndex.ready=True in telemetry
# Parse items — center is a LIST [x, y, z], not a dict
for a in tel['asteroidIndex']['items']:
    cx, cy, cz = a['center'][0], a['center'][1], a['center'][2]
    d_gold = sqrt((cx-gold[0])**2 + (cy-gold[1])**2 + (cz-gold[2])**2)
```

Ore deposits are INSIDE asteroids. If `d_gold < approxRadius`, the deposit is within that asteroid.

## Step 2: Fly to the asteroid surface

Use RC autopilot at speed=15 (fast) then manually stop:

```python
rc.enable(); rc.gyro_control_on(); rc.thrusters_on(); rc.dampeners_on()
rc.set_mode("oneway"); rc.set_collision_avoidance(False)
rc.goto(gps_str, speed=15.0, gps_name="Ore")

# Monitor — disable autopilot before overshoot
while True:
    time.sleep(2); rc.update()
    dist = compute_dist(rc_pos, gold)
    if dist < 40:
        rc.disable(); time.sleep(1)
        rc.enable(); rc.dampeners_on()
        break

# Wait for dampeners to stop
for _ in range(30):
    time.sleep(2); rc.update()
    if rc.telemetry['speed'] < 0.3: break
```

**Pitfall**: RC autopilot overshoots in space. The ship reaches ~30m then drifts past at 2-3 m/s.
Always disable RC at ~40m and let dampeners handle the final stop.

Verify: OreDetector `asteroidIndex` should show `surfaceDistance=0` for the nearest asteroid.

## Step 3: Compute drill area offset

The drill area is centered on the drill block. To point it at the ore deposit:

```python
# Get drill block offset from RC (from grid.blocks local_position)
drill_local = (-2.5, 2.5, 5.0)  # example: drill at (0,5,-2.5), RC at (2.5,2.5,-7.5)

# Compute drill world position
orient = rc.telemetry['orientation']
fwd, up = orient['forward'], orient['up']
right = cross(fwd, up)

drill_world = (
    rc_pos['x'] + drill_local[0]*right['x'] + drill_local[1]*up['x'] + drill_local[2]*fwd['x'],
    rc_pos['y'] + drill_local[0]*right['y'] + drill_local[1]*up['y'] + drill_local[2]*fwd['y'],
    rc_pos['z'] + drill_local[0]*right['z'] + drill_local[1]*up['z'] + drill_local[2]*fwd['z'],
)

# Vector from drill to ore
ddx, ddy, ddz = gold[0]-drill_world[0], gold[1]-drill_world[1], gold[2]-drill_world[2]

# Project onto ship-local axes
local_fwd  = ddx*fwd['x'] + ddy*fwd['y'] + ddz*fwd['z']
local_up    = ddx*up['x']  + ddy*up['y']  + ddz*up['z']
local_right = ddx*right['x'] + ddy*right['y'] + ddz*right['z']
```

## Step 4: Configure and start drill

```python
# Set area offset
drill.set_property("AreaOffsetUpDown", local_up)
drill.set_property("AreaOffsetFrontBack", local_fwd)
drill.set_property("AreaOffsetLeftRight", local_right)

# WorkMode=2 (Drill) — raw command required (set_work_mode is bugged!)
drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})

# Conveyor for auto-transfer to cargo
drill.set_use_conveyor(True)

# CRITICAL: ScriptControlled=False for auto-mining!
drill.set_property("ScriptControlled", False)

# Start mining sequence
drill.turn_on()
drill.start_drilling()  # REQUIRED — without this, drill stays idle
```

**Critical settings**:
- `ScriptControlled=False` → drill auto-selects and mines targets
- `ScriptControlled=True` → drill reports targets but waits for commands (no auto-mining)
- `start_drilling()` → must be called after `turn_on()` to begin mining

## Step 5: Monitor

```python
for i in range(20):
    time.sleep(3)
    drill.update(); time.sleep(1)
    tel = drill.telemetry or {}
    props = tel.get('properties', {})
    targets = tel.get('drill_possibledrilltargets', [])
    current = props.get('Drill.CurrentDrillTarget')
    gold_targets = [t for t in targets if 'Gold' in str(t)]
    print(f"Targets={len(targets)}(Gold={len(gold_targets)}) Mining={'Yes' if current else 'No'}")

# Check inventory
for inv in drill.inventories():
    for item in (inv.items or []):
        print(f"  {item.display_name}: {item.amount:.1f}")
```

## Results from test sessions

### Session 1: Ship at ~20m from gold (2026-05-17)

| Metric | Before | After 30s |
|---|---|---|
| Gold targets | 6 | 4 |
| Gold Ore in inventory | 0 | 948.6 |
| Stone in inventory | 0 | 53598.6 |
| CurrentDrillTarget | None | Gold_01 |

### Session 2: Ship at ~50m from gold (2026-05-17)

| Metric | Value |
|---|---|
| RC→Gold distance | 49.6m (≥50m safe) |
| Drill→Gold distance | 55.3m |
| AreaOffset | 0 (default) |
| Gold targets | 2 (at 43-46m) |
| Mining gold? | Yes (⛏️Gold confirmed) |
| Gold Ore location | Cargo Container (via conveyor) |

Drill successfully mined Gold ore from asteroid deposit at **50m safe distance**.
Stone was also collected from surrounding asteroid voxels (unavoidable).

## Key findings from session 2 (2026-05-17)

### AreaOffset=0 works at 50m distance

The drill area (75×75×75m) reaches ore at 42-46m from the drill block **without
any offset**. The area appears to extend further than the theoretical 37.5m radius
from center. At 50m RC distance (~55m drill-to-ore), gold targets were found at
43-46m with zero offset.

**Don't set large offsets** — offset of 55m toward the gold resulted in 0 targets.
The mod may clamp large offsets or the area geometry doesn't work as expected.
Instead: fly to ~50m, use zero offset, let the drill auto-select targets.

### Ore goes to Container via conveyor

With `set_use_conveyor(True)`, mined ore is transferred to CargoContainer
automatically. The drill's own inventory shows 0 items. To check gold ore:

```python
# Check ALL containers, not just drill
from secontrol.devices.container_device import ContainerDevice
cargo = grid.get_first_device(ContainerDevice)
cargo.update()
for inv in cargo.inventories():
    for item in (inv.items or []):
        if 'Gold' in (item.subtype or ''):
            print(f"Gold Ore: {item.amount:.1f}")
```

### Drill state corruption after many config changes

After multiple AreaOffset changes, enable/disable cycles, and restart attempts,
the drill can enter a state where it reports 0 targets even though ore exists.
**Full reset fixes it:**

```python
drill.stop_drilling(); time.sleep(0.5)
drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": False}})
time.sleep(1)
drill.set_property("AreaOffsetUpDown", 0.0)
drill.set_property("AreaOffsetFrontBack", 0.0)
drill.set_property("AreaOffsetLeftRight", 0.0)
time.sleep(0.3)
drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})
time.sleep(0.3)
drill.set_property("ScriptControlled", False)
time.sleep(0.3)
drill.set_use_conveyor(True)
time.sleep(0.2)
drill.turn_on(); time.sleep(0.5)
drill.start_drilling(); time.sleep(3)
# Now check targets — should be non-zero if ore is in range
```

### Safe distance: ≥50m from ore/asteroid

Ship crashes into asteroid voxels when flying closer than 50m to ore coordinates.
**Always stop at ≥50m from ore.** The drill area reaches far enough to mine
from this distance.

### Grid IDs can change

skynet-baza0 grid ID changed from `118168110731275470` to `91207270182100228`
between sessions. Always use `get_all_grids()` to find current IDs.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Targets=0 | Drill not on asteroid surface | Check `asteroidIndex` surfaceDistance=0 |
| Targets=0 after config changes | Drill state corruption | Full reset (stop→off→reset offsets→on→start) |
| Targets>0 but CurrentTarget=None | ScriptControlled=True | Set `ScriptControlled=False` |
| CurrentTarget=None after turn_on | start_drilling() not called | Call `drill.start_drilling()` |
| Drill auto-disables in space | Power/idle timeout | Re-enable: `send_command(OnOff, True)` |
| Area offset wrong | Vector not projected to ship-local | Recompute using RC orientation vectors |
| set_property("AreaWidth") fails | Not supported via API | Use `AreaWidth_Increase` action |
| Large AreaOffset → 0 targets | Offset too large, mod clamps | Use zero offset, fly closer instead |
| GoldOre=0 but Mining=Gold | Ore in CargoContainer via conveyor | Check ContainerDevice, not drill inventory |
| Ship crashes into asteroid | Flew too close to ore | Stop at ≥50m from ore coordinates |
