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

Typical path: `/workspace/src/secontrol/` (adjust per repo). Check `AGENTS.md` and `ARCHITECTUREURE.md` first.

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

## Core API patterns

### List all grids

```python
from secontrol.common import get_all_grids, resolve_owner_id
owner = resolve_owner_id()
grids = get_all_grids()  # returns list of (grid_id, grid_name)
```

### Read container inventory

```python
# Containers use get_inventory() → InventorySnapshot (items are objects with attributes)
for did, dev in grid.devices.items():
    if dev.device_type == 'container':
        inv = dev.get_inventory()
        for item in inv.items:
            print(f'{item.display_name}: {item.amount}')
```

### Read refinery/assembler inventory

```python
# Refinery/assembler use telemetry dicts (items are plain dicts with string keys!)
t = refinery.telemetry or {}
inp = t.get('inputInventory', {})
for item in inp.get('items', []):
    print(f'{item["displayName"]}: {item["amount"]}')
```

**Full details + pitfalls → `references/inventory-patterns.md`**

### Connect to a specific grid

```python
from secontrol.common import prepare_grid
grid = prepare_grid('GridName_or_GridID')  # by name or ID, auto-wakes
```

### Grid health scan (damage, non-functional, disabled)

```python
# Quick health check across all grids
from secontrol.common import get_all_grids, prepare_grid
import time

for gid, gname in get_all_grids():
    grid = prepare_grid(str(gid))  # ALWAYS str, never int
    time.sleep(1)
    damaged = [b for b in grid.blocks.values() if getattr(b, 'is_damaged', False)]
    non_func = [b for b in grid.blocks.values() if (b.state or {}).get('functional') == False]
    disabled = [b for b in grid.blocks.values() if (b.state or {}).get('enabled') == False]
```

**Pitfall: armor blocks are always `functional=False`** — this is normal SE behavior, not damage. Filter non-functional reports to exclude `MyObjectBuilder_CubeBlock` (armor) to avoid false alarms. Real damage = `is_damaged=True` on functional blocks (SolarPanel, Conveyor, Refinery, etc.).

**Pitfall: `execute_code` sandbox does NOT have secontrol installed.** Always use `terminal` (or `bash` tool) for secontrol scripts. The package is pip-installed at the system level, not inside the sandbox venv.

### Enumerate devices on a grid

Device type names are **lowercase singular** strings (e.g. `'projector'`, `'ship_welder'`, `'survivalkit'`, `'solarpanel'`, `'beacon'`). Use `find_devices_by_type()` or `get_device_any()`:

```python
# All enabled devices
for dev in grid.find_enabled_devices():
    print(f"  {dev.device_type}: {dev.name or 'unnamed'} (id={dev.device_id})")

# Find by type (lowercase!)
for p in grid.find_devices_by_type("projector"):
    print(f"  projector: {p.name}, id={p.device_id}")
    # Access telemetry
    print(f"    isProjecting: {p.telemetry.get('isProjecting')}")
    print(f"    remainingBlocks: {p.telemetry.get('remainingBlocks')}")
    print(f"    totalBlocks: {p.telemetry.get('totalBlocks')}")

# Fuzzy find by name substring
welder = grid.get_device_any("welder")
assembler = grid.get_device_any("assembler")
```

**Device type name quirks**: `ShipWelderDevice` → `ship_welder` (underscore). Survival Kit → `survivalkit` (no space). Solar → `solarpanel`. Ore detector → `ore_detector` (underscore, NOT `oredetector`). When unsure, iterate `find_enabled_devices()` and print `dev.device_type` for all.

### Inspect ALL blocks (block-level, no device class)

Useful when checking for blocks that have no device wrapper (e.g. armor, conveyor, non-registered blocks):

```python
# g.blocks is a dict: block_id → BlockInfo
print(f"Total blocks: {len(grid.blocks)}")
for block_id, block in sorted(grid.blocks.items(), key=lambda x: x[1].block_type or ''):
    functional = "✓" if block.state.get('functional') else "✗"
    enabled = "ON" if block.state.get('enabled') else "OFF"
    print(f"  [{block.block_type}] '{block.subtype}' | {functional} {enabled}")
```

### Find a specific block by type or subtype

When the user asks for a specific block (e.g. "Connector", "Refinery", "Battery"), search `grid.blocks` by `block_type` or `subtype`:

```python
# Find connector blocks
for block in grid.iter_blocks():
    if 'connector' in (block.subtype or '').lower() or 'connector' in (block.block_type or '').lower():
        print(f"  Connector: block_id={block.block_id}, subtype={block.subtype}, "
              f"pos={block.local_position}, enabled={block.state.get('enabled')}")

# Find any block by SE block_type string
target_type = 'MyObjectBuilder_ShipConnector'
for bid, block in grid.blocks.items():
    if block.block_type == target_type:
        print(f"  Found: {bid} → {block.subtype} at {block.local_position}")
```

**Key**: `block.block_id` is the ID attribute (NOT `block.id`). `block.block_type` is the SE type string (NOT `block.type`). `block.subtype` works as-is.

### Get block coordinates (position data)

**Device telemetry does NOT contain position data.** Coordinates come from `grid.blocks` → `BlockInfo`:

```python
# Find a block by type and get its position
for block_id, block in grid.blocks.items():
    if block.block_type == 'MyObjectBuilder_Refinery':
        # local_position: tuple (x, y, z) in METERS relative to grid center
        # bounding_box: dict with 'min'/'max' tuples in WORLD coordinates
        print(f"  Name: {block.name or block.subtype}")
        print(f"  Local position (meters): {block.local_position}")
        print(f"  World bbox min: {block.bounding_box['min']}")
        print(f"  World bbox max: {block.bounding_box['max']}")
        # Convert local meters to grid-local block units (large grid: 1 block = 2.5m)
        block_pos = tuple(round(v / 2.5) for v in block.local_position)
        print(f"  Grid-local block coords: {block_pos}")
```

`BlockInfo` attributes: `block_id`, `block_type`, `subtype`, `name`, `local_position`, `relative_to_grid_center`, `bounding_box`, `mass`, `state`, `is_damaged`.

**Common pattern — find block by user's name (may be localized):**
```python
# User says "базовый очиститель" → Basic Refinery in Russian SE
# Match by block_type or subtype, not localized display name
target_types = {
    'MyObjectBuilder_Refinery',       # Refinery / Basic Refinery (Blast Furnace)
    'MyObjectBuilder_Assembler',      # Assembler / Basic Assembler
    'MyObjectBuilder_Projector',      # Projector
    'MyObjectBuilder_ShipWelder',     # Ship Welder / Nanobot BARS
    'MyObjectBuilder_Drill',          # Drill / Nanobot Drill
}
for bid, block in grid.blocks.items():
    if block.block_type in target_types:
        print(f"  {block.block_type} ({block.subtype}) at {block.local_position}")
```

### Russian → English block name mapping

The user communicates in Russian. SE Russian localization maps common block names:

| Russian (SE localization) | English | block_type |
|---|---|---|
| Базовый очиститель | Basic Refinery (Blast Furnace) | MyObjectBuilder_Refinery |
| Очиститель | Refinery | MyObjectBuilder_Refinery |
| Базовый сборщик | Basic Assembler | MyObjectBuilder_Assembler |
| Сборщик | Assembler | MyObjectBuilder_Assembler |
| Проектор | Projector | MyObjectBuilder_Projector |
| Сварщик | Ship Welder | MyObjectBuilder_ShipWelder |
| Дробилка / Измельчитель | Ship Grinder | MyObjectBuilder_ShipGrinder |
| Буровая установка | Ship Drill | MyObjectBuilder_Drill |
| Батарея | Battery | MyObjectBuilder_BatteryBlock |
| Солнечная панель | Solar Panel | MyObjectBuilder_SolarPanel |
| Реактор | Reactor | MyObjectBuilder_Reactor |
| Генератор кислорода | Oxygen Generator | MyObjectBuilder_OxygenGenerator |
| Гравитационный генератор | Gravity Generator | MyObjectBuilder_GravityGenerator |
| Детектор руды | Ore Detector | MyObjectBuilder_OreDetector |
| Тягач / Двигатель | Thruster | MyObjectBuilder_Thrust |
| Шлюз | Air Vent | MyObjectBuilder_AirVent |
| Текстовая панель | Text Panel | MyObjectBuilder_TextPanel |
| Радар (Nanobot) | Ore Detector (mod) | MyObjectBuilder_OreDetector |
| Система постройки и ремонта | Nanobot Build and Repair | MyObjectBuilder_ShipWelder (subtype: SELtdLargeNanobotBuildAndRepairSystem) |
| Буровая система (Nanobot) | Nanobot Drill System | MyObjectBuilder_Drill (subtype: SELtdLargeNanobotDrillSystem) |
| Соединитель / Коннектор | Ship Connector | MyObjectBuilder_ShipConnector (subtype: Connector) |
| Соединительный блок / Мердж блок / Merge блок | Merge Block | MyObjectBuilder_MergeBlock (subtype: LargeShipMergeBlock) |

**When user names a block in Russian**, search `grid.blocks` by `block_type` and/or `subtype` rather than trying to match the localized display name.

Block types not in DEVICE_TYPE_MAP fall to `GenericDevice` — always inspect `dev.device_type` (the SE string) not just `type(dev).__name__`.

### Check device type registration

```python
from secontrol.base_device import DEVICE_TYPE_MAP
# 31 registered types: reactor, battery, thruster, connector, projector, assembler, etc.
# Unknown types fall to GenericDevice — check dev.device_type for the real SE type string
```

### Read inventories

```python
from secontrol import Grid, RedisEventClient
from secontrol.common import resolve_owner_id, resolve_player_id

# Use explicit grid_id from get_all_grids() — Grid.from_name() does fuzzy search
# and may return the WRONG grid (e.g. "DroneBase" → "DroneBase 2" as first match)
redis = RedisEventClient()
owner_id = resolve_owner_id()
player_id = resolve_player_id(owner_id)

grid = Grid(redis, owner_id, grid_id, player_id, grid_name, auto_wake=True)

# Correct pattern: find containers first, then call inventories()
containers = grid.find_devices_containers()
for dev in containers:
    for inv in dev.inventories():
        if inv.items:
            print(f"[{dev.name or dev.device_type}] ({inv.name})")
            for item in inv.items:
                label = item.display_name or item.subtype or "?"
                print(f"  {item.amount:.3f} × {label}")
```

### Projector / Blueprint operations

```python
projector = grid.devices['<projector_block_id>']  # use exact block_id from grid.devices dict
projector.load_prefab('LargeAssembler')         # built-in SE prefab
projector.load_blueprint_xml(xml_string)        # custom XML blueprint
projector.request_grid_blueprint()              # export current grid to XML
projector.remaining_blocks()                    # blocks left to build
projector.total_blocks                          # total in projection (from telemetry)
projector.is_enabled                            # projection active?
```

**Projector device lookup**: `grid.devices` is a dict of `{block_id: device}`. Find the projector by iterating:
```python
proj = next(d for d in grid.devices.values() if d.device_type == 'projector')
# or by known block_id:
proj = grid.devices['144018214373629345']
```
Do NOT use `grid.get_device("projector")` — it looks up by block_id, not type name.

### Blueprint export and load

```python
import time

# Export
proj.request_grid_blueprint(include_connected=False)  # False = only this grid
time.sleep(5)  # wait for SE to respond
bp = proj.blueprint_snapshot()  # dict with keys: xml, gridName, gridCount, ...
xml = bp['xml']

# Load (may not work — see pitfall below)
proj.load_blueprint_xml(xml, keep=False)  # keep=False replaces current projection
```

**`load_blueprint_xml` works — but requires minimal XML.** If `isProjecting` stays `False`
and `totalBlocks=0` after loading, the cause is almost always **XML bloat** (ComponentContainer
data inflating the XML), not missing plugin support. Strip non-essential tags (see Projection
Alignment section) and retry. Confirmed working on multiple grids (DroneBase, Core1).

