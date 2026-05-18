# Projection Alignment Reference

## ⚠️ Blueprint XML Bloat Problem (discovered 2026-05-14)

Blueprint exports can grow from ~40KB to ~800KB due to ComponentContainer metadata,
inventory data, and nested block state. **Loading bloated XML causes total alignment
failure** — `remainingBlocks == totalBlocks` regardless of offset/rotation.

### Root cause
The SE game's blueprint loader chokes on the extra ComponentContainer data. The
projection system can't match blocks when the XML contains nested inventory items,
component lists, and mod metadata.

### Solution: minimal XML stripping
Strip all non-essential child elements from each block in CubeBlocks:

```python
essential_tags = {
    'SubtypeName', 'Min', 'BlockOrientation', 'ColorMaskHSV',
    'Owner', 'BuiltBy', 'ShareMode', 'EntityId',
    'ProjectionOffset', 'ProjectionRotation',
    'Enabled', 'KeepProjection',
}
for cg in root.iter('CubeGrid'):
    cb = cg.find('CubeBlocks')
    if cb is None: continue
    for block in list(cb):
        to_remove = [child for child in block
                     if (child.tag.split('}')[-1] if '}' in child.tag else child.tag)
                     not in essential_tags]
        for child in to_remove:
            block.remove(child)
minimal_xml = '<?xml version="1.0" encoding="utf-8"?>\r\n' + ET.tostring(root, encoding='unicode')
```

Result: 786KB → ~15KB. Alignment works again with verified offset/rotation.

### How to detect the problem
If `remainingBlocks` stays at `totalBlocks` for ALL offset/rotation combinations,
the XML is likely bloated. Check XML size — if >100KB for a <30-block grid, strip it.

## ⚠️ set_offset / set_rotation don't work after load

The SE server reads ProjectionOffset/Rotation from the XML at load time. Calling
`proj.set_offset()` or `proj.set_rotation()` after `load_blueprint_xml()` updates
the telemetry but does NOT change the projection's actual position or `remainingBlocks`.

**To change alignment, you must embed offset/rotation in the XML before loading.**

```python
# In the projector block within CubeBlocks:
po = block.find('ProjectionOffset')
if po is not None:
    po.find('X').text = str(offset_x)
    po.find('Y').text = str(offset_y)
    po.find('Z').text = str(offset_z)
pr = block.find('ProjectionRotation')
if pr is not None:
    pr.find('X').text = str(rot_x)
    pr.find('Y').text = str(rot_y)
    pr.find('Z').text = str(rot_z)
```

## Telemetry timing

`proj.update()` needs 0.3–1.0s after offset/rotation change to reflect new
`remainingBlocks`. Polling faster than 0.1s returns stale values and wastes
iterations in brute-force sweeps. Use 0.5s sleep for rotation sweep, 0.3s for
offset sweep.

## Blueprint export reliability

- Rapid `set_offset()`/`set_rotation()` commands can overwhelm the SE plugin,
  causing `request_grid_blueprint()` to stop responding (blueprint never appears
  in Redis).
- If export fails, wait 60s and retry. If still failing, the SE plugin may need
  a restart.
- The blueprint Redis key has a TTL — it may expire between sessions. Always
  re-export before modifying.
- `reset_projection` may also clear the cached blueprint. Export BEFORE resetting
  if you need the old data.

## DroneBase (ID: 138748817302648345) — VERIFIED

**Alignment values** (remainingBlocks=0):
- `offset = (-5, -5, -4)`
- `rotation = (1, 0, 0)`
- `scale = 1`

**Grid world position**: `(998845, 91272, 1595378)`
**Grid orientation**: Forward=`(0.359, 0.444, -0.820)`, Up=`(-0.516, -0.637, -0.571)` (non-axis-aligned, Mars surface)

### Grid layout (block coordinates)

