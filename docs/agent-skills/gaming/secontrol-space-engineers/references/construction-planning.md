# Construction Planning in Space Engineers

## Component costs for common blocks

### Large Grid Assembler
- Steel Plate × 30
- Interior Plate × 8
- Motor × 4
- Construction Component × 8
- Computer × 4

### Large Grid Refinery
- Steel Plate × 35
- Interior Plate × 10
- Motor × 4
- Construction Component × 10
- Computer × 4
- Metal Grid × 4

### Survival Kit (Small/Large)
- Steel Plate × 4
- Interior Plate × 2
- Computer × 2
- Construction Component × 4

## Iron Ingot requirements (approximate)

- 1 Steel Plate ≈ 21 Iron Ingot
- 1 Interior Plate ≈ 3 Iron Ingot
- 1 Construction Component ≈ 2 Iron Ingot + 1 Steel Plate

For Large Grid Assembler: ~30 Steel Plate → ~630 Iron Ingot minimum

## Assembler Blueprint XML Template

```xml
<?xml version="1.0" encoding="utf-16"?>
<MyObjectBuilder_ShipBlueprintDefinition xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Id Type="MyObjectBuilder_ShipBlueprintDefinition" Subtype="AssemblerBlueprint" />
  <DisplayName>Assembler</DisplayName>
  <CubeGrids>
    <CubeGrid>
      <SubtypeName />
      <EntityId>0</EntityId>
      <PersistentFlags>CastShadows InScene</PersistentFlags>
      <PositionAndOrientation>
        <Position x="0" y="0" z="0" />
        <Forward x="0" y="0" z="-1" />
        <Up x="0" y="1" z="0" />
        <Orientation>
          <X>0</X><Y>0</Y><Z>0</Z><W>1</W>
        </Orientation>
      </PositionAndOrientation>
      <GridSizeEnum>Large</GridSizeEnum>
      <CubeBlocks>
        <MyObjectBuilder_CubeBlock xsi:type="MyObjectBuilder_Assembler">
          <SubtypeName>LargeAssembler</SubtypeName>
          <Min x="0" y="0" z="0" />
          <ColorMaskHSV x="0" y="0" z="0" />
          <Owner>OWNER_ID_HERE</Owner>
          <BuiltBy>OWNER_ID_HERE</BuiltBy>
          <ShareMode>Faction</ShareMode>
          <ShowOnHUD>false</ShowOnHUD>
          <ShowInTerminal>true</ShowInTerminal>
          <Enabled>true</Enabled>
          <Orientation>
            <Forward>Forward</Forward>
            <Up>Up</Up>
          </Orientation>
        </MyObjectBuilder_CubeBlock>
      </CubeBlocks>
      <DisplayName>Assembler</DisplayName>
    </CubeGrid>
  </CubeGrids>
</MyObjectBuilder_ShipBlueprintDefinition>
```

Replace `OWNER_ID_HERE` with the actual owner ID from `resolve_owner_id()`.

## Construction sequence

1. Mine Iron Ore (ship with drill)
2. Transfer ore to base (connector docking)
3. Enable Survival Kit or Refinery (refine ore → ingots)
4. Survival Kit or Assembler (assemble ingots → components)
5. Load blueprint into Projector (`load_prefab()` or `load_blueprint_xml()`)
6. ShipWelder auto-builds projected blocks
7. Monitor: `projector.remaining_blocks == 0` → done

## Common pitfalls

- **No refinery on base** — Survival Kit works but at x0.2 speed. Fine for one-off builds.
- **Empty containers** — Always check before assuming resources exist.
- **Connector must be locked** — Ship must be physically docked for transfer.
- **Projection offset** — After loading blueprint, may need `projector.set_offset()` and `projector.rotate()` to align with ShipWelder range.