**Diagnostic**: if minimal XML still doesn't load, test with a trivial 1-block blueprint:
```python
test_xml = '''<?xml version="1.0" encoding="utf-16"?>
<MyObjectBuilder_ShipBlueprintDefinition xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Id Type="MyObjectBuilder_ShipBlueprintDefinition" Subtype="Test" />
  <DisplayName>Test</DisplayName>
  <CubeGrids><CubeGrid><GridSizeEnum>Large</GridSizeEnum>
    <CubeBlocks>
      <MyObjectBuilder_CubeBlock xsi:type="MyObjectBuilder_Cockpit">
        <SubtypeName>LargeBlockCockpit</SubtypeName>
        <Min x="0" y="0" z="0" />
      </MyObjectBuilder_CubeBlock>
    </CubeBlocks>
  </CubeGrid></CubeGrids>
</MyObjectBuilder_ShipBlueprintDefinition>'''
proj.load_blueprint_xml(test_xml)
time.sleep(5)
proj.update()
# If totalBlocks=1 → import works, problem is your XML content
# If totalBlocks=0 → projector plugin issue, restart SE server
```

**XML encoding**: the `encoding="utf-16"` header in exported XML is fine — the game accepts
both utf-8 and utf-16 declarations regardless of actual byte encoding. Don't waste time
changing the encoding attribute. **However**, Python's `xml.etree.ElementTree.parse()` is
strict — it will raise `ParseError: encoding specified in XML declaration is incorrect` when
parsing a file with `encoding="utf-16"` that's stored as UTF-8 bytes. Fix by replacing the
declaration before parsing: `xml = xml.replace('encoding="utf-16"', 'encoding="utf-8"')`.
This is only needed for Python-side validation/processing; SE itself doesn't care.

**Blueprint XML structure** (ShipBlueprintDefinition):
- `<CubeGrids><CubeGrid>` → `<PositionAndOrientation>` (world pos/orientation of grid)
- `<CubeBlocks>` → list of block XML elements, each with:
  - `xsi:type` — SE block class (e.g. `MyObjectBuilder_Assembler`)
  - `<SubtypeName>` — block variant (e.g. `LargeAssembler`)
  - `<Min x="" y="" z=""/> — grid-local block coordinate (integers)
  - `<BlockOrientation Forward="" Up=""/> — orientation strings ("Right","Up","Forward",etc.)
  - `<ColorMaskHSV x="" y="" z=""/> — paint color

**Block position in XML**: `<Min>` is in **grid-local integer coordinates** (block units).
Device `local_position` from telemetry is in **meters** (1 large block = 2.5m). Convert:
```python
block_pos = tuple(round(v / 2.5) for v in device.local_position)
```

### Projection alignment (CRITICAL)

When loading a blueprint into a projector, the projection must **exactly overlap** the existing grid.
If alignment is wrong, the welder will try to build ALL blocks (including ones already built), wasting resources or corrupting the base.

**⚠️ BLUEPRINT XML BLOAT PROBLEM (discovered 2026-05-14)**:
The `request_grid_blueprint` export can grow massively (e.g. 41KB → 786KB) due to
ComponentContainer data, inventory contents, and nested metadata. **Loading the full
( bloated) XML causes total misalignment — remainingBlocks == totalBlocks even with
correct offset/rotation.** The game's projection system cannot parse the extra data
correctly.

**Solution: Strip to minimal XML before loading.** Keep ONLY these essential tags:
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
                     if (child.tag.split('}')[-1] if '}' in child.tag else child.tag) not in essential_tags]
        for child in to_remove:
            block.remove(child)
minimal_xml = '<?xml version="1.0" encoding="utf-8"?>\r\n' + ET.tostring(root, encoding='unicode')
```
This typically reduces XML from 786KB to ~15KB, and alignment works again.

**⚠️ `set_offset()` / `set_rotation()` are RELATIVE (DELTA) commands, NOT absolute!**
The values you pass tell the server "shift/rotate BY this amount from the current position."
`set_offset(0, 0, 0)` means "don't move" — it does NOT set the offset to origin.
To reach a target offset from current, compute the delta: `dx = target_x - current_x`, etc.
```python
# WRONG — this shifts by (0,0,0), i.e. does nothing:
proj.set_offset(0, 0, 0)

# RIGHT — compute delta to target:
cur = proj.telemetry.get('offset')
dx = target_x - cur['x']
dy = target_y - cur['y']
dz = target_z - cur['z']
proj.set_offset(dx, dy, dz)
```
Same applies to `set_rotation()` and `rotate()` / `move_offset()` (`nudge_offset`).

**⚠️ `set_offset()` / `set_rotation()` do NOT affect projection after `load_blueprint_xml()`**:
The telemetry shows the new values, but `remainingBlocks` does NOT recalculate.
The SE server only uses ProjectionOffset/Rotation from the XML at load time.
To change alignment, you must either:
- Embed the correct values in the XML's projector block before loading
- Or reload the entire blueprint with the new values baked in

**Verified workflow**:
1. Disable the welder BEFORE loading any projection
2. Export blueprint → **strip to minimal XML** (see above)
3. Load minimal blueprint with default offset/rotation
4. Check `remainingBlocks` — if equals `totalBlocks`, alignment is OFF (check XML bloat!)
5. Rotation sweep first (0.5s sleep per step for reliable telemetry).
   **IMPORTANT**: `set_rotation`/`set_offset` are DELTA commands. Each call shifts
   from the CURRENT value. Reset to zero between attempts by computing deltas:
```python
best = (total_blocks, (0,0,0), (0,0,0))
for rx in range(-3, 4):
    for ry in range(-3, 4):
        for rz in range(-3, 4):
            # Reset to zero first, then apply target
            cur_rot = proj.telemetry.get('rotation')
            proj.set_rotation(-cur_rot['x'], -cur_rot['y'], -cur_rot['z'])  # delta to zero
            time.sleep(0.3)
            proj.set_rotation(rx, ry, rz)  # delta from zero = absolute target
            time.sleep(0.5)
            proj.update()
            r = proj.telemetry.get('remainingBlocks', total_blocks)
            if r < best[0]:
                best = (r, (0,0,0), (rx,ry,rz))
            if r == 0: break
```
6. With best rotation, brute-force offset search (step 1, range -20..20):
   Same reset-then-apply pattern:
```python
# Set best rotation (reset + apply)
cur_rot = proj.telemetry.get('rotation')
proj.set_rotation(-cur_rot['x'], -cur_rot['y'], -cur_rot['z'])
time.sleep(0.3)
proj.set_rotation(*best_rot)
time.sleep(0.5)

for x in range(-20, 21):
    for y in range(-20, 21):
        for z in range(-20, 21):
            # Reset offset to zero, then apply target
            cur_off = proj.telemetry.get('offset')
            proj.set_offset(-cur_off['x'], -cur_off['y'], -cur_off['z'])
            time.sleep(0.3)
            proj.set_offset(x, y, z)
            time.sleep(0.3)
            proj.update()
            r = proj.telemetry.get('remainingBlocks', total_blocks)
            if r < best[0]: best = (r, (x,y,z), best_rot)
            if r == 0: break
```
7. Once `remainingBlocks == 0` → alignment VERIFIED. Save the offset/rotation values.
8. For subsequent loads: embed the verified offset/rotation in the XML's projector block:
```python
for block in cb:  # direct children of CubeBlocks
    subtype = block.find('SubtypeName')
    if subtype is not None and subtype.text == 'LargeProjector':
        po = block.find('ProjectionOffset')
        pr = block.find('ProjectionRotation')
        if po is not None:
            po.find('X').text = str(verified_offset[0])
            po.find('Y').text = str(verified_offset[1])
            po.find('Z').text = str(verified_offset[2])
        if pr is not None:
            pr.find('X').text = str(verified_rotation[0])
            pr.find('Y').text = str(verified_rotation[1])
            pr.find('Z').text = str(verified_rotation[2])
```

**Why brute-force**: The correct offset depends on the grid's world position and orientation (non-trivial quaternion). There's no simple formula — the grid center in the blueprint doesn't correspond to the projector's position. Per-grid search is required.

**Shortcut: Place projector at grid origin (0,0,0).** If the projector's `local_position` is `(0.0, 0.0, 0.0)`, then `ProjectionOffset=(0,0,0)` and `ProjectionRotation=(0,0,0)` will align perfectly — the projection origin coincides with the grid origin. No brute-force search needed. This is the recommended approach for new grids.

**`load_blueprint_xml` format requirements (confirmed 2026-05-16):**
- Must include `xmlns:xsd` and `xmlns:xsi` namespace attributes on the root element
- Minimal XML (stripped of ComponentContainer) loads successfully
- Full bloated XML (with ComponentContainer, inventory data) may silently fail — `isProjecting` stays `False`, `totalBlocks=0`
- `blueprint_snapshot()` returns a **dict** (not raw XML): keys include `xml`, `gridName`, `gridCount`, `ok`. Access XML via `snap['xml']`
- `totalBlocks` in telemetry counts only NEW blocks — blocks already built on the grid are excluded. So `totalBlocks=1, remainingBlocks=1` with a 7-block XML means 6 blocks already exist and 1 new block needs building.

**Telemetry timing**: `proj.update()` needs 0.3-1.0s after offset/rotation change to reflect
the new `remainingBlocks`. Too-fast polling (<0.1s) returns stale values and wastes iterations.

**Adding a new block to an existing grid** (full XML template: `references/blueprint-editing.md`):
1. Export blueprint → strip to minimal XML
2. Parse XML, insert new block element into `<CubeBlocks>`
3. Set `<Min>` to desired grid-local position (must not overlap existing blocks)
4. Set `<BlockOrientation>` for correct facing
5. **Embed verified offset/rotation in the projector block** (see step 8 above)
6. Load modified minimal XML
7. Check `remainingBlocks` — should equal number of new blocks (e.g. 1 for a single assembler)
8. Enable welder → wait → disable welder

### Blueprint cloning workflow (saving a grid template)

When the user wants to save a grid's current state as a reusable blueprint for building
copies (clones) — e.g. a docked multi-ship configuration:

1. **Export the grid blueprint** — `request_grid_blueprint()` captures the ENTIRE grid,
   including all docked/connected ships that have merged into a single grid.
2. **Save raw XML** — write to `/workspace/blueprints/<gridname>-raw.sbc`
3. **Strip ComponentContainer** — reduces size (e.g. 240KB → 150KB) for reliable loading.
   Use the standard stripping pattern (see projection-alignment reference).
