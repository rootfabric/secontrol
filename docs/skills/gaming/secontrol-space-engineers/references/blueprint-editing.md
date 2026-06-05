[← Parent skill: secontrol-space-engineers](../SKILL.md)

# Blueprint XML Editing — Adding Blocks

## Adding a block to an existing blueprint

Pattern: export → parse XML → insert block into `<CubeBlocks>` → strip → load.

### Minimal block XML template (Large Grid)

```xml
<MyObjectBuilder_CubeBlock xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:type="MyObjectBuilder_SolarPanel">
  <SubtypeName>LargeBlockSolarPanel</SubtypeName>
  <EntityId>0</EntityId>
  <Min x="-2" y="0" z="0" />
  <BlockOrientation Forward="Down" Up="Left" />
  <ColorMaskHSV x="0" y="-0.8" z="0" />
  <Owner>144115188075855919</Owner>
  <BuiltBy>144115188075855919</BuiltBy>
  <ShareMode>Faction</ShareMode>
  <ShowOnHUD>false</ShowOnHUD>
  <ShowInTerminal>true</ShowInTerminal>
  <ShowInToolbarConfig>true</ShowInToolbarConfig>
  <ShowInInventory>true</ShowInInventory>
  <NumberInGrid>1</NumberInGrid>
  <Enabled>true</Enabled>
</MyObjectBuilder_CubeBlock>
```

**Required fields for projection**: `SubtypeName`, `Min`, `BlockOrientation`, `EntityId`.
**Owner/BuiltBy**: use the player ID from `grid.player_id`. Without these, the block may
appear but the welder won't build it (ownership mismatch).

### Python pattern

```python
import xml.etree.ElementTree as ET

bp_xml = projector.blueprint_xml()
root = ET.fromstring(bp_xml)
cube_blocks = root.find('.//CubeBlocks')

# Build the new block element
new_block_xml = '''<MyObjectBuilder_CubeBlock xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:type="MyObjectBuilder_SolarPanel">
  <SubtypeName>LargeBlockSolarPanel</SubtypeName>
  <EntityId>0</EntityId>
  <Min x="-2" y="0" z="0" />
  <BlockOrientation Forward="Down" Up="Left" />
  <ColorMaskHSV x="0" y="-0.8" z="0" />
  <Owner>PLAYER_ID_HERE</Owner>
  <BuiltBy>PLAYER_ID_HERE</BuiltBy>
  <ShareMode>Faction</ShareMode>
  <ShowOnHUD>false</ShowOnHUD>
  <ShowInTerminal>true</ShowInTerminal>
  <ShowInToolbarConfig>true</ShowInToolbarConfig>
  <ShowInInventory>true</ShowInInventory>
  <NumberInGrid>1</NumberInGrid>
  <Enabled>true</Enabled>
</MyObjectBuilder_CubeBlock>'''

cube_blocks.append(ET.fromstring(new_block_xml))

# Serialize (strip bloat if needed — see SKILL.md Projection Alignment section)
new_xml = ET.tostring(root, encoding='unicode', xml_declaration=True)
```

### Position placement rules

- `<Min>` is in **grid-local integer block coordinates** (not meters).
- 1 large block = 2.5 meters. `local_position` from `BlockInfo` is in meters.
  Convert: `block_pos = tuple(round(v / 2.5) for v in block.local_position)`
- Adjacent block: offset by 1 in the desired axis (e.g. battery at (-1,0,0) → solar at (-2,0,0)).
- Multi-block devices (Assembler 3×3×3, etc.): `<Min>` is one corner, check all 27 positions.

### BlockOrientation values

Common orientation strings: `"Right"`, `"Left"`, `"Up"`, `"Down"`, `"Forward"`, `"Backward"`.
To match an existing block's orientation, copy its `<BlockOrientation>` directly.

**⚠️ Orientation must match EXACTLY.** A solar panel at `Min=(2,2,0)` with `Forward="Up" Up="Backward"` will NOT match the same panel with `Forward="Left" Up="Backward"`. The game treats different orientations as different blocks. **Never guess orientation** — always export after the user places the block manually, then copy from the export.

**Workflow for getting correct orientation:**
1. User places block in-game
2. Export blueprint: `proj.request_grid_blueprint(include_connected=False)`
3. Parse export, find the block by `SubtypeName` and `EntityId`
4. Copy its `<BlockOrientation Forward="..." Up="..." />` exactly
5. Use in modified XML

### Duplicate blocks in export

`blueprint_snapshot()['xml']` may contain blocks twice — once in the main `<CubeBlocks>` and once in a connected-grid or metadata section. When parsing:
```python
# WRONG — may double-count:
for block in root.iter('MyObjectBuilder_CubeBlock'): ...

# RIGHT — direct children only:
cubes = root.find('.//CubeBlocks')
for block in list(cubes): ...
```

### Common SE block types for xsi:type

| xsi:type | SubtypeName | Notes |
|----------|-------------|-------|
| MyObjectBuilder_SolarPanel | LargeBlockSolarPanel | 1×1×1 large block |
| MyObjectBuilder_BatteryBlock | LargeBlockBatteryBlock | 1×1×1 large block |
| MyObjectBuilder_Refinery | Blast Furnace | Basic Refinery |
| MyObjectBuilder_Assembler | Assembler | Standard assembler |
| MyObjectBuilder_ShipWelder | SELtdLargeNanobotBuildAndRepairSystem | Nanobot BARS |
| MyObjectBuilder_Drill | SELtdLargeNanobotDrillSystem | Nanobot Drill |
| MyObjectBuilder_CargoContainer | LargeBlockSmallContainer | Small cargo |
| MyObjectBuilder_Projector | LargeProjector | Projector block |

### Saving modified blueprint for manual import

When `load_blueprint_xml` doesn't work (see pitfall in SKILL.md), save to file:

```python
output_path = "/workspace/<gridname>_with_block.xml"  # runtime path
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(new_xml)
print(f"Saved: {output_path} ({len(new_xml)} bytes, {len(cube_blocks)} blocks)")
```

User can then load this file through the SE game UI projector terminal.
