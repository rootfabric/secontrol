[← Parent skill: secontrol-space-engineers](../SKILL.md)

# Inventory Reading Patterns (verified working)

## Container inventory — use `get_inventory()` (NOT telemetry)

Container devices (`ContainerDevice`, `ConnectorDevice`, `AssemblerDevice`) expose inventory via
`dev.get_inventory()` which returns an `InventorySnapshot`. The telemetry dict does NOT have
`inputInventory`/`outputInventory` for containers — that pattern only works for refinery/assembler.

```python
from secontrol.common import get_all_grids, prepare_grid

grid = prepare_grid('skynet-baza0')

for did, dev in grid.devices.items():
    if dev.device_type != 'container':
        continue
    inv = dev.get_inventory()  # InventorySnapshot
    t = dev.telemetry or {}
    name = t.get('CustomName', 'Container')
    print(f'{name}: {inv.current_mass:.0f} kg, {inv.current_volume:.1f}/{inv.max_volume:.0f} L ({inv.fill_ratio*100:.1f}%)')
    for item in inv.items:
        print(f'  {item.display_name}: {item.amount}')
```

## Refinery/Assembler inventory — use telemetry dict

Refinery and assembler expose inventory in telemetry as dicts with nested structure.
**IMPORTANT**: these are plain dicts, NOT InventoryItem objects — access with string keys.

```python
for did, dev in grid.devices.items():
    if dev.device_type not in ['refinery', 'assembler']:
        continue
    t = dev.telemetry or {}
    for label, key in [('INPUT', 'inputInventory'), ('OUTPUT', 'outputInventory')]:
        inv = t.get(key)
        if not inv:
            continue
        items = inv.get('items', [])
        mass = inv.get('currentMass', 0)
        vol = inv.get('currentVolume', 0)
        maxvol = inv.get('maxVolume', 0)
        print(f'  {label} ({len(items)} stacks, {mass:.0f} kg, {vol:.1f}/{maxvol} L):')
        for item in items:
            # NOTE: string keys, not attributes!
            print(f'    {item["displayName"]}: {item["amount"]}')
```

## Key difference: InventoryItem vs dict

| Source | Item access | Name field | Amount field |
|---|---|---|---|
| `get_inventory()` → `InventorySnapshot.items` | **attributes**: `item.display_name` | `.display_name` | `.amount` |
| Telemetry `inputInventory.items` | **dict keys**: `item["displayName"]` | `"displayName"` | `"amount"` |

## Get all grids with IDs

```python
from secontrol.common import get_all_grids

grids = get_all_grids()  # list of (grid_id, grid_name)
for gid, name in grids:
    print(f"ID={gid} → {name}")
```

**Never use `Grid.from_name()` for grids with similar names** — it returns the first fuzzy-search match. Use IDs from `get_all_grids()`.

## List all containers + capacities

```python
containers = grid.find_devices_containers()
for dev in containers:
    cap = dev.capacity()  # {"currentVolume": ..., "maxVolume": ..., "fillRatio": ...}
    print(f"{dev.name}: {cap['fillRatio']*100:.1f}% full")
```

## InventorySnapshot fields

- `device_id`, `key`, `index`, `name`
- `current_volume`, `max_volume`, `current_mass`, `fill_ratio`
- `items: list[InventoryItem]`
- Each `InventoryItem`: `type`, `subtype`, `amount`, `display_name`

## Grid health check — damage and functional state

```python
for bid, block in grid.blocks.items():
    state = block.state or {}  # ALWAYS guard — can be None
    is_damaged = getattr(block, 'is_damaged', False)
    functional = state.get('functional')
    enabled = state.get('enabled')
    # functional=False on armor blocks is NORMAL (they have no function)
    # functional=False on functional blocks = damaged or incomplete
```

## Pitfalls

- **`execute_code` sandbox does NOT have `secontrol` installed.** Always run secontrol scripts via `terminal`, not `execute_code`.
- **Batteries, solar panels, thrusters, hydrogen engines often return empty telemetry dicts.** Don't assume `enabled`/`currentOutput` keys exist — always guard with `.get()`.
- **`block.state` can be `None`** — always use `block.state or {}`.