```
Block type                              | Min (x, y, z)  | Orientation
----------------------------------------|----------------|------------------
LargeBlockArmorBlock                    | (-1, 0, -1)    | default
LargeBlockArmorBlock                    | (-1, 0, 0)     | default
LargeBlockArmorBlock                    | (-1, 0, 1)     | default
LargeBlockArmorBlock                    | (0, 0, 0)      | default
LargeBlockArmorBlock                    | (0, 0, 1)      | default
LargeBlockArmorBlock                    | (1, 0, -1)     | default
LargeBlockArmorBlock                    | (1, 0, 0)      | default
LargeBlockArmorBlock                    | (1, 0, 1)      | default
LargeBlockBatteryBlock                  | (0, 0, -1)     | F=Down, U=Forward
LargeBlockLargeContainer                | (0, 0, -4)     | F=Left, U=Forward
LargeBlockSmallContainer                | (1, 1, 1)      | default
LargeBlockConveyor                      | (1, 1, 0)      | default
LargeBlockConveyor                      | (1, 2, 0)      | default
LargeBlockConveyor                      | (1, 3, 0)      | default
LargeBlockConveyor                      | (1, 4, 0)      | default
LargeBlockConveyor                      | (1, 5, 0)      | default
LargeBlockConveyor                      | (1, 6, 0)      | default
Connector                               | (1, 7, 0)      | F=Up, U=Backward
SurvivalKitLarge                        | (1, 1, -1)     | F=Right, U=Up
LargeBlockBeacon                        | (1, 2, 1)      | default
LargeBlockSolarPanel                    | (0, 3, -3)     | F=Backward, U=Right
LargeProjector                          | (0, 1, 0)      | F=Right, U=Up
SELtdLargeNanobotBuildAndRepairSystem   | (3, 1, -3)     | F=Down, U=Backward
OxygenGenerator (subtype=None)          | (1, 1, 2)      | default
```

**Total: 24 blocks** (8 armor, 6 conveyors, 2 cargo, 1 battery, 1 solar, 1 survival kit, 1 beacon, 1 connector, 1 projector, 1 welder, 1 O2 generator)

### Conveyor line
Runs along `x=1, z=0`, from `y=1` to `y=6` (6 conveyors), ending at Connector at `y=7`.

### Proposed Assembler position: `Min = (2, 2, 0)`
- LargeAssembler = 3×3×3 blocks, occupying `(2..4, 2..4, 0..2)`
- Adjacent to conveyor at `(1, 2, 0)` — connected via conveyor port
- No overlap with existing blocks
- BlockOrientation: `Forward=Right, Up=Up` (port facing conveyor line)

## Core1 (ID: 143139590779134749) — VERIFIED

**Alignment values** (projector at origin, no offset needed):
- `offset = (0, 0, 0)`
- `rotation = (0, 0, 0)`
- `scale = 1`

**Grid world position**: `(998762, 91340, 1595390)` (approximate)
**Grid orientation**: Forward=`(0.795, -0.604, -0.047)`, Up=`(-0.518, -0.637, -0.572)` (Mars)

### Grid layout (block coordinates)

```
Block type                              | Min (x, y, z)  | Orientation
----------------------------------------|----------------|------------------
LargeProjector                          | (0, 0, 0)      | default (projector at origin!)
LargeBlockSmallContainer                | (1, 0, 0)      | F=Left, U=Down
LargeBlockBatteryBlock                  | (-1, 0, 0)     | F=Down, U=Left
SELtdLargeNanobotBuildAndRepairSystem   | (1, 0, -1)     | F=Down, U=Right
SELtdLargeNanobotDrillSystem            | (1, 0, -2)     | F=Down, U=Forward
Blast Furnace (Refinery)                | (2, 0, 0)      | F=Left, U=Up
```

**Total: 6 blocks** (projector, small container, battery, nanobot welder, nanobot drill, blast furnace)

**Projector at origin**: `local_position = (0.0, 0.0, 0.0)` → `Min = (0, 0, 0)`. This means
`ProjectionOffset=(0,0,0)` and `ProjectionRotation=(0,0,0)` align perfectly. **No brute-force
search needed for this grid.**

**Successfully added**: LargeBlockSolarPanel at `Min=(0,1,0)`, Orientation `Forward=Up, Up=Backward`.
`load_blueprint_xml` loaded 7-block XML → `totalBlocks=1, remainingBlocks=1` (6 existing blocks
matched, 1 new solar panel needed building).

