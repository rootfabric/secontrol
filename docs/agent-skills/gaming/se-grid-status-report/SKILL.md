---
name: se-grid-status-report
description: >
  Generate a full status report for Space Engineers grids: block counts, device states,
  damage detection, and container inventories. Uses secontrol to query all grids or a
  specific one, producing a structured summary suitable for dashboards or chat output.
version: 1.0.0
metadata:
  hermes:
    tags: [gaming, space-engineers, secontrol, inventory, diagnostics]
    related_skills: [secontrol-space-engineers]
---

# SE Grid Status Report

Use when the user asks "show all ships", "what's in the containers", "grid status",
"check damage", "show inventory", or any request for an overview of SE grids and their contents.

## Prerequisites

- secontrol installed (`pip install -e ".[dev]"` from `/workspace`)
- `.env` with Redis credentials at project root
- Run all scripts via `terminal` from `/workspace` (not execute_code — secontrol may not be importable in sandbox)

## Quick: list all grids

```python
cd /workspace && python3 -c "
from secontrol.common import get_all_grids, resolve_owner_id
owner = resolve_owner_id()
grids = get_all_grids()
print(f'Owner: {owner}')
for gid, gname in grids:
    print(f'  {gname} (ID: {gid})')
"
```

## Full status report (blocks + damage + devices + containers)

Single script that iterates all grids, collects block stats, damage, device states, and inventories.
Always run from `/workspace`. Use `time.sleep(0.8)` between grid connections to avoid Redis overload.

### Pattern

```python
from secontrol.common import get_all_grids, prepare_grid
import time

grids = get_all_grids()

for gid, gname in grids:
    grid = prepare_grid(str(gid))   # MUST be string, int = wrong grid
    time.sleep(0.8)

    # --- Block stats ---
    from collections import Counter
    types = Counter()
    damaged = []
    non_functional = []
    disabled = []
    for bid, block in grid.blocks.items():
        types[f'{block.block_type}:{block.subtype}'] += 1
        state = block.state or {}
        if hasattr(block, 'is_damaged') and block.is_damaged:
            damaged.append(block)
        if state.get('functional') == False:
            non_functional.append(block)
        if state.get('enabled') == False:
            disabled.append(block)

    # --- Devices ---
    for did, dev in grid.devices.items():
        t = dev.telemetry or {}
        # ... collect enabled/functional/telemetry keys

    # --- Container inventories ---
    for did, dev in grid.devices.items():
        if dev.device_type == 'container':
            inv = dev.get_inventory()
            # inv.current_mass, inv.current_volume, inv.max_volume, inv.fill_ratio
            # inv.items -> list of InventoryItem(type, subtype, amount, display_name)
```

## Container inventory via ContainerDevice

ContainerDevice has `.get_inventory()` method returning `InventorySnapshot`:
- `inv.current_mass` — kg
- `inv.current_volume` / `inv.max_volume` — litres
- `inv.fill_ratio` — 0.0–1.0
- `inv.items` — list of `InventoryItem` with `.type`, `.subtype`, `.amount`, `.display_name`

Refinery and Assembler inventories come from telemetry dict:
- `dev.telemetry['inputInventory']` — dict with `items` list, `currentVolume`, `maxVolume`, `currentMass`
- `dev.telemetry['outputInventory']` — same structure
- Each item: `{'type': ..., 'subtype': ..., 'amount': ..., 'displayName': ...}`

## Device telemetry keys by type

| Device | Key telemetry fields |
|---|---|
| battery | `currentInput`, `currentOutput`, `storedPower`, `maxStoredPower`, `batteryLevel` |
| solarpanel | `currentOutput` |
| refinery | `inputInventory`, `outputInventory`, `isProducing`, `isQueueEmpty`, `queue` |
| assembler | `inputInventory`, `outputInventory`, `isProducing`, `queue`, `cooperativeMode`, `disassembleEnabled` |
| projector | `remainingBlocks`, `buildableBlocks`, `isProjecting`, `isWorking`, `offset` |
| connector | `connectorStatus`, `connectorIsConnected`, `nearbyConnectors`, `otherConnectorId/Name/GridId` |
| cockpit | `hasPilot` |
| remote_control | `autopilot` |
| nanobot_drill_system | `drill_areawidth`, `drill_areaheight`, `drill_areadepth`, `isMining`, `workMode` |
| ore_detector | `range`, `includeVoxels` |
| thruster | `currentThrust`, `maxThrust`, `override` |
| gyro | `power`, `override` |

## Damage interpretation

- `block.is_damaged == True` — actual damage (missing HP)
- `block.state['functional'] == False` — can mean:
  - **Damaged armor** — expected, not a bug
  - **Incomplete blocks** — projection ran out of resources
  - **Broken functional block** — needs repair
- Filter: skip armor blocks (`CubeBlock`) when reporting damage to avoid noise

## Pitfalls

1. **`prepare_grid()` MUST take a string arg.** `prepare_grid(123456)` (int) resolves to a wrong grid or fails silently. Always `prepare_grid(str(gid))`.
2. **Sleep between grids.** `time.sleep(0.8)` minimum; rapid-fire connections cause Redis timeouts.
3. **Container telemetry may be empty** even when `get_inventory()` works. Always prefer `get_inventory()` over telemetry for containers.
4. **`block.state` may be None.** Always guard: `state = block.state or {}`.
5. **Refinery/Assembler inventory is in telemetry**, not via `get_inventory()`. Only `ContainerDevice` has `.get_inventory()`.
6. **Disabled containers** still report inventory via `get_inventory()` — `enabled=False` doesn't block reads.
7. **Non-functional armor blocks** are normal — armor always reports `functional=False`. Filter them out when showing "broken" blocks.
8. **Telemetry keys vary.** Some devices return empty dicts. Always guard with `.get()` and `or {}`.
