[← Parent skill: secontrol-space-engineers](../SKILL.md)

# DroneBase Telemetry Snapshot (May 2026)

## Grid IDs
- **DroneBase**: `138748817302648345` — production base, Mars orbit/surface
- **DroneBase 2**: `134540402238780591` — secondary base with Uranium reactor

Note: `Grid.from_name("DroneBase")` resolves to DroneBase 2 (alphabetical first match).
Use explicit IDs or full name `"DroneBase 2"`.

## DroneBase (138748817302648345) — Block Composition

| SE Block Type | Subtype | Device Type | Status |
|---------------|---------|-------------|--------|
| MyObjectBuilder_Projector | LargeProjector | projector | ✓ functional |
| MyObjectBuilder_ShipWelder | SELtdLargeNanobotBuildAndRepairSystem | ship_welder | ✓ functional, empty inventory |
| MyObjectBuilder_SurvivalKit | SurvivalKitLarge | survivalkit | ✓ functional |
| MyObjectBuilder_SolarPanel | LargeBlockSolarPanel | solarpanel | ✓ functional |
| MyObjectBuilder_BatteryBlock | LargeBlockBatteryBlock | battery | ✓ functional |
| MyObjectBuilder_Beacon | LargeBlockBeacon | beacon | ✓ functional, name="sky0" |
| MyObjectBuilder_CargoContainer | LargeBlockLargeContainer | container | OFF (has inventory) |
| MyObjectBuilder_CargoContainer | LargeBlockSmallContainer | container | OFF (has inventory) |
| MyObjectBuilder_ShipConnector | Connector | connector | ✓ functional |
| MyObjectBuilder_Conveyor | LargeBlockConveyor | — (no device) | OFF |
| MyObjectBuilder_CubeBlock | LargeBlockArmorBlock | — | ✗ 8 blocks NOT functional |
| MyObjectBuilder_OxygenGenerator | None | — | ✓ functional |

## Inventory Contents

### LargeBlockLargeContainer
- Ice: 25,748
- Stone: 1,313
- Small Steel Tube: 2
- Girder: 1
- Metal Grid: 4
- Interior Plate: 4
- Display: 1
- Iron Ingot: 82
- Scrap Metal: 2

### SmallBlockSmallContainer
- Nickel Ore: 9,961
- Stone: 150
- Ice: 25,519

### Connector 2
- Ice: 3,892
- Stone: 980

**Summary**: ~55k Ice, ~2.4k Stone, ~10k Nickel Ore, 82 Iron Ingot, minimal components.

## Gaps for Constructor Module

DroneBase already has:
- ✓ Projector + ShipWelder (construction pipeline ready)
- ✓ Power (Solar + Battery)
- ✓ Life support (OxygenGenerator + SurvivalKit)
- ✓ Docking (Connector)

Missing for full constructor module:
- ❌ **Assembler** — components can't be manufactured
- ❌ **Refinery** — ore can't be refined (only SurvivalKit x0.2 which is impractical)
- ❌ **Ore Detector** — can't find ore deposits
- ❌ **Drill** — can't mine
- ❌ 8 damaged armor blocks blocking projected area

## ShipWelder Telemetry Notes
- `currentVolume: 0` — nanobots empty (need components or ore to charge)
- `isProjecting: False` — projector not loading a blueprint
- `remainingBlocks: 0` — no active projection