## `load_blueprint_xml` format requirements (VERIFIED 2026-05-16)

The `load_blueprint_xml` command sends XML via Redis to the SE plugin. Format matters:

**Working format:**
```xml
<?xml version="1.0" encoding="utf-16"?>
<MyObjectBuilder_ShipBlueprintDefinition xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Id Type="MyObjectBuilder_ShipBlueprintDefinition" Subtype="Core1" />
  <DisplayName>Core1</DisplayName>
  <CubeGrids>
    <CubeGrid>
      <EntityId>143139590779134749</EntityId>
      <GridSizeEnum>Large</GridSizeEnum>
      <CubeBlocks>
        <!-- blocks here -->
      </CubeBlocks>
    </CubeGrid>
  </CubeGrids>
</MyObjectBuilder_ShipBlueprintDefinition>
```

**Critical requirements:**
- `xmlns:xsd` and `xmlns:xsi` namespace attributes MUST be present on root element
- `<Id>` with `Type` and `Subtype` attributes MUST be present
- `<GridSizeEnum>Large</GridSizeEnum>` (or `Small`) MUST match the target grid
- Minimal XML (stripped of ComponentContainer) loads successfully
- Full bloated XML may silently fail: `isProjecting=False, totalBlocks=0`
- The `encoding="utf-16"` declaration in the header works even though content is ASCII/UTF-8

**What does NOT work:**
- Missing `xmlns:xsd`/`xmlns:xsi` → silent failure
- Using just `<ShipBlueprintDefinition>` instead of `<MyObjectBuilder_ShipBlueprintDefinition>` → silent failure
- Changing encoding to `"utf-8"` → may also fail (untested conclusively)

**`blueprint_snapshot()` return format:** Returns a `dict` with keys:
- `ok` (bool), `xml` (str), `gridName` (str), `gridCount` (int)
- `gridId` (int), `deviceId` (int), `ownerId` (int)
- `timestamp` (ISO str), `includeConnected` (bool), `blueprintName` (str)

Access XML via `snap['xml']`, not the raw return value.

## `totalBlocks` semantics (VERIFIED 2026-05-16)

`totalBlocks` in projector telemetry counts **only NEW (unbuilt) blocks**. Blocks already
constructed on the grid are excluded from the count. So:
- 7-block XML loaded, 6 blocks already exist → `totalBlocks=1`
- `remainingBlocks=1` means 1 new block needs building
- `remainingBlocks=0` means all projected blocks are already built (perfect alignment)

## Projector freeze state (discovered 2026-05-15)

After extensive rapid `set_offset()`/`set_rotation()` calls (30+ commands in quick succession),
the SE projector can enter a **frozen state**:

**Symptoms:**
- `set_offset(x,y,z)` returns `seq=1` (success code) — looks normal
- `telemetry['commands']['lastMs']` updates (~16ms) — command channel alive
- But `telemetry['ProjectionOffset']` stays at the old value — **server ignores commands**
- `remainingBlocks` doesn't change regardless of what offset/rotation is set
- `request_grid_blueprint()` stops producing Redis keys (export broken)
- `buildableBlocks` stays at 0

**Root cause:** SE plugin command queue overwhelmed. The plugin consumes commands (returns success)
but doesn't apply them to the projector block's actual state.

**Diagnosis:** Check if offset/rotation actually change after a `set_offset`:
```python
proj.set_offset(5, 5, 5)
time.sleep(1)
proj.update()
actual = proj.telemetry.get('ProjectionOffset', {})
print(f"Set (5,5,5), got: {actual}")  # If still old value → FROZEN
```

**Recovery:** Restart the SE server or the plugin. Waiting alone doesn't fix it — the
projector stays frozen indefinitely (tested: 5+ minutes with no recovery).

**Prevention:** After brute-force sweeps, add 0.5s+ sleep between offset/rotation changes.
Never send more than ~20 commands per minute to a single projector.

### Offset calculation from projector position (VERIFIED 2026-05-16)