4. **Fix encoding declaration** — replace `encoding="utf-16"` with `encoding="utf-8"` for
   Python compatibility (SE accepts both, but Python's XML parser is strict).
5. **Validate XML** — parse with `xml.etree.ElementTree`, count blocks, verify block types.
6. **Save stripped version** — write to `/workspace/blueprints/<gridname>-clone.sbc`

**Key insight**: `request_grid_blueprint()` exports the entire physical grid. If two ships
are docked via connectors and merged into one grid, the export contains ALL blocks from both
ships (visible as 2x of each device type). This is the desired behavior for cloning — the
projection will contain the full template.

**Stripping regex** (simpler than XML-tree approach for ComponentContainer):
```python
import re
stripped = re.sub(r'<ComponentContainer>.*?</ComponentContainer>', '', xml, flags=re.DOTALL)
```

### Enable all disabled blocks on a grid

Newly projected/welded ships often come with most blocks disabled (thrusters, conveyors, RC, cockpit).
Only batteries, solar panels, and gyros are typically ON. Use this pattern to enable everything:

```python
grid = prepare_grid("grid_name")  # STRING arg!
enabled = 0
for block in grid.blocks.values():
    state = block.state or {}
    if state.get('enabled') is False:
        dev = grid.get_device_any(block.block_id)
        if dev:
            try:
                dev.set_enabled(True)
                enabled += 1
            except Exception:
                pass
print(f"Enabled {enabled} blocks")
time.sleep(2)  # wait for SE to process
```

**⚠️ Not all blocks can be enabled via API.** The SE mod only handles enable/disable commands for certain block types:
- ✅ **Can enable**: ThrusterDevice, BatteryDevice, GyroDevice, OreDetectorDevice, ShipWelderDevice, NanobotDrillSystemDevice, RefineryDevice, AssemblerDevice, GasGeneratorDevice, GenericDevice (H2 Engine, SolarPanel)
- ❌ **Cannot enable**: MergeBlock, CargoContainer, Cockpit, RemoteControl, Conveyors
These require in-game terminal. The API returns 1 (success) but the block state doesn't change.

### Grid commands

```python
grid.send_grid_command('wake')    # activate telemetry
grid.park_on()                    # parking mode
grid.park_off()                   # exit parking
```

### Device control

```python
dev.enable() / dev.disable()      # toggle on/off
dev.toggle_enabled()              # flip state
```

## Navigation & Flight Control

Full API reference for RemoteControl autopilot, GyroDevice, ThrusterDevice, navigation_tools, and forward-scan obstacle avoidance: `references/navigation-and-flight.md`

Manual flight (gyro+thruster without RemoteControl) — full controller class and tuning guide: `references/manual-flight-controller.md`

### Device-specific APIs

**RemoteControlDevice** (`remote_control`):
- `rc.enable()` → enables **autopilot** (NOT the block itself!)
- `rc.set_enabled(True)` → enables the **block** (on/off). May not persist — check telemetry.
- `rc.disable()` → disables **autopilot**. Block stays on.
- `rc.goto(gps, speed=N, dock=True/False)` → fly to GPS point. Returns immediately; autopilot engages async.
- `rc.gyro_control_on()` / `rc.gyro_control_off()` — required before autopilot can steer.
- `rc.thrusters_on()` / `rc.thrusters_off()` — required before autopilot can thrust.
- `rc.dampeners_on()` / `rc.dampeners_off()` — dampener control.
- `rc.set_collision_avoidance(True/False)` — SE's built-in voxel avoidance.
- `rc.set_mode("oneway")` / `"patrol"` / `"circle"` — flight mode.
- `rc.handbrake_on()` / `rc.handbrake_off()` — handbrake.
- Orientation via telemetry: `tel['orientation']['forward']` etc. (dict with x/y/z).

**⚠️ `rc.enable()` vs `rc.set_enabled(True)` — DIFFERENT things!**
- `rc.enable()` sends `autopilot_enable` — turns on the autopilot system.
- `rc.set_enabled(True)` sends block on/off — powers the block.
- Both may be needed. `rc.enable()` alone won't work if the block is powered off.
- `rc.set_enabled(True)` may return 1 (success) but telemetry still shows `enabled: False`
  — some blocks (RC, Cockpit, Conveyors) cannot be enabled via API. Must be enabled in-game.

**GyroDevice** (`gyro`):
- `gyro.set_override(pitch=0.0, yaw=0.0, roll=0.0)` — keyword-only args, values -1.0 to 1.0.
- `gyro.clear_override()` — removes all override.
- `gyro.aim_vector({"x": dx, "y": dy, "z": dz})` — aim ship's forward at world vector.
- `gyro.align_vector({"x": dx, "y": dy, "z": dz})` — same as aim_vector.

**ThrusterDevice** (`thruster`):
- `thruster.set_thrust(override=0.5)` — keyword-only arg, 0.0 to 1.0.
- `thruster.set_thrust(enabled=True/False)` — enable/disable thruster block.
- NO `set_override()` method — use `set_thrust(override=N)` instead.

**ConnectorDevice** (`connector`):
- `conn.connect()` / `conn.disconnect()` — explicit lock/unlock.
- `conn.toggle_connect()` — toggle connection state.
- `conn.set_state(locked=None, enabled=None)` — connector_state command.
- Telemetry keys: `connectorStatus` ("Connected"/"Unconnected"), `connectorIsConnected` (bool),
  `nearbyConnectors` (list), `otherConnectorId`, `otherConnectorGridId`, `otherConnectorName`.
- **Connector has `orientation` in telemetry** — `forward`, `up`, `right` vectors (dict with x/y/z).
  Critical for computing docking approach vectors.

### Quick: fly to GPS point (RemoteControl autopilot)

```python
rc = grid.get_first_device(RemoteControlDevice)

# Enable sequence (REQUIRED before autopilot works):
rc.enable()
rc.gyro_control_on()
rc.thrusters_on()
rc.dampeners_on()
time.sleep(1)

# Configure and fly:
rc.set_mode("oneway")
rc.set_collision_avoidance(False)  # we handle collision ourselves
rc.goto("GPS:Target:123.45:678.90:0.00:", speed=10.0, gps_name="Target")
# Wait for engage:
for _ in range(15):
    time.sleep(0.2); rc.update()
    if rc.telemetry.get("autopilotEnabled"): break
# Stop:
rc.disable()
rc.dampeners_on()
rc.handbrake_on()
```

**⚠️ RC enable sequence is REQUIRED.** Without calling `gyro_control_on()` + `thrusters_on()` before `goto()`, the autopilot engages (`autopilotEnabled=True`) but the ship doesn't move. The SE mod needs these explicit enables to give the RC control over the ship's systems.

### Quick: manual flight via gyro + thruster (no RemoteControl needed)

When there's no RemoteControl on the grid, use CockpitDevice for telemetry + gyro overrides for orientation + thruster overrides for propulsion:

```python
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.thruster_device import ThrusterDevice
from secontrol.tools.navigation_tools import get_world_position, get_orientation, _dot, _normalize

cockpit = grid.get_first_device(CockpitDevice)
gyros = grid.find_devices_by_type(GyroDevice)
thrusters = grid.find_devices_by_type(ThrusterDevice)

cockpit.enable()
cockpit.set_dampeners(False)  # disable for free flight

# Orientation — P controller (same pattern as align_to_up_vector)
basis = get_orientation(cockpit)  # works with CockpitDevice, not just RC
desired_fwd = _normalize((dx, dy, dz))  # direction to target

local_y = _dot(desired_fwd, basis.up)      # how much target is "above"
local_x = _dot(desired_fwd, basis.right)   # how much target is "right"

pitch_cmd = max(-1.0, min(1.0, -local_y * 1.5))
yaw_cmd   = max(-1.0, min(1.0, -local_x * 1.5))

for gyro in gyros:
    gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

# Thrust — only when pointing roughly at target
angle_err = math.acos(max(-1.0, min(1.0, _dot(basis.forward, desired_fwd))))
if angle_err < 0.5:  # ~30 degrees
    for t in thrusters:
        t.set_thrust(override=0.5)
```

**⚠️ Thrusters REQUIRE a pilot or RemoteControl.** Without either, thrusters ignore all override commands. Check cockpit telemetry: `tel.get('hasPilot')` must be `True`, OR there must be a `RemoteControlDevice` on the grid. If `hasPilot=False` and no RC exists, the ship is immovable via API. See pitfall section.

**Orientation P-controller vs PD**: Use pure P-controller (no derivative). Adding D-term to gyro orientation causes oscillation — the `align_to_up_vector` reference implementation uses P-only with `gain=2.0, max_rate=1.0`. The sign convention `pitch = -local_y * gain, yaw = -local_x * gain` is proven correct.

### Quick: obstacle avoidance in space flight

Use `ForwardScanner` pattern — background thread with RadarController beam.

**Two approaches for stopping near an asteroid:**

**A. Voxel-based stopping (PREFERRED):** Fly toward asteroid center, stop when nearest voxel < `stop_distance`. No geometric formulas needed. Scanner measures actual terrain distance. See `references/asteroid-flight-pattern.md` for full implementation.

**B. Geometric approach (legacy):** Compute approach point at `radius + stop_distance` from center, fly to it. Needs `target_distance` comparison to avoid false-positive obstacle detection on target's own voxels. Less accurate because `approxRadius` is often wrong.

**Critical for geometric approach**: scanner must compare voxel distance vs BOTH `OBSTACLE_RANGE` AND `target_distance`. Only stop if voxels are closer than the target AND within obstacle range.

**Critical for both approaches**: scanner must directly `rc.disable()` on detection AND set flag for `cancel_check`. Update scanner state from main thread as ship moves.

**Long-range scan config** (space flight): `bbox 100x100x100, cell_size=100, radius=5000` (~0.3s per scan, detects asteroids at 3-5km).
**Narrow beam config** (close-range): `bbox 20x20x100, cell_size=10` (~5s per scan, 200×200×1000m beam).

Full implementation: `references/navigation-and-flight.md`
Full asteroid flight pattern: `references/asteroid-flight-pattern.md`

### Space docking (connector-to-connector in zero-G)

Full workflow for docking a ship to a base via connectors: `references/space-docking.md`

Quick summary: enable all ship blocks → fly to approach point (CA off) → align with gyro aim_vector → creep and dock (RC goto with dock=True). Key pitfall: collision avoidance must be OFF — base sits on asteroid.

```python
# Quick dock: fly to 15m from base connector, align, dock
rc.set_collision_avoidance(False)
approach = base_pos + base_fwd * 15  # 15m in front of base connector
rc.goto(f"GPS:Approach:{approach[0]}:{approach[1]}:{approach[2]}:", speed=5)
# Wait for arrival, then align:
gyro.aim_vector({"x": desired_fwd[0], "y": desired_fwd[1], "z": desired_fwd[2]})
# Wait for alignment, then dock:
dock = base_pos + base_fwd * 1.5
rc.goto(f"GPS:Dock:{dock[0]}:{dock[1]}:{dock[2]}:", speed=2, dock=True)
# Monitor conn.telemetry['connectorStatus'] == 'Connected'
```

---

## Ore Detector — asteroid scanning

The Ore Detector's SE plugin supports an `asteroids` command that returns nearby asteroid positions.
The `OreDetectorDevice` Python class does NOT have a dedicated method — use `send_command()` directly.

Full protocol and helper function: `references/asteroid-scanning.md`

### Ore Deposit Scanner — scan + save + query tool

Ready-to-use script: `examples/organized/radar/ore_deposit_scanner.py`

**Scan and save** (ore_only=True, avoids 256-cell truncation by filtering Stone):
```bash
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 1000
# → /home/hermeswebui/se-data/scans/ore_scan_<timestamp>.json
# → /home/hermeswebui/se-data/scans/ore_latest.json (always latest)
```

**Find nearest ore from saved scan** (no re-scan needed):
```bash
python examples/organized/radar/ore_deposit_scanner.py --find Gold
python examples/organized/radar/ore_deposit_scanner.py --find Platinum --find_n 5
```

**Use from Python** (importable functions):
```python
from examples.organized.radar.ore_deposit_scanner import find_nearest_ore, load_scan

# Find nearest Gold deposit
results = find_nearest_ore(None, "Gold", n=3)
for r in results:
    print(f"{r['distance']}m — {r['gps']}")

# Load full scan data
data = load_scan()  # reads ore_latest.json
for cl in data['clusters']:
    print(f"{cl['ore_type']}: {cl['deposit_count']} deposits at {cl['center']}")

# Custom origin (e.g. from another grid position)
results = find_nearest_ore(None, "Iron", from_position=[100000, 80000, -130000])
```

**Data storage**: `/home/hermeswebui/se-data/scans/` (outside git repo)

**JSON structure**:
```json
{
  "scan_time": "ISO timestamp",
  "grid": {"name": "...", "id": "..."},
  "ship_position": [x, y, z],
  "scan_config": {"radius": 1000, "cell_size": 10, "ore_only": true},
  "ore_summary": {"Gold": {"count": 16, "closest_m": 538.7, "max_content": 255}},
  "clusters": [{"ore_type": "Gold", "center": [x,y,z], "deposit_count": 6, "spread_m": 24.5}],
  "gps_markers": ["GPS:Gold_3:x:y:z:#FF8800:"],
  "all_deposits": [{"ore_type": "Gold", "position": [x,y,z], "content": 255, "distance_from_ship": 538.7}]
}
```

**Key pitfall**: without `ore_only=True`, Stone fills the 256-cell buffer → valuable ores truncated. Always use ore_only=True for resource scanning.

**Ready-to-use ore scanner script**: `scripts/ore_deposit_scanner.py` — scans deposits with `ore_only=True`, clusters them, generates GPS markers, saves JSON. Run: `python scripts/ore_deposit_scanner.py --grid <name>`. Output goes to `/home/hermeswebui/se-data/scans/` (outside git repo).

**Data storage**: SE game data (scans, blueprints, etc.) should be stored outside the git repo at `/home/hermeswebui/se-data/`. Do not write scan results or blueprints into the `/workspace` repo directory.

**Full asteroid flight pattern** (scan → approach → fly_to_point): `references/asteroid-flight-pattern.md`

```python
from secontrol.devices.ore_detector_device import OreDetectorDevice

radar = grid.get_first_device(OreDetectorDevice)
radar.send_command({
    "cmd": "asteroids",
    "targetId": int(radar.device_id),
    "state": {"radius": 50000.0, "limit": 320, "includePlanets": False},
})
# Poll telemetry for asteroidIndex with ready=True and new revision
```

Aliases the plugin may accept: `asteroids`, `asteroid_index`, `list_asteroids`.

## RadarController — ore-only scan mode (v0.3.1+)

The `RadarController` supports `ore_only=True` — scans only ore deposits, skipping stone/empty voxels. Faster and more targeted than full voxel scans.

**⚠️ ALWAYS use `ore_only=True` for ore scanning.** Without it, Stone voxels fill the 256-cell `oreCells` buffer, pushing out valuable ores (see Pitfalls: oreCells truncation).

```python
from secontrol.controllers.radar_controller import RadarController

# Ore-only scan — returns ONLY valuable ore cells, no Stone
ore_ctrl = RadarController(radar, ore_only=True, radius=1000, cell_size=10, boundingBoxY=1000)
solid, meta, contacts, ore_cells = ore_ctrl.scan_voxels()

# Two-pass pattern: ore first, then full voxels
ore_ctrl = RadarController(radar, ore_only=True, radius=1000, cell_size=10, boundingBoxY=1000)
ore_solid, ore_meta, ore_contacts, ore_cells = ore_ctrl.scan_voxels()

voxel_ctrl = RadarController(radar, ore_only=False, radius=300, cell_size=10, fullSolidScan=True)
vox_solid, vox_meta, vox_contacts, vox_ore = voxel_ctrl.scan_voxels()
```

The `ore_only` parameter maps to `oreOnly: true` in the scan command sent to the SE plugin. The `OreDetectorDevice.scan()` method also accepts `ore_only=True` directly.

**New RadarController internals (v0.3.1+, confirmed live 2026-05-17):**
- `_radar_marker()` — extracts revision/timestamp from radar raw data for dedup
- `_latest_radar_snapshot()` — gets freshest radar data from telemetry or snapshot
- `_solid_points_from_raw()` — parses both `solidPoints[]` (XYZ) and `solid[]` (flat int index) formats
- `budget_ms_per_tick` parameter — controls per-tick scan budget for performance tuning
- `filter_no_stone` — filters out Stone ore cells (default True)

**New OreDetectorDevice methods (v0.3.1+, confirmed live 2026-05-17):**
- `ore_only()` — property, checks if scanner is in ore-only mode via `telemetry['scan']['oreOnly']`
- `scan(ore_only=True)` — sends `oreOnly` flag in scan state
- `scan(fastScanMaxRadius=N)` — limits fast scan radius
- `scan(reset_active_scan=True)` — force-restart a stuck/in-progress scan (v0.3.2+, 2026-05-17)

**RadarController scan completion (v0.3.2+, 2026-05-17):**

Voxel distance diagnostics (measuring distances to nearest voxels): `references/voxel-distance-diagnostics.md`

- Server now sends `scan.done=True` in telemetry when scan completes (not just progressPercent>=99.9)
- RadarController checks `candidate.get("done")` for instant completion detection — avoids post-scan wait
- Default `boundingBox` increased from 500³ to 5000³ (catches more terrain by default)
- Metadata now includes `radius` and `policyMaxRadius` from server response

**Two-pass ore scanning pattern** (ore first, full geometry second):
```python
# Pass 1: ore_only — fast, finds all ore deposits
ore_ctrl = RadarController(radar, ore_only=True, radius=1000, cell_size=10,
                           boundingBoxX=3000, boundingBoxZ=3000)
ore_solid, ore_meta, ore_contacts, ore_cells = ore_ctrl.scan_voxels()

# Pass 2: full voxels — solid geometry for visualization/navigation
voxel_ctrl = RadarController(radar, ore_only=False, radius=300, cell_size=10,
                             boundingBoxX=3000, boundingBoxZ=3000)
vox_solid, vox_meta, vox_contacts, vox_ore = voxel_ctrl.scan_voxels()

# Merge: ore data from pass 1, geometry from pass 2
# ore_cells has better ore data (dedicated scan), vox_solid has full solid geometry
```
Use `boundingBoxY` to control vertical scan depth (default=5000, can reduce to 1000 for flat terrain).
Cancel any previous scan before starting: `radar.cancel_scan()` + `time.sleep(0.2)`.

## Ore Detector — telemetry keys for player/grid detection

Ore Detector's `telemetry` has these keys for external awareness:

```python
t = ore_detector.telemetry

# Scan configuration (can be changed in-game or via set_property)
scan = t['scan']
scan['includePlayers']   # bool — scan for players
scan['includeGrids']     # bool — scan for other grids
scan['inProgress']       # bool — scan currently running
scan['requestPending']   # bool — scan queued

# Detection results
t['players']             # list of player entries — empty if no players nearby
t['detectedgrids']       # list of grid entries — each is dict/list with gridId + name
t['detectedores']        # list of ore vein entries (voxels)

# Misc
t['broadcast']           # bool — broadcasting to GPS markers
t['gravityVector']       # [x, y, z] in m/s²
t['isWorking']           # bool — block functional
t['load']                # performance: avgMs, peakMs per update/commands window
```

**Common issue**: `t['players']` is empty NOT because no players are nearby, but because
`scan['includePlayers']` is `False`. Small Block Ore Detector defaults vary by modpack.
Enable `includePlayers` and `includeGrids` in the in-game terminal to get detection data.

### OreDetectorDevice methods for ore scanning

The `OreDetectorDevice` class exposes several methods beyond basic `scan()`:

```python
radar = grid.get_first_device(OreDetectorDevice)

# Ore deposit cells (list of detected ore veins with positions)
cells = radar.ore_cells()         # returns list, empty if no voxels in range

# Detected contacts (players, grids, ore — combined)
contacts = radar.contacts()       # returns list

# Scan and wait for results (blocking)
result = radar.scan_and_wait(timeout=10)  # returns dict

# Long-running ore monitor (prints to stdout, blocks forever — NOT for use in execute_code)
radar.monitor_ore()               # DO NOT call from execute_code — it blocks for minutes

# Current scan radius
radius = radar.scan_radius()      # returns current range value
```

**All ore-related methods return empty data when `scan.includeVoxels` is `False`.**
Always verify the scan config before calling these methods.

**Detected grids format**: `detectedgrids` is a list where each entry may be a dict
(`{'gridId': '...', 'name': '...'}`) or a list/tuple. Always check `isinstance`:
```python
for dg in detected_grids:
    if isinstance(dg, dict):
        g_id   = str(dg.get('gridId', ''))
        g_name = dg.get('name', g_id)
    else:
        g_id   = str(dg[0]) if isinstance(dg, (list, tuple)) else str(dg)
        g_name = str(dg[1]) if isinstance(dg, (list, tuple)) and len(dg) > 1 else g_id
```

## Monitoring pipeline — cron-based scanner + alert agent

A reusable pattern for continuous SE monitoring without keeping an agent running:

### Architecture (3 scripts)

```
se_player_scan.py    (cron: every 5m, no_agent=True)
  └─→ scans all grids via OreDetector telemetry
      ├─ writes logs/scan_YYYY-MM-DD.jsonl  (full scan log)
      ├─ writes logs/active_alert.json      (current threat state)
      └─ reads OWN_GRID_IDS to classify detected grids as foreign

se_alert_watcher.py  (cron: every 1m, no_agent=True)
  └─→ reads active_alert.json
      if threats present AND not yet processed
          └─→ spawns se_alert_agent.py (WITH agent)

se_alert_agent.py    (runs on-demand, WITH agent)
  └─→ assess_risk(), gather grid positions, write journal.jsonl
```

### Required env bootstrap in standalone scripts

Cron scripts run outside the `execute_code` sandbox and don't auto-load `.env`:

```python
import os, sys

WORKSPACE = "/workspace"   # hardcoded path
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

### Cron registration (no_agent=True)

**Important**: `hermes kanban create` takes `title` as a positional arg — see references/hermes-kanban-subprocess.md for the correct subprocess pattern and pitfalls.

```bash
# Script path must be relative to ~/.hermes/scripts/ — no absolute paths!
cronjob create --name "SE Scanner" --script "se_player_scan.py" \
    --schedule "every 5m" --repeat forever --no_agent true

cronjob create --name "SE Watcher" --script "se_alert_watcher.py" \
    --schedule "every 1m" --repeat forever --no_agent true
```

### Required pip packages for system Python

Before cron scripts can run, install dependencies into the system Python:
```bash
pip3 install python-dotenv redis
```
(`execute_code` sandbox has its own Python; cron scripts use the system Python at `/usr/local/bin/python3`.)

### Log files

```
~/.hermes/scripts/logs/
  scan_YYYY-MM-DD.jsonl    — all scan results, one JSONL per run
  active_alert.json        — current threat state (written by scanner)
  processed_alerts.json    — dedup: {alert_hash → timestamp}
  journal.jsonl            — all handled incidents (written by agent)
```

### Risk levels

| Level | Trigger |
|-------|---------|
| CRITICAL | Foreign grid detected (gridId not in OWN_GRID_IDS) |
| HIGH | Player(s) detected |
| LOW | Nothing found |

### Own grid IDs (maintain this list!)

Currently known:
- `134540402238780591` — DroneBase 2
- `138748817302648345` — DroneBase
- `74055729860857332` — taburet3
- `98945391841930411` — taburet2
- `125173132660614842` — taburet5
- `82069157247683112` — Respawn Rover
- `143139590779134749` — Core1
- `118163643286714656` — skynet-baza1
- `127817843801970018` — skynet-baza0
- `91207270182100228` — skynet-baza0 (new, after recreation)
- `76365856444180915` — skynet-baza2
- `121847557547546902` — skynet-farpost0
- `125173132660614842` — taburet5

Update `OWN_GRID_IDS` in `se_player_scan.py` when new grids are added.

## Ore Detector — player & foreign grid detection

Ore Detectors (SmallBlockOreDetector / LargeBlockOreDetector) can detect players and
grids — but this is a separate scan mode from ore scanning, controlled by two flags:

```python
for dev in grid.devices.values():
    if dev.device_type == 'ore_detector':
        scan = dev.telemetry.get('scan', {})
        print(f"  includePlayers={scan.get('includePlayers')}")
        print(f"  includeGrids={scan.get('includeGrids')}")
        print(f"  includeVoxels={scan.get('includeVoxels')}")
```

| Flag | What it enables | Default |
|------|----------------|---------|
| `scan.includePlayers` | Detects players in range | often `False` |
| `scan.includeGrids` | Detects other grids | often `False` |
| `scan.includeVoxels` | Detects ore voxels | usually `True` |

**The telemetry fields `players` and `detectedgrids` are EMPTY** unless the respective
`includePlayers` / `includeGrids` flags are `True` AND a scan has completed recently.
There are no `radar` or `surveillance` device types in vanilla SE — Ore Detector
is the only built-in device for player/grid awareness.

**To enable detection:** in the Space Engineers terminal/PB, toggle:
- `Show Players` → `On`
- `Show Other Grids` → `On`
- `Include Voxels` → `On` (keep for ore scanning)

⚠️ **Ore deposit data (oreCells) is available via Redis as of v0.3.1+.** The `radar` telemetry key now contains `oreCells` with deposit positions and types. Use `RadarController.extract_solid()` or `ore_only=True` mode to get ore data programmatically. Previously (pre-v0.3.1) this data was client-side HUD only — no longer the case.

Then wait for the detector to run a scan cycle. The `scan.inProgress` field shows
whether a scan is currently running.

**Common trap:** `detectedgrids` returns empty even when the flag is on because the
scan hasn't completed yet, or because no grids are within range. Small Block Ore Detector
has a relatively short range (~50m). Large Block is longer (~200m). Both require line
of sight (no thick armor blocking).

**`detectedgrids` format:** can be a list of strings, list of dicts, or list of lists
depending on SE version. Always check `isinstance()` before indexing.

## Analyzing base readiness (drone base construction checklist)

When asked "what's on the base", "what's missing", or "is it ready to build":

1. **List grids** → `get_all_grids()` → identify base vs ship vs rover by name/device mix
2. **Inspect all blocks** → enumerate `grid.blocks` dict (block_id → BlockInfo) to see every SE block including GenericDevice types
3. **Enumerate all devices** → `find_enabled_devices()` + `find_devices_by_type()` → build inventory of capabilities
4. **Check containers** → `find_devices_containers()` → read inventories for resources
5. **Check Projector** → `get_device_any("projector")` → `telemetry['isProjecting']`, `remainingBlocks`
6. **Check ShipWelder** → `get_device_any("ship_welder")` → enabled, `currentVolume` (nanobot resources)
7. **Cross-reference against needed blocks**:

| Module | Required blocks |
|--------|-----------------|
| Mining | NanobotDrillSystem, OreDetector |
| Refining | Refinery (or SurvivalKit as fallback) |
| Assembly | Assembler |
| Construction | Projector + ShipWelder |
| Power | SolarPanel, Battery, Reactor |
| Life support | OxygenGenerator, OxygenTank, AirVent |

8. **Note damaged/non-functional blocks** — `block.state['functional'] == False` means broken armor or incomplete blocks. Common on bases that tried to project and ran out of resources.

## Construction planning workflow

To build a missing block on a base:

1. **Check resources** — are containers empty? → need mining or transfer first
2. **Check refining** — is there Refinery or Survival Kit? → refine ore → ingots
3. **Check assembly** — is there Assembler or Survival Kit? → ingots → components
4. **Check projector** — is there a blueprint loaded? → `load_prefab()` or `load_blueprint_xml()`
5. **Check welding** — is ShipWelder enabled? → auto-builds projected blocks
6. **Monitor progress** — `projector.remaining_blocks` → 0 = done

## Nanobot Drill System — area reach and offset

The drill area is a cube centered at an offset from the block, in **ship-local coordinates**.

### Max drill reach formula

```
Макс. дальность от блока = (размер_зоны / 2) + |смещение|
```

| Config | Area | Offset | Max reach from block |
|--------|------|--------|---------------------|
| Default | 75×75×75m | 0 | ~37.5m |
| Planet harvest | 75×75×75m | +50 (down) | ~87.5m |
| Extended | 250×250×250m | ±100 | ~225m |

### Adjustable parameters

| Property | Action methods | Default |
|----------|---------------|---------|
| `Drill.AreaWidth` | `increase_area_width()` / `decrease_area_width()` | ~75m |
| `Drill.AreaHeight` | `increase_area_height()` / `decrease_area_height()` | ~75m |
| `Drill.AreaDepth` | `increase_area_depth()` / `decrease_area_depth()` | ~75m |
| `Drill.AreaOffsetUpDown` | `increase_area_offset_up_down()` / `decrease_area_offset_up_down()` | 0 |
| `Drill.AreaOffsetLeftRight` | `increase_area_offset_left_right()` / `decrease_area_offset_left_right()` | 0 |
| `Drill.AreaOffsetFrontBack` | `increase_area_offset_front_back()` / `decrease_area_offset_front_back()` | 0 |

All can be set directly via `drill.set_property("AreaOffsetUpDown", 50.0)` or `drill.set_property("AreaWidth", 250.0)`.

### Practical limits (tested via API)

- **Offset**: works up to ±100-150m (beyond that, area loses voxel contact)
- **Area dimensions**: up to 250m per axis (larger = slower scan)
- **Realistic max reach**: ~150-200m from the block with aggressive settings
- `set_property` accepts any float — hard limits are in the SE mod itself

### Planet harvest pattern (from examples)

```python
# Drone flies to resource point at FLY_ALTITUDE=50m above surface
# Then sets drill area offset to reach ground:
drill.set_property("AreaOffsetUpDown", FLY_ALTITUDE + EXTRA_DEPTH)  # e.g. 50
```

The `harvest_full.py` and `simple_nano_focus_to_res.py` examples in `examples/organized/autopilot/harvest/` demonstrate the full pattern: search resource → fly to it → offset drill area → mine → return to base.

### Space drilling offset sweep (no gravity)

```python
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

## Nanobot Drill System — Mining Workflow (tested 2026-05-17)

### Complete space mining workflow (asteroid ore)

```python
# === 1. Navigate to ore deposit ===
gold = (98977.14, 81034.139, -131244.897)  # from ore detector scan
rc.enable(); rc.gyro_control_on(); rc.thrusters_on(); rc.dampeners_on()
rc.set_mode("oneway"); rc.set_collision_avoidance(False)
rc.goto(f"GPS:Ore:{gold[0]}:{gold[1]}:{gold[2]}:", speed=15.0, gps_name="Ore")
# Monitor: when dist < 40m, disable autopilot and let dampeners stop
# (autopilot overshoots in space due to inertia)
while dist > 40:
    time.sleep(2); rc.update(); dist = compute_dist(rc, gold)
rc.disable(); time.sleep(1); rc.enable(); rc.dampeners_on()
# Wait for speed < 0.3 m/s

# === 2. Compute drill area offset ===
# Drill block offset from RC in local meters (check grid.blocks for drill local_position)
# Example: drill at (0, 5, -2.5), RC at (2.5, 2.5, -7.5) → offset = (-2.5, 2.5, 5.0)
drill_world = rc_world + offset_in_world_coords  # use RC orientation vectors
ddx, ddy, ddz = gold - drill_world  # vector from drill to ore

# Project onto ship-local axes
local_fwd  = ddx*fwd['x'] + ddy*fwd['y'] + ddz*fwd['z']
local_up    = ddx*up['x']  + ddy*up['y']  + ddz*up['z']
local_right = ddx*right['x'] + ddy*right['y'] + ddz*right['z']

# === 3. Configure drill ===
drill.set_property("AreaOffsetUpDown", local_up)
drill.set_property("AreaOffsetFrontBack", local_fwd)
drill.set_property("AreaOffsetLeftRight", local_right)
drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})  # 2=Drill!
drill.set_use_conveyor(True)

# === 4. Start mining (CRITICAL SEQUENCE) ===
drill.set_property("ScriptControlled", False)  # MUST be False for auto-mining!
drill.turn_on()
drill.start_drilling()  # REQUIRED — without this, drill has targets but CurrentTarget=None

# === 5. Monitor ===
# drill.update(); tel = drill.telemetry
# tel['drill_possibledrilltargets'] — list of detected ore targets
# props['Drill.CurrentDrillTarget'] — active mining target (None = idle)
# tel['content'] / drill.inventories() — collected material
```

### ⚠️ `ScriptControlled` is the KEY setting

| ScriptControlled | Behavior |
|---|---|
| `True` | Drill reports targets via telemetry but **waits for explicit commands** — `CurrentDrillTarget` stays `None`, no mining happens |
| `False` | Drill **auto-detects and mines** targets — `CurrentDrillTarget` shows active target, ore accumulates |

**Always set `ScriptControlled=False` for mining.** The `True` mode is only for advanced scripted control where you manually select targets.

### ⚠️ `start_drilling()` is REQUIRED

Calling `turn_on()` alone is NOT sufficient. The drill powers on but remains idle.
You MUST call `start_drilling()` after `turn_on()` to begin actual mining.

Sequence: `set_property("ScriptControlled", False)` → `turn_on()` → `start_drilling()`

### Area offset in space (no gravity vector)

In space, there's no gravity to project. Instead:
1. Get drill block world position (from RC world + drill local_position offset via RC orientation)
2. Compute vector from drill to ore: `(gold - drill_world)`
3. Project onto ship axes using RC orientation (forward, up, right)
4. Set `AreaOffsetUpDown`, `AreaOffsetFrontBack`, `AreaOffsetLeftRight`

### Area property limitations

- `set_property("AreaWidth", 250.0)` returns success but **does NOT change the value** (stays at 75)
- `send_command({"cmd": "set", "payload": {"property": "Drill.AreaWidth", "value": 250}}` also fails
- Only `AreaWidth_Increase` / `AreaHeight_Increase` / `AreaDepth_Increase` actions work (incremental)
- Default area: 75×75×75m for large grid Nanobot Drill

### Finding ore deposits

1. Use OreDetector `asteroids` command to find nearby asteroids
2. Gold ore is typically INSIDE asteroids (within `approxRadius`)
3. Ore detector `detectedores` shows ore vein positions (world coords)
4. The drill must be ON the asteroid surface for the area to intersect voxels

## Nanobot Drill System — diagnosis workflow

When the drill isn't collecting, check in this order:

1. **Check ScriptControlled** — if `True`, drill won't auto-mine. Set to `False`.
2. **Check work mode** — `get_work_mode()` returns "Drill", "Collect", or "Fill".
   But `set_work_mode()` has a **known bug**: drill/collect values are swapped.
   Use raw command instead: `drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})` (2=Drill, 1=Collect, 0=Fill).
3. **Check PossibleDrillTargets** in telemetry — if empty, no voxels in the drill's area.
   The drill area is 75×75×75m for large grid. If the drone is near but not on the surface,
   the area may miss the voxels.
4. **Check `start_drilling()` was called** — `turn_on()` alone is not enough.
5. **Offset the drill area along the gravity vector** — this is the key trick:
   ```python
   import math
   rc = next(d for d in grid.devices.values() if d.device_type == 'remote_control')
   grav = rc.telemetry.get('gravitationalVector', {})
   gx, gy, gz = grav['x'], grav['y'], grav['z']
   mag = math.sqrt(gx**2 + gy**2 + gz**2)
   # Project gravity onto ship axes
   orient = rc.telemetry.get('orientation', {})
   fwd = orient['forward']; up = orient['up']; left = orient['left']
   g_up = gx*up['x'] + gy*up['y'] + gz*up['z']      # negative = gravity pulls down
   g_left = gx*left['x'] + gy*left['y'] + gz*left['z']
   g_fwd = gx*fwd['x'] + gy*fwd['y'] + gz*fwd['z']
   # Move drill area toward gravity (positive UpDown = ship "up" = opposite of gravity)
   drill.set_property("AreaOffsetUpDown", -g_up * 5)   # scale factor as needed
   drill.set_property("AreaOffsetLeftRight", -g_left * 5)
   drill.set_property("AreaOffsetFrontBack", -g_fwd * 5)
   ```
   Or simply use `increase_area_offset_up_down()` action repeatedly to move the area.
   After adjusting, wait 2-3s and re-check `telemetry['drill_possibledrilltargets']`.

4. **Check ComponentClassList** — `['1;False', ...]` means class 1 (stone/gravel) is disabled.
   This is a read-only mod property; may require in-game UI to toggle.
   Despite this, stone mining still works if the drill is in Drill mode (WorkMode=2).

5. **Check ore filters** — `debug_get_enabled_known_ores()` shows which ores are allowed.
   All ores including stone are enabled by default in DrillPriorityList.

## Iron from stone

Stone voxels contain iron (and other base ores). The Nanobot Drill can mine stone voxels
when no iron ore deposit is nearby. Stone is index 0 in the ore priority list and is
enabled by default. No special ore filter needed — just ensure the drill is on the surface
and in Drill mode (WorkMode=2).

### Safe welding / construction workflow

**ALWAYS** follow this sequence when using projector + nanobot welder:

1. **Disable welder first** — `welder.set_enabled(False)`. If the welder is active during projection loading, it may start welding blocks in wrong positions immediately.
2. **Take block snapshot** — record all block IDs, types, and positions before any changes:
```python
import json
snapshot = {}
for bid, block in grid.blocks.items():
    block_pos = tuple(round(v / 2.5) for v in block.local_position) if block.local_position else None
    snapshot[bid] = {'type': block.block_type, 'subtype': block.subtype, 'pos': block_pos}
with open('/tmp/block_snapshot.json', 'w') as f:
    json.dump(snapshot, f, indent=2, default=str)
```
3. **Load blueprint with VERIFIED alignment** — use pre-confirmed offset/rotation values
4. **Verify `remainingBlocks`** — must equal expected count (e.g. 1 for one new block). If it equals totalBlocks → alignment is WRONG, clear projection and redo alignment search.
5. **Enable welder** — `welder.set_enabled(True)`
6. **Monitor** — poll `proj.remaining_blocks()` until 0
7. **Disable welder** — `welder.set_enabled(False)`
8. **Compare blocks** — re-enumerate blocks and diff against snapshot to verify only expected blocks were added

### Disassembly mode (Nanobot BARS)

The Nanobot Build And Repair System can **disassemble** blocks painted a specific color:

1. **Paint target blocks** with the disassembly color (via `paint_block` — see pitfall on HSV normalization)
2. **In-game**: open Nanobot terminal → set mode to Grind → set Grind Color → enable Use Grind Color
3. **Nanobot starts disassembly** of blocks matching that color
4. **Disable welder** when done

**⚠️ BARS telemetry does NOT expose grind state.** Fields like `buildandrepair_grindcolor`, `buildandrepair_mode`, `possibleGrindTargets`, `currentGrindTarget` are **absent from Redis telemetry entirely** (not even None). You cannot read or verify grind color, mode, or targets through the API. All grind configuration must happen in-game. Only `paint_block()` works via API (painting the block itself).

## Base survival audit — concrete script pattern

When asked "does this base have enough for survival" or "what's missing", run this sequence:

```python
import os, sys
from dotenv import load_dotenv
load_dotenv('/workspace/.env')
sys.path.insert(0, '/workspace/src')

from secontrol.common import prepare_grid
grid = prepare_grid('GridNameOrID')

# 1. Block inventory (catches everything including GenericDevice types)
for bid, block in sorted(grid.blocks.items(), key=lambda x: x[1].block_type or ''):
    functional = "✓" if block.state.get('functional') else "✗"
    enabled = "ON" if block.state.get('enabled') else "OFF"
    print(f"  [{block.block_type}] '{block.subtype}' | {functional} {enabled}")

# 2. Devices with safe telemetry access
for dev in grid.find_enabled_devices():
    t = dev.telemetry or {}  # ← ALWAYS guard: some devices return None
    print(f"  {dev.device_type}: enabled={dev.is_enabled}")  # ← is_enabled is a METHOD, call it

# 3. Inventories
for dev in grid.find_devices_containers():
    for inv in dev.inventories():
        if inv.items:
            for item in inv.items:
                print(f"  {item.display_name or item.subtype}: {item.amount:.3f}")
        else:
            print(f"  [{dev.name or dev.device_type}] пусто")
```

**Survival checklist** (cross-reference against found blocks):

| Module | Required blocks | Critical? |
|--------|----------------|-----------|
| Respawning | SurvivalKit or MedicalRoom | 🔴 YES — no respawn = game over |
| Power | SolarPanel, Battery, Reactor, HydrogenEngine | 🔴 YES |
| Mining | NanobotDrillSystem or ShipDrill + OreDetector | 🟡 needed for resources |
| Refining | Refinery or SurvivalKit | 🟡 needed for ingots |
| Assembly | Assembler or SurvivalKit | 🟡 needed for components |
| Construction | Projector + ShipWelder/BARS | 🟢 for expansion |
| Life support | OxygenGenerator + OxygenTank/HydrogenTank | 🟡 planet-dependent |
| Storage | CargoContainer (must be ON) | 🟡 conveyor network depends on it |

## Pitfalls

- **`Grid.from_name()` does fuzzy search** and returns the **first match**. If multiple grids have similar names (e.g. "DroneBase" and "DroneBase 2"), calling `Grid.from_name("DroneBase")` will return "DroneBase 2". **Always use `get_all_grids()` to list grids with their IDs first, then construct `Grid` directly with explicit `grid_id`** or use the full exact name (e.g. `"DroneBase 2"`).
- **`prepare_grid()` REQUIRES a STRING argument, not int!** Passing an integer like `prepare_grid(76365856444180915)` treats it as `existing_client` (first positional arg), NOT as `grid_id`. The function then resolves the default grid (often the wrong one!). All subsequent operations silently work on the wrong grid. Correct: `prepare_grid("76365856444180915")` (string) or `prepare_grid("skynet-baza2")`. Always verify the "Resolved grid" printout matches expectations.
- **`rc.enable()` enables AUTOPILOT, NOT the block.** `rc.enable()` sends `autopilot_enable` command — it turns on the autopilot system, not the RC block itself. To enable the block (power on/off), use `rc.set_enabled(True)`. However, some blocks (RC, Cockpit, Conveyors) **cannot be enabled via API** — `set_enabled(True)` returns 1 but telemetry still shows `enabled: False`. These must be enabled in-game via the terminal. Always check `rc.telemetry.get('enabled')` after calling `set_enabled()` to verify.
- **RC `enabled: False` doesn't always mean broken.** The RC block may report `enabled: False` but still respond to `goto()` commands — the autopilot system works independently of the block's on/off state. Test with `rc.goto(small_target, speed=5)` and check if speed changes. If speed increases, the RC is functional despite `enabled: False`.
- **Newly built/projected ships have most blocks disabled.** After projection + welding, only batteries, solar panels, and gyros are typically ON. All thrusters, conveyors, RC, cockpit, and functional blocks start disabled. Use the "enable all blocks" pattern before any automation. Not all blocks can be enabled via API (see device enable limitations above).
- **Empty inventories are common.** Always check `inv.items` — many devices report inventory but it's `None` or empty list. Don't assume resources exist.
- **`g.blocks` is a dict** (block_id → BlockInfo), not a list. Do not iterate it directly — use `g.find_devices_containers()` or `g.devices.values()` instead.
- **`dev.is_enabled` is a METHOD, not a property.** Always call it as `dev.is_enabled` (it's a `@property` so no parens needed), but be aware: if you accidentally use it in a context where Python treats it as an attribute access on a different object, it can return a bound method. The safest pattern: `enabled = "ON" if dev.is_enabled else "OFF"`. In the list output from `find_enabled_devices()`, devices are already enabled — don't confuse this with `dev.is_enabled` returning a method object when telemetry is None and you're debugging.
- **`dev.telemetry` can be `None` for many device types.** Batteries, solar panels, hydrogen engines, and oxygen generators frequently return `None` telemetry when the SE server hasn't populated Redis yet or the device just came online. **ALWAYS guard**: `t = dev.telemetry or {}` before calling `t.get(...)`. Failing to guard causes `AttributeError: 'NoneType' object has no attribute 'get'`.
- **Empty inventories are the norm on new/unused bases.** Don't report "error" — report "empty" and flag it as a resource problem. A base with full equipment but zero resources is common and means the player needs to mine or transfer resources first.
- **Redis connection: always load from `/workspace/.env` via dotenv.** Never hardcode Redis credentials or manually set env vars from `.env` content — the password may be truncated or rotated. Pattern:
  ```python
  from dotenv import load_dotenv
  load_dotenv('/workspace/.env')
  ```
  The `execute_code` sandbox does NOT auto-load `.env`, but dotenv handles it correctly including the REDIS_URL with embedded auth.
- **GenericDevice is a catch-all.** If `type(dev).__name__ == 'GenericDevice'`, check `dev.device_type` for the real SE type (e.g. 'survivalkit', 'solarpanel'). These have NO specific methods — only basic `enable()`/`disable()`.
- **Survival Kit is slow.** Refining at x0.2 speed. Fine for one-off builds, painful for bulk production.
- **Connector-based transfers** require the ship to be physically docked. `prepare_grid()` doesn't auto-dock — check connector status first.
- **Redis timeout.** If `prepare_grid()` hangs, Redis may be unreachable. Test with `socket.create_connection((host, 6379), timeout=5)` first.
- **Inline f-strings with quotes in execute_code** cause SyntaxError. Write to a temp file (`/tmp/script.py`) and run via subprocess instead.
- **`set_work_mode()` has swapped drill/collect values** (as of v0.3.0). `set_work_mode("drill")` sends value 1 (=Collect). Use raw `send_command` with `value: 2` for Drill mode instead. See references/nanobot-drill-debugging.md.
- **`ScriptControlled=True` prevents auto-mining.** When `ScriptControlled=True`, the drill reports targets via telemetry but `CurrentDrillTarget` stays `None` — no actual mining happens. **Always set `ScriptControlled=False` for automatic ore mining.** The `True` mode is only for advanced scripted control.
- **`turn_on()` is NOT enough — `start_drilling()` is REQUIRED.** Calling `turn_on()` powers on the drill but it remains idle. You must explicitly call `start_drilling()` after `turn_on()` to begin mining. Correct sequence: `set_property("ScriptControlled", False)` → `turn_on()` → `start_drilling()`.
- **`set_property("AreaWidth")` doesn't change area size.** Returns success but the value stays at 75. `send_command` with `Drill.AreaWidth` also fails. Only `AreaWidth_Increase` / `AreaHeight_Increase` / `AreaDepth_Increase` actions work (incremental steps). Default area: 75×75×75m for large grid.
- **RC autopilot overshoots in space.** The autopilot cannot fully stop the ship due to inertia. When distance < 40m, disable RC (`rc.disable()`), re-enable with dampeners (`rc.enable(); rc.dampeners_on()`), and wait for speed < 0.3 m/s. Without this, the ship drifts past the target at 2-3 m/s.
- **RC goto() engages autopilot asynchronously.** `rc.goto()` returns immediately (result=1) but the autopilot takes 1-3 seconds to engage. Check `rc.telemetry['autopilotEnabled']` in a polling loop. The autopilot may also disengage on its own after a few seconds if the RC block is in a degraded state.
- **Collision avoidance blocks docking to bases on asteroids.** SE's built-in `set_collision_avoidance(True)` detects asteroid voxels near the base and stops the ship 30-50m away. **Always disable collision avoidance for base docking** and handle obstacles manually or accept the risk. The base's connector is ON the asteroid surface — the ship must fly through the "danger zone" to dock.
- **Ore deposits are INSIDE asteroids.** Gold/platinum ore coordinates from ore detector scans are world coordinates of the deposit center, which is INSIDE the asteroid (within `approxRadius`). The drill area must intersect the asteroid's voxel geometry. Fly the ship ONTO the asteroid surface (check `asteroidIndex` surfaceDistance=0) before mining.
- **NEVER fly closer than 50m to ore/asteroid surface.** Ship crashes into asteroid voxels when approaching too close. Stop at ≥50m from ore coordinates. The Nanobot Drill area (75m) reaches far enough to mine from this distance — no need to fly closer.
- **Large AreaOffset values cause 0 targets.** Setting offset of 50+ meters toward ore resulted in 0 drill targets. The mod may clamp large offsets. Use zero offset instead — the 75m drill area reaches ore at 42-46m from the block without any offset. If ore is further, fly closer (but not <50m).
- **Mined ore goes to CargoContainer via conveyor, NOT drill inventory.** With `set_use_conveyor(True)`, the drill's own inventory shows 0 items. Check `ContainerDevice` inventories for collected ore. Don't assume mining failed just because drill inventory is empty.
- **Drill state corruption after many config changes.** After multiple AreaOffset changes, enable/disable cycles, and restart attempts, the drill can report 0 targets even with ore in range. Full reset fixes: stop_drilling → Off → reset offsets to 0 → WorkMode=2 → ScriptControlled=False → turn_on → start_drilling. See `references/nanobot-drill-mining-workflow.md` for exact sequence.
- **Grid IDs can change between sessions.** SE server restarts can reassign grid IDs (e.g. skynet-baza0 changed from 118168110731275470 to 91207270182100228). Always use `get_all_grids()` to find current IDs rather than hardcoding from previous sessions.
- **Projection alignment is per-grid and non-trivial.** The correct offset/rotation depends on the grid's world position and orientation (quaternion). There's no formula — brute-force search is required. Values differ per grid. **NEVER guess offset values** — wrong alignment = welder builds blocks everywhere.
- **Welder MUST be disabled before loading projections.** Nanobot BARS starts welding immediately when a projection appears. If the projection is misaligned, it will corrupt the base before you can react.
- **Blueprint XML may have blocks without `<Min>`.** Armor blocks (1x1x1) may omit `<Min>`, defaulting to position (0,0,0). This is normal.
- **`request_grid_blueprint(include_connected=False)`** — still may return blocks from connected grids if they share a physical connection (via Connector). Check `bp['gridCount']` and block count against expected.
- **Blueprint XML bloat breaks alignment.** ComponentContainer/inventory data can inflate exports from ~40KB to ~800KB. Loading bloated XML causes `remainingBlocks == totalBlocks` for ALL offsets. **Always strip non-essential XML tags before loading** (see Projection Alignment section). If `remainingBlocks` never drops below `totalBlocks` during brute-force, XML is bloated — strip and retry.
- **`set_offset()` / `set_rotation()` do NOT change projection after `load_blueprint_xml()`.** Telemetry shows new values but `remainingBlocks` doesn't recalculate. Embed offset/rotation in the XML projector block before loading.
- **Projector can FREEZE after rapid commands.** After ~30+ rapid `set_offset()`/`set_rotation()` calls (e.g. during brute-force sweep), the projector enters a stuck state: commands return `seq=1` (success), telemetry's `commands.lastMs` updates normally (~16ms), but offset/rotation values DON'T change and `remainingBlocks` stays stale. The SE plugin's command queue gets overwhelmed. **Recovery: restart the SE server or the plugin.** Waiting alone may not fix it — the projector stays frozen indefinitely.
- **`request_grid_blueprint` stops working when projector is frozen.** The same rapid-command overload that freezes offset/rotation also breaks blueprint export — the Redis key never appears, even after 120+ seconds. Both failures share the same root cause (SE plugin overload). Restart fixes both.
- **Not all blocks can be enabled/disabled via API.** The SE mod only handles enable/disable commands for certain block types. Tested results:
  - ✅ **Can enable**: ConnectorDevice, ThrusterDevice, BatteryDevice, GyroDevice, OreDetectorDevice, ShipWelderDevice, NanobotDrillSystemDevice, RefineryDevice, AssemblerDevice, GasGeneratorDevice, HydrogenEngine (GenericDevice), SolarPanel (GenericDevice)
  - ❌ **Cannot enable**: LargeShipMergeBlock, LargeBlockLargeContainer (CargoContainer), LargeBlockCockpitSeat (Cockpit), Conveyors
  The device command channel `se.{player_id}.commands.device.{block_id}` accepts the command (returns 1), but the block state doesn't change. There is no alternative API path — these blocks must be enabled in-game via the terminal. **Merge blocks are the most critical limitation** — they cannot be toggled programmatically, which means docked-ship workflows that rely on merge blocks require manual in-game intervention.
- **ConnectorDevice has lock/connect control methods.** Beyond `enable()`/`disable()`:
  - `set_state(locked=None, enabled=None)` — sends `connector_state` command to lock/unlock the connector
  - `toggle_connect()` — toggles connection state
  - `connect()` / `disconnect()` — explicit connection control
  - `nearbyConnectors` in telemetry — list of connectors within docking range (empty if nothing nearby)
  - `connectorStatus` in telemetry — "Connected" or "Unconnected"
  - `connectorIsConnected` in telemetry — boolean connection state
  - `otherConnectorId` / `otherConnectorName` / `otherConnectorGridId` — info about the connected counterpart (None if unconnected) If `remainingBlocks > 0` but `buildableBlocks == 0`, the projection is completely misaligned — no projected blocks overlap with existing grid geometry. If `buildableBlocks > 0` but less than `remainingBlocks`, alignment is partial — some blocks are in valid positions but not all. Use this to distinguish "alignment off" from "resources missing." **However**, `buildableBlocks == 0` can also mean the projected blocks are physically floating — not adjacent to any existing block. This happens when a blueprint contains a full multi-ship grid (e.g. two docked ships) but one ship has been removed: the missing ship's blocks project in empty space with no adjacent anchor. This is NOT an alignment issue — it's a topology issue. The solution is to ensure the projected blocks touch existing blocks (e.g. via connector/merge block docking), not to adjust offset/rotation.
- **`local_pos = Min * 2.5` (exact, for large grid).** The `local_position` from `BlockInfo` is the Min corner in meters. `Min = round(local_pos / 2.5)` for each axis. Verified: Refinery at Min=(2,0,0) → local_pos=(5.0, 0.0, 0.0); Battery at Min=(-1,0,0) → local_pos=(-2.5, 0.0, 0.0); Solar at Min=(2,2,0) → local_pos=(5.0, 5.0, 0.0). This is the REVERSE of the XML `<Min>` coordinate — use it to compute Min from telemetry when placing new blocks.
- **`iter('MyObjectBuilder_CubeBlock')` on blueprint XML may overcount.** Use `CubeBlocks` direct children instead: `cube_blocks = root.find('.//CubeBlocks'); blocks = list(cube_blocks)` for accurate count.
- **Export may contain duplicate blocks.** `blueprint_snapshot()['xml']` can include the same block twice — once in the main `<CubeBlocks>` and once in a connected-grid section. When parsing for block count or positions, always filter to direct children of `<CubeBlocks>` only: `root.find('.//CubeBlocks')` → `list(cubes)`. Using `root.iter('MyObjectBuilder_CubeBlock')` will double-count.
- **BlockOrientation must match EXACTLY when adding blocks to blueprint XML.** Wrong `Forward`/`Up` values = block doesn't match existing grid geometry → `remainingBlocks` stays > 0 even with correct `Min` position. The only reliable way to get the right orientation: (a) have the user place the block manually in-game, (b) export the blueprint, (c) copy the `<BlockOrientation>` from the export. Guessing orientation (e.g. `Forward="Up" Up="Backward"` vs `Forward="Left" Up="Backward"`) will fail.
- **`isProjecting=False` with `remainingBlocks=0` is NORMAL.** When all projected blocks already exist on the grid, the projector auto-disables projection. This is expected behavior, not an error. `totalBlocks=1, remainingBlocks=0` means the one new block was already built.
- **LargeAssembler is 3×3×3 blocks.** When placing in blueprint XML, the `<Min>` position defines one corner. Verify the 3×3×3 volume doesn't overlap existing blocks by checking all occupied positions.
- **`proj.update()` must be called after changing offset/rotation** to see new `remainingBlocks` value in telemetry.
- **Nanobot BARS disassembly mode** works by color matching — paint the blocks you want removed, configure the disassembly color in CustomData, then enable the welder. Remember to disable it after.
- **Drill area offset is in ship-local coordinates.** The gravity vector from RC telemetry must be projected onto the ship's orientation axes to determine which direction is "down." Use `increase_area_offset_up_down()` action repeatedly if unsure about the math. The area needs to intersect voxels — if PossibleDrillTargets is empty, the offset is wrong.
- **User may be wrong about grid position.** Always verify with telemetry — check `position`, `planetPosition`, and calculate altitude. But DON'T dismiss the user's claim without checking if the coordinate system might be misleading. The altitude calculation `dist - 30000` is an approximation; Mars radius varies.
- **Execute_code sandbox doesn't load .env** — must set `os.environ` explicitly for Redis credentials.
- **`/opt/hermes/.venv/bin/python` may lack `pip` module.** If `execute_code` scripts need to install packages at runtime, use `subprocess.run(['pip', 'install', ...])` with the system pip binary, or run `subprocess.run([sys.executable, '-m', 'ensurepip'])` first. (Hit in session `20260515_060153_18c4b3`)
- **`send_command` with `set` can accidentally toggle OreDetector boolean scan flags.** Sending `{"cmd": "set", "state": {"property": "Range", "value": 200.0}}` (or any `set` command) to an OreDetector can flip `scan.includeVoxels` from `True` to `False` as a side effect. Worse, **you cannot toggle it back via API** — none of `Scan.IncludeVoxels`, `IncludeVoxels`, `includeVoxels`, `Scan.IncludeOres` work, and sending a toggle command has no effect. The fix requires **in-game terminal**: Ore Detector → enable "Show Voxels" / "Include Voxels". **Avoid sending `set` commands to OreDetector unless absolutely necessary.** If you must, check `scan.includeVoxels` before and after, and warn the user to re-enable in-game if it flips.
- **`monitor_ore()` blocks forever** — it enters a long-running loop printing to stdout. NEVER call it from `execute_code` — it will timeout after 300s. Use `ore_cells()`, `contacts()`, or `scan_and_wait(timeout=N)` instead for programmatic ore data.
- **Ore voxel detection requires physical proximity.** `detectedores` and `ore_cells()` return empty even with `includeVoxels=True` if the grid is not close enough to voxel surfaces. Large Ore Detector range is configurable (default ~50m, max ~250m). If the grid is floating in space near an asteroid but not touching it, increase range or move closer. `asteroidIndex` surfaceDistance=0 means the grid IS on the voxel surface.
- **`asteroidIndex` vs `detectedores` are different systems.** The `asteroids` command (via `send_command`) finds asteroid POSITIONS in a 50km radius using the SE plugin — this works regardless of ore detector range. `detectedores` in telemetry shows ORE DEPOSITS within the detector's physical range — requires `includeVoxels=True` AND proximity to voxels. Don't confuse the two.
- **`hermes kanban create` takes `title` as a positional argument, NOT `--title`.** Using `--title "..."` causes hermes to interpret it as a top-level `hermes` flag (not a `kanban create` flag), which fails silently or produces wrong output. Correct: `hermes kanban create "title text" --priority 50 --json`. See references/hermes-kanban-subprocess.md for the full subprocess pattern.
- **Ore Detector ore cells (oreCells) ARE transmitted through Redis (as of v0.3.1+).** The `radar` telemetry key now contains `oreCells` with ore deposit positions and types. `RadarController.extract_solid()` parses them. The `ore_only=True` mode scans only ore deposits. `contacts` are also populated. **Previously** (pre-v0.3.1), `oreCells` and `radar` were always empty — this is no longer the case. Update: if ore cells are still empty, check that `scan.includeVoxels=True` and the grid is close enough to voxel surfaces.
- **`send_command` with `{"cmd": "set", "state": {"property": "Range", "value": N}}` can accidentally toggle `includeVoxels` to False.** The SE plugin's `set` command for ore detector properties is unreliable — it may flip boolean scan flags. Once `includeVoxels` is False, no API command can restore it (tried: `set(True)`, `set(False)`, toggle, property paths like `Scan.IncludeVoxels`, `includeVoxels`, `IncludeVoxels`). Must be re-enabled in-game terminal. Avoid sending `set` property commands to the ore detector unless you specifically intend to change that property.
- **Nanobot Drill auto-disables in space.** The drill periodically sets `enabled=False` on its own — likely due to power management or idle timeout when no targets are found. Re-enable with `drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": True}})`. The drill also needs to be enabled BEFORE it can detect targets (`drill_possibledrilltargets` stays empty while `enabled=False`).
- **Nanobot Drill area is 75×75×75m (large grid), not 25×25×25m.** The default drill area is significantly larger than documented for planetary drills. This means the drill can reach voxels further from the block. If targets are still empty, try increasing `AreaWidth/Height/Depth` to 100-250m or sweeping `AreaOffsetUpDown/FrontBack/LeftRight`.
- **`asteroidIndex` is auto-populated in ore detector telemetry.** No explicit `asteroids` command needed — the data appears automatically with `ready=True`, `count`, and full `items` list. Use this as the primary method for finding nearby asteroids. Each item has `center`, `distance`, `surfaceDistance`, `approxRadius`, `seed`, `loadedNow`, `aabb`. `surfaceDistance=0` means the grid is on the asteroid.
- **Ore Detector `showOnScreen`/`showInTerminal` cannot be set via API.** Sending `{"cmd": "property", "state": {"ShowOnScreen": True}}` returns success but doesn't change the value. These must be toggled in-game.
- **⚠️ Thrusters REQUIRE a pilot or RemoteControl to respond.** Cockpit telemetry `hasPilot: False` + no `RemoteControlDevice` on grid = all `set_thrust(override=N)` commands are silently ignored. The ship appears to have working thrusters (blocks are enabled, commands return `sent=1`) but produces zero acceleration. Check: `cockpit.telemetry.get('hasPilot')` or `cockpit.telemetry.get('isUnderControl')`. If both are False, thrusters are dead. Fix: (a) seat a pilot in the cockpit in-game, or (b) add a Remote Control block. The `controlThrusters: True` telemetry flag means the cockpit CAN control thrusters — but only when there's a pilot or RC. Also: `canControlShip: True` does NOT mean thrusters are active; it only means the cockpit type supports ship control.
- **CockpitDevice provides flight telemetry without RemoteControl.** `CockpitDevice` exposes the same flight-relevant telemetry as `RemoteControlDevice`: `position`, `orientation` (forward/up/right), `linearVelocity`, `angularVelocity`, `speed`, `gravity`, `shipMass`, `dampenersOverride`. Use `get_orientation(cockpit)` and `get_world_position(cockpit)` — they accept any `BaseDevice`, not just RC. The `set_dampeners(enabled: bool)` method is the correct API (not raw `send_command({"cmd": "set_dampeners", ...})`).
- **`CockpitDevice.set_dampeners()` takes a bool, not a dict.** The correct call is `cockpit.set_dampeners(True)` or `cockpit.set_dampeners(False)`. Sending `cockpit.send_command({"cmd": "set_dampeners", "state": "on"})` may work but is non-standard and may break with updates. The underlying command is `{"cmd": "dampeners", "state": {"dampeners": bool}}`.
- **`prepare_grid()` raises `ValueError: Multiple grids found` when duplicate names exist.** If two grids have the same name (e.g. two copies of "skynet-baza0"), `prepare_grid('skynet-baza0')` fails with `Multiple grids found containing 'skynet-baza0': ['skynet-baza0', 'skynet-baza0'] (IDs: [...])`. Fix: use the grid ID directly: `prepare_grid('127817843801970018')`. Check available grids with `get_all_grids()` if unsure.
- **RadarController: two scan configs for different purposes.** (a) `bbox 100x100x5000, cell_size=10` = 1M+ tiles → resets at 0-1.5%, NEVER use this. (b) Narrow beam: `bbox 20x20x100, cell_size=10` = 4,000 tiles, ~5s per scan — close-range obstacle detection. (c) Long-range: `bbox 100x100x100, cell_size=100, radius=5000` = ~1,000 tiles, ~0.3s per scan — detects asteroids at 3-5km. Use (b) for planetary approach, (c) for space flight. See `references/navigation-and-flight.md` for tested configs.
- **ForwardScanner: two stopping approaches.** (A) **Voxel-based (PREFERRED)**: fly toward asteroid center, `arrived = nearest < stop_distance`. No geometric formulas, no `target_distance` comparison needed. The scanner simply measures actual voxel distance and stops when close enough. (B) **Geometric (legacy)**: compute approach point, compare `nearest < OBSTACLE_RANGE AND nearest < target_distance`. Needs `target_distance` tracking from main thread. Less accurate because `approxRadius` is often wrong. For approach (A), set `arrival_distance=9999` in `fly_to_point()` so the scanner (not the arrival threshold) controls when to stop.
- **`solidPoints` are WORLD coordinates, not grid indices.** Each point in the `solid` list from `scan_voxels()` is `[world_x, world_y, world_z]` in SE world space. To compute distance from the ship, subtract ship position: `d = sqrt((pt[0]-ship_pos[0])² + (pt[1]-ship_pos[1])² + (pt[2]-ship_pos[2])²)`. Do NOT treat them as grid indices (they are NOT `[ix, iy, iz]` to be converted via `origin + (idx+0.5)*cell_size`). The `RadarVisualizer` converts them TO indices via `rel = (arr - origin) / cell_size` for occupancy grid building — this confirms they arrive as world coords. Common mistake: using `math.sqrt(p[0]**2 + p[1]**2 + p[2]**2)` treats them as origin-relative vectors, which gives wrong distances when the ship is far from world origin.

- **`fly_to_point()` `arrival_distance=50` causes premature stops on re-approach or when flying toward asteroid center.** Default `arrival_distance=50.0` means the ship considers "arrived" when within 50m of the target. If the ship is already near a previously-computed approach point (e.g. 40m away), it immediately "arrives" without flying further. When flying toward asteroid center with voxel-based stopping, the ship may "arrive" at the center point (which is inside the rock) before the scanner triggers. For precision approaches, use `arrival_distance=5.0` or `arrival_distance=10.0`. For voxel-based stopping, use `arrival_distance=9999` to ensure the scanner controls the stop.
- **ForwardScanner must directly `rc.disable()` on obstacle detection.** Don't rely solely on `cancel_check` callback — `fly_to_point()` polls it each iteration which may be too slow. The scanner thread should immediately call `rc.disable()` + `rc.dampeners_on()` when voxels are detected within OBSTACLE_RANGE, AND set the flag for `cancel_check` to return `True`.
- **`compute_approach_point` must return final stop position from CENTER, not intermediate from ship.** The correct formula: `stop_radius = radius + stop_distance; point = center + direction * stop_radius` (where direction = ship→center normalized). The OLD formula `approach_dist = dist - radius - stop_distance` computed an intermediate point that was wrong when the ship was already close. Verified: with radius=256m, stop_distance=500m, the ship stops at 756m from center = 500m from surface.
- **Gyro orientation: use P-controller only, not PD.** The `align_to_up_vector` reference in navigation_tools uses a pure proportional controller (`pitch = -local_y * gain`, `yaw = -local_x * gain`, `gain=2.0`, `max_rate=1.0`). Adding a derivative term (D-gain) to gyro orientation commands causes wild oscillation — the ship spins continuously because the D-term amplifies noise in the angle error signal. If you need damping, increase `max_rate` clamping instead of adding D.
- **Import path priority: `/workspace/src` on sys.path hides pip-installed package.** If both `/workspace/src/secontrol/` and a pip-installed secontrol exist, adding `sys.path.insert(0, '/workspace/src')` makes Python import the OLD source, hiding newer pip-installed code. This causes `TypeError: RadarController.__init__() got an unexpected keyword argument 'ore_only'` and similar. Fix: don't add `/workspace/src` to sys.path when using `pip install -e /tmp/secontrol-fresh`.
- **`paint_block` HSV normalization — use `hsv=[H, S/100, V/100]` to match in-game grind colors.** The `_normalize_hsv_triplet()` function: H > 1 → /360 (degrees to 0-1), S/V via `_normalize_unit()`: 0→0.0, 0-1→as-is, 1-100→/100, 100-255→/255. SE ColorMaskHSV: x=H(0-1), y=S(-1..1), z=V(-1..1). Game terminal: H(0-360), S(0-100), V(0-100). To match grind color H=255, S=0, V=0: `paint_block(id, hsv=[255, 0.5, 0.5])` → ColorMaskHSV=(0.708, 0.0, 0.0). Using `hsv=[255, 0, 0]` gives ColorMaskHSV=(0.708, -1, -1) which is WRONG (minimum, not neutral). See se-projection-builder skill for full color conversion reference.
- **Redis ACL restricts KEYS and SCAN.** The secontrol Redis user (owner_id as username) cannot run `KEYS` or `SCAN` commands — `NoPermissionError`. Use direct `GET` with known key patterns (e.g. `se:{owner_id}:grids`, `se:{owner_id}:grid:{grid_id}:gridinfo`) instead of trying to enumerate keys.
- **`se:{owner_id}:grids` returns None → SE server is offline.** When the grids key is empty AND known grid telemetry keys (like `se:{owner_id}:grid:{grid_id}:gridinfo`) also return None, the Space Engineers dedicated server is not running or the Redis bridge is disconnected. Don't chase configuration issues — tell the user the server needs to be started.
- **`pip install -e .` may fail on egg-info permissions.** If the `src/secontrol.egg-info` directory is owned by a different user, editable install fails. Workaround: use `PYTHONPATH=src` instead of installing, or `rm -rf src/secontrol.egg-info` and retry.
- **Disk space exhaustion causes cascading failures.** When `/tmp` fills up with `hermes_sandbox_*` directories from `execute_code` runs, you get `[Errno 28] No space left on device`. This blocks `execute_code`, skill file operations, and kanban DB writes. Fix: `rm -rf /tmp/hermes_sandbox_*` to reclaim space. Monitor with `df -h /tmp`.
- **Git repo files owned by different UID — `pip install -e` from fresh clone as workaround.** The `/workspace` repo may have `.git/` and source files owned by UID 1001 (not the current user). No sudo, chmod, chown, or file writes work. `hermes_tools.write_file()` reports `bytes_written: 0` with Permission denied but the outer status says `success` — **always verify writes by reading back**. Workaround: `git clone --depth=1 https://github.com/rootfabric/secontrol.git /tmp/secontrol-fresh && pip install -e /tmp/secontrol-fresh`. This makes Python import from the fresh clone. The `/workspace` source files stay stale but are unused by the runtime. For direct file updates without pip, use the `write_file` function tool (not hermes_tools) which may have elevated permissions.
- **`Grid` object has no `.id` attribute — use `.grid_id` instead.** Also `.name`, `.grid_key`, `.owner_id`, `.player_id`, `.metadata` (raw dict from Redis). The `.metadata['blocks']` list contains full block data (type, subtype, id, state, local_pos, bounding_box, mass) as raw dicts — useful fallback when `.blocks` returns incomplete data or only IDs.
- **API methods may return tuples, strings, or ints — not always objects.** Before calling `.get()`, `.name`, `.text`, or other object methods on a return value, check its type with `type(x)`. Common mistakes: calling `.get()` on a tuple (use indexing instead), `.name` on a string (it's already the name), or `KeyError: 0` from list-indexing a dict. Always check `isinstance(x, dict)` before calling `.get()`.
- **`Grid()` constructor requires 3 positional arguments: `owner_id`, `grid_id`, `player_id`.** Never call `Grid()` without args — use `prepare_grid("grid_name")` or `Grid.from_name("grid_name")` for name-based lookup, or construct explicitly: `Grid(redis, owner_id, grid_id, player_id, grid_name)`.
- **Grid device inventory can change between sessions.** Blocks can be removed, ground down, or destroyed in-game. `get_first_device(OreDetectorDevice)` may return `None` even if the detector was present in a previous session. Always guard for `None` and tell the user which grids currently have the needed device. Use `grid.blocks` with `block_type='MyObjectBuilder_OreDetector'` to confirm.
- **`grid.blocks` may behave differently depending on grid state.** On some grids, iterating `grid.blocks` yields only block IDs (integers), while on others it yields `(block_id, BlockInfo)` pairs. When in doubt, access block details via `grid.metadata['blocks']` which always returns the full raw dict per block.
- **Git pull fails on untracked example files.** If you copied custom scripts (e.g. `space_navigator_v3.py`) into the repo's `examples/` directory, `git pull origin main` will abort with "untracked working tree files would be overwritten by merge". Fix: `rm <conflicting-file> && git pull origin main`, then re-copy if needed. The repo may add its own version of the file in the update.
- **secontrol update workflow.** When user asks to update secontrol from git: `cd /workspace && git pull origin main` → `pip install -e /workspace`. If pull fails on untracked files, remove them first (see pitfall above). Always reinstall with pip after pulling — the editable install needs to refresh.
- **`get_world_position(device)` works with any BaseDevice** (CockpitDevice, RemoteControlDevice, etc). Preferred over manual `telemetry.get('planetPosition')` parsing — handles both dict `{x,y,z}` and list `[x,y,z]` formats, and correctly resolves planet-relative vs world coordinates. Import from `secontrol.tools.navigation_tools`.
- **HOME path varies between contexts.** Interactive sessions typically use `/home/hermeswebui`, but cron/scheduled jobs use `/home/hermes`. Skills, scripts, and configs created in one context may not be found in the other. Always verify `os.environ['HOME']` and use absolute paths when referencing skill/script locations. (3 consecutive sleep-review cron runs failed because the skill was created at `/home/hermeswebui/.hermes/skills/` but cron resolved HOME to `/home/hermes`.)
- **Cron scripts that shell out to `hermes` must use the correct binary path.** The wrapper at `~/.hermes/hermes-agent/hermes` may have a broken shebang if the venv was relocated. Verify with `head -1 <path>` — the shebang interpreter must exist. The working binary is typically at `/app/venv/bin/hermes` (check with `which hermes` or `find / -name hermes -type f`).
