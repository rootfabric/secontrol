# API Reference — secontrol

Full public API for the `secontrol` library. All imports from `secontrol` top-level unless noted.

---

## RedisEventClient

```python
from secontrol import RedisEventClient

client = RedisEventClient(url=None, username=None, password=None)
```

Low-level Redis wrapper. Reads connection from `.env` if not passed explicitly.

| Method | Returns | Description |
|---|---|---|
| `publish(channel, payload)` | `int` | Publish JSON to a Redis channel |
| `get_json(key)` | `dict \| None` | Fetch and parse JSON from a Redis key |
| `get_value(key)` | `bytes \| None` | Fetch raw value from a Redis key |
| `list_grids(owner_id, exclude_subgrids=False)` | `list[dict]` | List all grids for an owner |
| `subscribe_to_key(key, callback, events=None)` | `_PubSubSubscription` | Subscribe to keyspace notifications for a key |
| `subscribe_to_channel(channel, callback)` | `_PubSubSubscription` | Subscribe to a pub/sub channel |
| `subscribe_to_key_resilient(key, callback, events=None)` | `_CompositeSubscription` | Resilient subscription (keyspace + channel + polling) |
| `close()` | `None` | Close all subscriptions and Redis connection |
| `client` | `redis.Redis` | Access underlying Redis client |

---

## Grid

```python
from secontrol import Grid

# By name (preferred)
grid = Grid.from_name("MyShip", redis_client=None, owner_id=None, player_id=None,
                       auto_wake=True, wake_timeout=3.0)

# Direct construction
grid = Grid(redis_client, owner_id, grid_id, player_id, name=None, auto_wake=True)
```

### Properties

| Property | Type | Description |
|---|---|---|
| `redis` | `RedisEventClient` | Redis client used by this grid |
| `owner_id` | `str` | Owner ID |
| `grid_id` | `str` | Grid ID |
| `player_id` | `str` | Player ID |
| `name` | `str` | Grid display name |
| `metadata` | `dict \| None` | Latest raw telemetry payload |
| `is_subgrid` | `bool` | Whether this is a sub-grid |
| `devices` | `dict[str, BaseDevice]` | Devices keyed by device_id string |
| `devices_by_num` | `dict[int, BaseDevice]` | Devices keyed by device_id int |
| `blocks` | `dict[int, BlockInfo]` | All blocks keyed by block_id |

### Methods

| Method | Returns | Description |
|---|---|---|
| `wake(timeout=3.0, poll_interval=0.1)` | `bool` | Send wake command, wait for telemetry |
| `wait_until_ready(timeout=3.0, poll_interval=0.1)` | `bool` | Wait until grid has full telemetry |
| `on(event, callback)` | `None` | Register event handler |
| `off(event, callback)` | `None` | Remove event handler |
| `send_grid_command(command, **kwargs)` | `int` | Send command to the grid |
| `close()` | `None` | Close subscriptions |

### Events

| Event | Callback signature | Payload |
|---|---|---|
| `"devices"` | `(grid, GridDevicesEvent, source)` | `.added: list[BaseDevice]`, `.removed: list[RemovedDeviceInfo]` |
| `"integrity"` | `(grid, dict, source)` | `{"changes": list[GridIntegrityChange]}` |
| `"damage"` | `(grid, DamageEvent, source)` | `DamageEvent` parsed from damage channel |

### GridDevicesEvent

```python
@dataclass
class GridDevicesEvent:
    added: list[BaseDevice]
    removed: list[RemovedDeviceInfo]
```

### GridIntegrityChange

```python
@dataclass
class GridIntegrityChange:
    block_id: int
    block: BlockInfo
    name: Optional[str]
    block_type: str
    subtype: Optional[str]
    previous_integrity: Optional[float]
    current_integrity: Optional[float]
    was_damaged: bool
    is_damaged: bool
```

---

## Grids

```python
from secontrol import Grids

grids = Grids(redis_client, owner_id, player_id)
```

| Method | Returns | Description |
|---|---|---|
| `search(name)` | `list[GridState]` | Search grids by name (case-insensitive partial match) |
| `on(event, callback)` | `None` | Events: `"added"`, `"updated"`, `"removed"` |

---

## GridState

```python
@dataclass
class GridState:
    owner_id: str
    grid_id: str
    descriptor: dict
    info: dict
```

| Property | Type | Description |
|---|---|---|
| `name` | `str \| None` | Best available grid name |
| `clone()` | `GridState` | Deep copy |

---

## BaseDevice

Base class for all device types. Accessed via `grid.devices`.

### Properties

| Property | Type | Description |
|---|---|---|
| `device_id` | `str` | Device entity ID (string) |
| `device_type` | `str` | Device type key (e.g. `"lamp"`, `"thruster"`) |
| `name` | `str \| None` | Block name |
| `grid` | `Grid` | Parent grid |
| `telemetry` | `dict` | Latest telemetry payload |
| `telemetry_key` | `str` | Redis key for this device's telemetry |
| `metadata` | `DeviceMetadata` | Device metadata |

### Methods