If the projector is at grid position `Min=(px, py, pz)`, the projection offset needed
to align the blueprint is `offset = (-px, -py, -pz)`. This works because the projection
origin is at the projector's position, and the blueprint's blocks are relative to grid origin.

```python
# Get projector's grid position from telemetry
proj_pos = projector.local_position  # meters
proj_min = tuple(round(v / 2.5) for v in proj_pos)  # grid coords
calculated_offset = tuple(-v for v in proj_min)
```

**Status: VERIFIED.** Tested on Core1 (projector at origin (0,0,0)) — offset=(0,0,0) aligned
perfectly: `remainingBlocks=0` for all 6 existing blocks. The formula works when:
- Rotation is already correct (0,0,0 for axis-aligned grids)
- The projector's `local_position` in meters converts cleanly to grid units

**For non-axis-aligned grids** (most planetary surfaces), rotation must be determined first
(via brute-force), then offset can be calculated from the projector's rotated position.

**Practical recommendation**: For new grids, place the projector at grid origin `(0,0,0)`
and ensure `ProjectionRotation=(0,0,0)` in the XML. This guarantees zero-offset alignment.

## Telemetry-based XML construction (fallback when export broken)

When `request_grid_blueprint()` fails (e.g. projector frozen), you can construct a valid
minimal blueprint XML from block telemetry data:

```python
import xml.etree.ElementTree as ET

blocks_xml = []
for bid, block in grid.blocks.items():
    if not block.local_position:
        continue
    # Convert meters to grid coords (large block = 2.5m)
    gx, gy, gz = [round(v / 2.5) for v in block.local_position]
    
    subtype = block.subtype or ''
    block_type = block.block_type or ''
    
    # Map block_type to xsi:type
    type_map = {
        'LargeBlockArmorBlock': ('MyObjectBuilder_CubeBlock', 'LargeBlockArmorBlock'),
        'LargeBlockConveyor': ('MyObjectBuilder_Conveyor', 'LargeBlockConveyor'),
        'LargeBlockBatteryBlock': ('MyObjectBuilder_BatteryBlock', 'LargeBlockBatteryBlock'),
        'LargeBlockSolarPanel': ('MyObjectBuilder_SolarPanel', 'LargeBlockSolarPanel'),
        'LargeBlockLargeContainer': ('MyObjectBuilder_CargoContainer', 'LargeBlockLargeContainer'),
        'Connector': ('MyObjectBuilder_ShipConnector', 'Connector'),
        'SurvivalKitLarge': ('MyObjectBuilder_SurvivalKit', 'SurvivalKitLarge'),
        'LargeProjector': ('MyObjectBuilder_Projector', 'LargeProjector'),
        'SELtdLargeNanobotBuildAndRepairSystem': ('MyObjectBuilder_ShipWelder', 'SELtdLargeNanobotBuildAndRepairSystem'),
        'LargeBlockBeacon': ('MyObjectBuilder_Beacon', 'LargeBlockBeacon'),
        'OxygenGenerator': ('MyObjectBuilder_OxygenGenerator', 'OxygenGenerator'),
    }
    xsi, sub = type_map.get(block_type, ('MyObjectBuilder_CubeBlock', block_type))
    
    blocks_xml.append(f'''    <MyObjectBuilder_CubeBlock xsi:type="{xsi}">
      <SubtypeName>{sub}</SubtypeName>
      <Min x="{gx}" y="{gy}" z="{gz}" />
      <ColorMaskHSV x="0" y="-1" z="0.3647059" />
      <Owner>0</Owner>
      <BuiltBy>0</BuiltBy>
    </MyObjectBuilder_CubeBlock>''')

xml = f'''<?xml version="1.0" encoding="utf-8"?>
<ShipBlueprintDefinition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Id Type="MyObjectBuilder_ShipBlueprintDefinition" Subtype="DroneBase" />
  <ShipBlueprint>
    <CubeGrids>
      <CubeGrid>
        <PositionAndOrientation>
          <Position x="0" y="0" z="0" />
          <Forward x="0" y="0" z="-1" />
          <Up x="0" y="1" z="0" />
        </PositionAndOrientation>
        <CubeBlocks>
{chr(10).join(blocks_xml)}
        </CubeBlocks>
      </CubeGrid>
    </CubeGrids>
  </ShipBlueprint>
</ShipBlueprintDefinition>'''
```

