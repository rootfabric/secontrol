[← Parent skill: secontrol-space-engineers](../SKILL.md)

# Space Docking — Zero-G Connector-to-Connector Approach

Universal workflow for docking a ship to a base via connectors in space (zero gravity).

## Prerequisites

- Ship has: RemoteControl, Gyro(s), Thruster(s), Connector
- Base has: Connector
- Both grids accessible via `prepare_grid()` (STRING args!)

## Data needed

```python
ship_grid = prepare_grid("ship_name")
base_grid = prepare_grid("base_name")

rc = ship_grid.get_first_device('remote_control')
ship_conn = ship_grid.get_device_any(ship_connector_id)
base_conn = base_grid.get_device_any(base_connector_id)

# Positions (from telemetry)
rc_pos = rc.telemetry['position']        # {x, y, z}
ship_conn_pos = ship_conn.telemetry['position']
base_conn_pos = base_conn.telemetry['position']

# Orientations (connector has orientation in telemetry!)
base_fwd = base_conn.telemetry['orientation']['forward']  # {x, y, z}
ship_fwd = ship_conn.telemetry['orientation']['forward']

# RC offset from ship connector (ship-local)
rc_offset = (rc_pos - ship_conn_pos)
```

## Approach algorithm

### Phase 0: Enable ship systems

Newly built ships have most blocks disabled. Enable everything:

```python
for block in ship_grid.blocks.values():
    if (block.state or {}).get('enabled') is False:
        dev = ship_grid.get_device_any(block.block_id)
        if dev:
            try: dev.set_enabled(True)
            except: pass
time.sleep(2)
```

Also disable merge blocks if present (they lock the ship):

```python
for dev in ship_grid.devices.values():
    if type(dev).__name__ == 'MergeBlockDevice' or dev.device_type == 'merge_block':
        dev.disable()
```

### Phase 1: Fly to approach point

Compute approach point: `approach_distance` meters in front of base connector,
adjusted by RC offset so the ship connector ends up at the approach point.

```python
# Approach point = base_pos + base_fwd * approach_distance
approach = base_conn_pos + base_fwd * approach_distance

# RC target = approach - rc_offset
rc_target = approach - rc_offset

# Disable collision avoidance (base sits on asteroid)
rc.set_collision_avoidance(False)

# Fly
gps = f"GPS:Approach:{rc_target[0]:.6f}:{rc_target[1]:.6f}:{rc_target[2]:.6f}:"
rc.goto(gps, speed=5)

# Monitor until close
while dist_to_target > 5:
    time.sleep(2)
    # check position, speed

rc.disable()
rc.dampeners_on()
```

**⚠️ Collision avoidance must be OFF for base docking.** The base sits on an asteroid,
so SE's collision avoidance sees voxels and stops the ship prematurely. Handle obstacle
detection manually with RadarController if needed.

### Phase 2: Align ship to face base connector

The ship must be rotated so its connector faces the base connector.

```python
# Desired forward = direction from ship toward base
desired_fwd = normalize(base_conn_pos - rc_pos)

# Use gyro aim_vector
gyro = ship_grid.get_first_device('gyro')
gyro.aim_vector({"x": desired_fwd[0], "y": desired_fwd[1], "z": desired_fwd[2]})

# Monitor angle
while angle > tolerance:
    time.sleep(1)
    # recalculate angle from RC orientation

gyro.set_override(pitch=0, yaw=0, roll=0)  # stop gyro
```

**⚠️ Gyro aim_vector works for large angles (180°+).** It uses the SE plugin's internal
alignment algorithm, not a simple P-controller. More reliable than manual gyro override
for large rotations.

**⚠️ RC must be disabled during alignment.** If RC autopilot is active, it fights the
gyro commands. Disable RC, align with gyro, then re-enable RC for final approach.

### Phase 3: Creep and dock

Final approach at low speed. Use RC goto with `dock=True`.

```python
dock_point = base_conn_pos + base_fwd * 1.5  # 1.5m from base connector
rc_dock_target = dock_point - rc_offset

gps = f"GPS:Dock:{rc_dock_target[0]:.6f}:{rc_dock_target[1]:.6f}:{rc_dock_target[2]:.6f}:"
rc.goto(gps, speed=2, dock=True)

# Monitor connector status
while True:
    time.sleep(0.5)
    status = ship_conn.telemetry.get('connectorStatus')
    if status == 'Connected':
        print("DOCKED!")
        break

    # If very close, try connector lock
    if dist_to_base < 2.0:
        ship_conn.connect()
        time.sleep(1)
        if ship_conn.telemetry.get('connectorStatus') == 'Connected':
            break

    # If stuck (collision avoidance), disable it and retry
    if not moving:
        rc.set_collision_avoidance(False)
        rc.goto(gps, speed=1, dock=True)
```

## Common pitfalls

1. **`prepare_grid()` with int arg → wrong grid.** Always use STRING.
2. **Ship blocks disabled after projection.** Enable all blocks first.
3. **Collision avoidance stops ship near base.** Base sits on asteroid → voxels detected.
   Disable CA and handle manually.
4. **RC.enable() ≠ block enable.** `rc.enable()` = autopilot. `rc.set_enabled(True)` = block power.
   RC block may not be enableable via API (shows `enabled: False` even after `set_enabled(True)`).
5. **Connector orientation is in telemetry.** Use `conn.telemetry['orientation']['forward']` for
   approach vector calculation.
6. **RC offset changes with ship rotation.** The RC's world position relative to the ship connector
   changes as the ship rotates. Recalculate after alignment.
7. **Gyro aim_vector may cause overshoot.** For fine alignment (<10°), use P-controller:
   `cross = cross(current_fwd, desired_fwd); yaw = clamp(cross[2] * 2, -1, 1)`
8. **`dock=True` in RC goto may not work as expected.** SE's dock mode may just slow down
   near the target — it doesn't guarantee connector alignment. Manual alignment (Phase 2)
   is still required.

## Full script

Reusable script at `scripts/space_docker.py`:

```bash
python scripts/space_docker.py \
  --base skynet-farpost0 \
  --base-connector 84716854740522554 \
  --ship skynet-baza2 \
  --ship-connector 109000895254503418 \
  --safe-distance 50 \
  --approach-distance 50
```
