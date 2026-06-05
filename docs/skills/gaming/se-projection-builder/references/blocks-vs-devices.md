# g.blocks vs g.devices — API discovery notes

## g.blocks — dict[int, BlockInfo]

All blocks on the grid. Key = integer block ID, value = `BlockInfo`.

```python
g.blocks                          # dict — NOT a list
g.blocks[BLOCK_ID]                # BlockInfo
g.blocks.get(BLOCK_ID)            # BlockInfo or None
for bid, binfo in g.blocks.items():
    print(bid, binfo.subtype, binfo.state)
```

**BlockInfo attributes:** `block_id`, `block_type`, `subtype`, `name`, `state` (dict with `enabled`, `functional`, `working`, `buildRatio`, `integrity`), `local_position`, `bounding_box`, `mass`, `normalized_type`, `relative_to_grid_center`, `extra`, `is_damaged`.

## g.devices — dict[str, Device]

Only blocks with `isDevice: True` in metadata. Key = string block ID, value = device object (ConnectorDevice, ProjectorDevice, etc.).

```python
g.devices                         # dict[str, Device]
g.devices['88575364068781680']    # ConnectorDevice
g.get_device('connector')         # → None! Only works with exact type name
g.find_devices_by_type('connector')  # list of matching devices
```

## Blocks NOT in g.devices

These block types appear in `g.blocks` but **NOT** in `g.devices`:
- `LargeShipMergeBlock` — cannot enable/disable via API
- `LargeBlockArmorBlock` — structural only
- `LargeBlockConveyor` — structural only
- `LargeBlockInteriorTurret`, `LargeBlockGatlingTurret` — may or may not be devices

**Workaround:** Use `g.send_grid_command("enable", payload={"deviceId": block_id})` — but this often doesn't work either (command sent=1 but block ignores it). Manual enable in-game is the reliable fallback.

## Connector device methods

```python
conn = g.devices['CONNECTOR_ID']
conn.enable() / conn.disable()
conn.toggle_connect()             # requires nearbyConnectors
conn.connect() / conn.disconnect()
conn.telemetry['nearbyConnectors']  # must be non-empty for connect to work
conn.telemetry['connectorIsConnected']
conn.telemetry['connectorStatus']   # 'Unconnected' | 'Connected' | etc.
```