**Limitations:**
- `local_position` from telemetry uses the grid's origin — the world `PositionAndOrientation`
  doesn't matter for projection alignment (offset handles that)
- Orientation of each block (`BlockOrientation`) is NOT available from telemetry — blocks
  default to Forward=Forward, Up=Up. Non-default orientations (e.g. rotated conveyors) will
  be wrong. Works for armor/standard blocks; may fail for rotated components.
- This is a **last resort** when export is broken. Always prefer `request_grid_blueprint()`.

## `buildableBlocks` diagnostic

| `buildableBlocks` | `remainingBlocks` | Meaning |
|--------------------|-------------------|---------|
| 0 | > 0 | Projection completely misaligned — no blocks overlap grid |
| > 0 but < total | > 0 | Partial alignment — some blocks in valid positions |
| = total | > 0 | Alignment good, blocks unbuilt (need resources or welder) |
| 0 | 0 | All blocks built! |

When `buildableBlocks == 0` and `remainingBlocks == totalBlocks`, the offset/rotation is
completely wrong OR the XML is bloated. Check XML size first, then redo alignment search.

## Blueprint export failure modes

1. **Normal failure**: Redis key appears after 3-5s. Telemetry `blueprintStatus` may show state.
2. **Slow server**: Key appears after 10-30s. Wait up to 60s.
3. **Plugin overload** (rapid commands): Key never appears. Wait 60s, retry. If still failing
   after 3 attempts → plugin needs restart.
4. **Frozen projector**: Key never appears AND offset/rotation are stuck. Restart required.

## How to find alignment for a NEW grid

1. Disable welder
2. Export blueprint (any offset/rotation — just to get the XML)
3. Load the SAME blueprint back
4. Try `rotation=(1,0,0)` first — most grids on planets need X-axis rotation
5. Brute-force offset search: `range(-8, 9)` for x, y, z
6. If no match at `rotation=(1,0,0)`, try other single-axis rotations
7. If no match with any single rotation, try combinations
8. Once `remainingBlocks == 0` → save the values

Typical search time: ~2-5 minutes per rotation (8³ = 512 combinations at 0.12s each)

## Block type → XML element mapping

| SE Block | xsi:type | SubtypeName |
|----------|----------|-------------|
| Armor | MyObjectBuilder_CubeBlock | LargeBlockArmorBlock |
| Conveyor | MyObjectBuilder_Conveyor | LargeBlockConveyor |
| Battery | MyObjectBuilder_BatteryBlock | LargeBlockBatteryBlock |
| Solar Panel | MyObjectBuilder_SolarPanel | LargeBlockSolarPanel |
| Cargo Container | MyObjectBuilder_CargoContainer | LargeBlockLargeContainer / LargeBlockSmallContainer |
| Projector | MyObjectBuilder_Projector | LargeProjector |
| Ship Welder | MyObjectBuilder_ShipWelder | SELtdLargeNanobotBuildAndRepairSystem (mod) |
| Connector | MyObjectBuilder_ShipConnector | Connector |
| Survival Kit | MyObjectBuilder_SurvivalKit | SurvivalKitLarge |
| Assembler | MyObjectBuilder_Assembler | LargeAssembler / LargeAssemblerSurvival |
| Refinery | MyObjectBuilder_Refinery | LargeRefinery |
| Beacon | MyObjectBuilder_Beacon | LargeBlockBeacon |
| Ore Detector | MyObjectBuilder_OreDetector | LargeOreDetector |
| O2 Generator | MyObjectBuilder_OxygenGenerator | (subtype may be empty) |
| Drill | MyObjectBuilder_Drill | LargeBlockDrill |
| Nanobot Drill | MyObjectBuilder_Drill | SELtdLargeNanobotDrillSystem (mod) |