| Method | Returns | Description |
|---|---|---|
| `send_command(command)` | `int` | Send command payload to device |
| `update()` | `bool` | Force telemetry refresh from Redis |
| `wait_for_telemetry(timeout=5.0, need_update=True)` | `bool` | Wait for next telemetry update |
| `on(event, callback)` | `None` | Register event handler (event: `"telemetry"`) |
| `off(event, callback)` | `None` | Remove event handler |
| `close()` | `None` | Cleanup |
| `set_enabled(enabled)` | `int` | Enable/disable the block |
| `enable()` | `int` | Enable the block |
| `disable()` | `int` | Disable the block |
| `custom_data()` | `str \| None` | Get custom data from block |
| `get_inventory(reference=None)` | `InventorySnapshot \| None` | Get inventory snapshot |
| `inventories()` | `list[InventorySnapshot]` | Get all inventory snapshots |
| `inventory_count()` | `int` | Number of inventories |
| `inventory_items(inventory=None)` | `list[InventoryItem]` | Get items from inventory |
| `is_functional()` | `bool` | Block is functional |
| `is_working()` | `bool` | Block is working |
| `world_position()` | `tuple[float,float,float] \| None` | Block world position |

---

## AdminUtilitiesClient

```python
from secontrol.admin import AdminUtilitiesClient

admin = AdminUtilitiesClient(redis_client=None, player_id=None, ack_channel=None)
```

| Method | Description |
|---|---|
| `spawn_grid(xml, position, forward=None, up=None, rotation=None, wait_for_ack=True, timeout=10.0)` | Spawn a grid from XML blueprint |
| `remove_grid(grid_id, wait_for_ack=True, timeout=5.0)` | Remove a grid |
| `remove_block(block_id, wait_for_ack=True, timeout=5.0)` | Remove a block |
| `upgrade_block(block_id, wait_for_ack=True, timeout=5.0)` | Upgrade a block |
| `remove_voxel(position, radius=0.5, wait_for_ack=True, timeout=10.0)` | Remove voxel terrain |
| `fill_voxel(position, material, radius=0.5, wait_for_ack=True, timeout=10.0)` | Fill voxel terrain |
| `teleport_grid(grid_id, position, forward=None, up=None, rotation=None, ...)` | Teleport a grid |
| `show_mission_screen(body, title=None, subtitle=None, ...)` | Show mission screen popup |
| `send_chat_message(message, author=None, broadcast=None, player_id=None, ...)` | Send in-game chat message |
| `close()` | Close connection |

---

## InventoryItem

```python
@dataclass
class InventoryItem:
    type: str           # e.g. "MyObjectBuilder_Ore"
    subtype: str        # e.g. "Iron"
    amount: float
    display_name: Optional[str]
```

| Method | Description |
|---|---|
| `from_payload(dict)` | Create from telemetry payload |
| `to_payload()` | Serialize to dict |
| `matches(item_type)` | Check against `ItemType` |

---

## InventorySnapshot

```python
@dataclass
class InventorySnapshot:
    device_id: int
    key: str
    index: int
    name: str
    current_volume: float
    max_volume: float
    current_mass: float
    fill_ratio: float
    items: list[InventoryItem]
```

| Method | Description |
|---|---|
| `describe_items()` | `list[str]` — human-readable item list |
| `to_dict()` | Serialize to dict |
| `copy()` | Deep copy |

---

## Item Types (item_types.py)

```python
from secontrol.item_types import Item, ORE, INGOT, COMPONENT, TOOL, AMMO

# Typed access
Item.SteelPlate       # ItemType for SteelPlate component
Item.PlatinumOre      # ItemType for Platinum ore
Item.UraniumIngot     # ItemType for Uranium ingot

# Category checks
from secontrol.item_types import is_ore, is_ingot, is_component
is_ore(item)       # True if item is ore
is_ingot(item)     # True if item is ingot
is_component(item) # True if item is component

# Matching
from secontrol.item_types import item_matches
item_matches(inventory_item, Item.SteelPlate)
```

---

## Utility functions (common.py)

| Function | Returns | Description |
|---|---|---|
| `prepare_grid(grid_id=None, auto_wake=True)` | `Grid` | Create Grid from env vars |
| `get_all_grids(client=None, exclude_subgrids=True)` | `list[tuple[str,str]]` | List `(grid_id, grid_name)` |
| `resolve_owner_id()` | `str` | Get owner ID from env |
| `resolve_player_id(owner_id)` | `str` | Get player ID from env |
| `resolve_grid_id(client, owner_id)` | `str` | Auto-select first non-subgrid |
| `close(grid)` | `None` | Close grid and optionally Redis |

---

## Controllers

### RadarController

```python
from secontrol.controllers.radar_controller import RadarController

rc = RadarController(radar_device, cell_size=10.0, radius=50.0, ...)
```

| Method | Returns | Description |
|---|---|---|
| `scan_voxels(filter_no_stone=None, max_wait_sec=120.0)` | `tuple` | Full voxel scan → `(solid, metadata, contacts, ore_cells)` |
| `scan_contacts()` | `list[dict]` | Scan only contacts (grids/players) |
| `extract_solid(radar)` | `tuple` | Extract solid points from radar data |
| `get_surface_height(x, z, search_radius=1)` | `float \| None` | Get surface height at world position |
| `filter_valuable_ore_cells(ore_cells)` | `list[dict]` | Filter out Stone, keep valuable ores |
| `set_scan_params(**kwargs)` | `None` | Update scan parameters |

### SurfaceFlightController

```python
from secontrol.controllers.surface_flight_controller import SurfaceFlightController

sfc = SurfaceFlightController(grid_name, scan_radius=100.0)
```

High-level autopilot: scans voxels, builds occupancy grid, flies over surface.

### SharedMapController

Redis-backed shared voxel maps for multi-vehicle coordination.

---

## DamageEvent

```python
@dataclass
class DamageEvent:
    timestamp: str
    grid_id: Optional[int]
    grid_name: Optional[str]
    grid_is_static: Optional[bool]
    owner_id: Optional[int]
    attacker_id: Optional[int]
    block: Optional[BlockInfo]
    damage: DamageDetails
    attacker: DamageSource
    raw: dict
```
