# Device Reference — secontrol

All 26 concrete device classes in `src/secontrol/devices/`. Each registers itself in `DEVICE_TYPE_MAP` at import time.

Access devices via `grid.devices` (dict keyed by device_id string) or `grid.find_devices_by_type(DeviceClass)`.

---

## BaseDevice (all devices inherit from this)

```python
from secontrol.base_device import BaseDevice
```

Common methods available on every device:

| Method | Returns | Description |
|---|---|---|
| `send_command(command)` | `int` | Send command dict to device via Redis |
| `update()` | `bool` | Force telemetry refresh |
| `wait_for_telemetry(timeout=5.0)` | `bool` | Wait for next telemetry update |
| `on(event, callback)` | `None` | Register event handler (`"telemetry"`) |
| `off(event, callback)` | `None` | Remove event handler |
| `set_enabled(enabled)` | `int` | Enable/disable block |
| `enable()` / `disable()` | `int` | Enable / disable |
| `get_inventory(ref=None)` | `InventorySnapshot \| None` | Get inventory |
| `inventories()` | `list[InventorySnapshot]` | All inventories |
| `inventory_items(ref=None)` | `list[InventoryItem]` | Items in inventory |
| `is_functional()` | `bool` | Block functional? |
| `is_working()` | `bool` | Block working? |
| `world_position()` | `tuple \| None` | World position (x, y, z) |
| `custom_data()` | `str \| None` | Custom data string |

Common properties: `device_id`, `device_type`, `name`, `grid`, `telemetry`, `telemetry_key`, `metadata`.

---

## Lighting

### LampDevice — `device_type = "lamp"`

```python
from secontrol.devices.lamp_device import LampDevice
```

| Method | Returns | Description |
|---|---|---|
| `enable()` / `disable()` | `int` | Turn on/off |
| `set_enabled(bool)` | `int` | Enable/disable |
| `toggle()` | `int` | Toggle state |
| `set_color(rgb=..., color=..., red=..., green=..., blue=...)` | `int` | Set color (0.0–1.0 range) |
| `set_intensity(float)` | `int` | Set intensity (0.0–10.0) |
| `set_radius(float)` | `int` | Set radius (1.0–100.0) |
| `is_enabled()` | `bool \| None` | Current state |
| `intensity()` | `float \| None` | Current intensity |
| `radius()` | `float \| None` | Current radius |
| `color_rgb()` | `tuple[float,float,float] \| None` | Current RGB color |

---

## Propulsion & Movement

### ThrusterDevice — `device_type = "thruster"`

```python
from secontrol.devices.thruster_device import ThrusterDevice
```

| Method | Returns | Description |
|---|---|---|
| `set_thrust(override=None, enabled=None)` | `int` | Set thrust override (float) and/or enabled state |

### WheelDevice — `device_type = "wheel"`

```python
from secontrol.devices.wheel_device import WheelDevice
```

Wheel suspension control for rovers.

### RoverDevice — `device_type = "rover"`

```python
from secontrol.devices.rover_device import RoverDevice
```

High-level rover control (wraps wheels + remote control).

### GyroDevice — `device_type = "gyro"`

```python
from secontrol.devices.gyro_device import GyroDevice
```

Gyroscope override control.

---

## Navigation & Autopilot

### RemoteControlDevice — `device_type = "remote_control"`

```python
from secontrol.devices.remote_control_device import RemoteControlDevice
```

| Method | Returns | Description |
|---|---|---|
| `enable()` | `int` | Enable autopilot |
| `disable()` | `int` | Disable autopilot |
| `set_mode(mode)` | `int` | Set mode: `"oneway"`, `"patrol"`, `"circle"` |
| `goto(gps, speed=None, gps_name="Target", dock=False)` | `int` | Navigate to GPS coordinate |
| `set_collision_avoidance(enabled)` | `int` | Toggle collision avoidance |
| `set_enabled(enabled)` | `int` | Enable/disable block |
| `gyro_control_on()` / `gyro_control_off()` | `int` | Gyro control |
| `handbrake_on()` / `handbrake_off()` | `int` | Handbrake |
| `dampeners_on()` / `dampeners_off()` | `int` | Dampeners |
| `thrusters_on()` / `thrusters_off()` | `int` | Thrusters |
| `wheels_on()` / `wheels_off()` | `int` | Wheels |
| `planetary_autopilot_on()` / `planetary_autopilot_off()` | `int` | Planetary autopilot |
| `get_orientation_vectors_world()` | `(forward, up, right)` | RC orientation in world coords |

**Important**: `goto()` accepts GPS strings (`"GPS:Name:x:y,z:"`) or raw `"x,y,z"` coordinates.

---

## Cargo & Inventory

### ContainerDevice — `device_type = "container"`

```python
from secontrol.devices.container_device import ContainerDevice
```

Base for all inventory-aware devices. Also used by ConnectorDevice, AssemblerDevice, RefineryDevice.

| Method | Returns | Description |
|---|---|---|
| `items(inventory=None)` | `list[InventoryItem]` | Get items |
| `capacity(inventory=None)` | `dict` | `{currentVolume, maxVolume, currentMass, fillRatio}` |
| `inventory(ref=None)` | `InventorySnapshot \| None` | Alias for `get_inventory()` |
| `move_items(dest, items, source_inventory=None, dest_inventory=None)` | `int` | Transfer items to another device |
| `move_subtype(dest, subtype, amount=None, ...)` | `int` | Move specific subtype |
| `move_items_to_slot(dest, items, target_slot_id, ...)` | `int` | Move to specific slot |
| `move_all(dest, blacklist=None, ...)` | `int` | Move all items |
| `drain_to(dest, subtypes, ...)` | `int` | Drain specific subtypes |
| `find_items_by_type(type, ...)` | `list[InventoryItem]` | Filter by type |
| `find_items_by_subtype(subtype, ...)` | `list[InventoryItem]` | Filter by subtype |
| `find_items_by_display_name(name, ...)` | `list[InventoryItem]` | Filter by display name |
| `has_tag(tag)` | `bool` | Check tag (from name `[tag]` or custom data) |
| `tags` | `set[str]` | Current tags |

### ConnectorDevice — `device_type = "connector"` (extends ContainerDevice)

```python
from secontrol.devices.connector_device import ConnectorDevice
```

| Method | Returns | Description |
|---|---|---|
| `set_state(locked=None, enabled=None)` | `int` | Set connector state |
| `connect()` | `int` | Connect to another connector |
| `disconnect()` | `int` | Disconnect |
| `toggle_connect()` | `int` | Toggle connection |
| `set_throw_out(bool)` | `int` | Throw out items on disconnect |
| `set_collect_all(bool)` | `int` | Collect all items in range |
| `nearbyConnectors()` | `list \| None` | Nearby connectors from telemetry |
| `transfer_remote(target_id, items, radius=100.0)` | `int` | Transfer to remote connector |
| `scan(radius=100.0)` | `int` | Scan for nearby connectors |
| `transfer_to_nearby(items, radius=100.0)` | `int` | Transfer to first nearby connector |

---

## Production

### AssemblerDevice — `device_type = "assembler"` (extends ContainerDevice)

```python
from secontrol.devices.assembler_device import AssemblerDevice
```

| Method | Returns | Description |
|---|---|---|
| `set_enabled(bool)` | `int` | Enable/disable |
| `toggle_enabled()` | `int` | Toggle |
| `set_use_conveyor(bool)` | `int` | Toggle conveyor system |
| `clear_queue()` | `int` | Clear production queue |
| `remove_queue_item(index, amount=None)` | `int` | Remove queue item by index |
| `add_queue_item(blueprint, amount=None)` | `int` | Add to queue (str, tuple, or dict) |
| `add_queue_items(items)` | `int` | Add multiple items |
| `request_blueprints()` | `int` | Request available blueprints |
| `queue()` | `list[dict]` | Current queue |
| `print_queue()` | `None` | Print queue to stdout |
| `is_producing()` | `bool` | Currently producing? |
| `is_queue_empty()` | `bool` | Queue empty? |
| `current_progress()` | `float` | Current progress (0.0–1.0) |
| `input_inventory()` | `InventorySnapshot \| None` | Input inventory |
| `output_inventory()` | `InventorySnapshot \| None` | Output inventory |
| `blueprints` | `list[dict] \| None` | Available blueprints |

### RefineryDevice — `device_type = "refinery"` (extends ContainerDevice)

```python
from secontrol.devices.refinery_device import RefineryDevice
```

Similar to AssemblerDevice but for ore processing.

---

## Projection & Construction

### ProjectorDevice — `device_type = "projector"`

```python
from secontrol.devices.projector_device import ProjectorDevice
```

| Method | Returns | Description |
|---|---|---|
| `set_enabled(bool)` | `int` | Enable/disable projector |
| `set_flags(keep_projection=..., show_only_buildable=..., instant_build=..., align_grids=..., lock_projection=..., use_adaptive_offsets=..., use_adaptive_rotation=...)` | `int` | Set projection flags |
| `set_scale(float)` | `int` | Set projection scale |
| `set_offset(x, y, z)` | `int` | Set projection offset (absolute) |
| `move_offset(dx, dy, dz)` | `int` | Nudge offset (delta) |
| `set_rotation(x, y, z)` | `int` | Set rotation (absolute) |
| `rotate(dx, dy, dz)` | `int` | Nudge rotation (delta) |
| `reset_projection()` | `int` | Reset projection |
| `clear_projection()` | `int` | Clear projection |
| `lock_projection()` / `unlock_projection()` | `int` | Lock/unlock |
| `load_prefab(prefab_id, keep=True)` | `int` | Load PrefabDefinition |
| `load_blueprint_xml(xml, keep=False)` | `int` | Load blueprint from XML |
| `request_grid_blueprint(include_connected=True)` | `int` | Export grid to blueprint XML |
| `blueprint_xml()` | `str \| None` | Get exported blueprint XML |
| `blueprint_snapshot()` | `dict \| None` | Get blueprint snapshot |
| `remaining_blocks()` | `int \| None` | Blocks remaining to build |
| `buildable_blocks()` | `int \| None` | Blocks that can be built |
| `projected_grid_name()` | `str \| None` | Projected grid name |

**Important**: `set_offset`/`set_rotation` are ABSOLUTE. `move_offset`/`rotate` are DELTA.

### ShipWelderDevice — `device_type = "ship_welder"`

```python
from secontrol.devices.ship_welder_device import ShipWelderDevice
```

Welder block control. Use with ProjectorDevice for construction workflows.

### BuildAndRepairDevice — `device_type = "build_and_repair"`

```python
from secontrol.devices.build_and_repair_device import BuildAndRepairDevice
```

Nanobot Build and Repair system. Handles ColorMaskHSV for painting.

---

## Mining & Drilling

### ShipDrillDevice — `device_type = "ship_drill"`

```python
from secontrol.devices.ship_drill_device import ShipDrillDevice
```

Ship drill control.

### NanobotDrillSystemDevice — `device_type = "nanobot_drill_system"`

```python
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
```

Nanobot Drill and Fill system. Area-based mining automation.

---

## Scanning & Detection

### OreDetectorDevice — `device_type = "ore_detector"`

```python
from secontrol.devices.ore_detector_device import OreDetectorDevice
```

| Method | Returns | Description |
|---|---|---|
| `scan(include_players=True, include_grids=True, include_voxels=False, ore_only=False, radius=None, cell_size=None, ...)` | `int` | Request radar scan (many optional params) |
| `cancel_scan()` | `int` | Cancel current scan |
| `scan_and_wait(timeout=10.0, **kwargs)` | `dict` | Scan and wait for result |
| `monitor_ore(scan_interval=10.0, config=None)` | `None` | Blocking ore monitor loop |
| `radar_snapshot()` | `dict` | Latest radar data |
| `contacts()` | `list[dict]` | Detected contacts |
| `ore_cells()` | `list[dict]` | Ore cell data |
| `ore_cells_truncated()` | `int` | Truncation count |
| `scan_radius()` | `float \| None` | Current scan radius |
| `revision()` | `int \| None` | Radar revision number |
| `wait_for_new_radar(timeout=10.0)` | `bool` | Wait for radar update |

### LargeTurretDevice — `device_type = "large_turret"`

```python
from secontrol.devices.large_turret_device import LargeTurretDevice
```

Turret targeting and firing control.

### AIDevice — `device_type = "ai"`

```python
from secontrol.devices.ai_device import AIDevice
```

AI block behavior configuration.

---

## Power & Systems

### BatteryDevice — `device_type = "battery"`

```python
from secontrol.devices.battery_device import BatteryDevice
```

Battery charge/discharge control.

### ReactorDevice — `device_type = "reactor"`

```python
from secontrol.devices.reactor_device import ReactorDevice
```

Reactor on/off and fuel management.

### GasGeneratorDevice — `device_type = "gas_generator"`

```python
from secontrol.devices.gas_generator_device import GasGeneratorDevice
```

Hydrogen/Oxygen generator control.

---

## Cockpit & Display

### CockpitDevice — `device_type = "cockpit"`

```python
from secontrol.devices.cockpit_device import CockpitDevice
```

Cockpit control and terminal access.

### DisplayDevice — `device_type = "display"`

```python
from secontrol.devices.display_device import DisplayDevice
```

LCD/display content management.

---

## Weapons

### WeaponDevice — `device_type = "weapon"`

```python
from secontrol.devices.weapon_device import WeaponDevice
```

Weapon fire control.

### ArtilleryDevice — `device_type = "artillery"`

```python
from secontrol.devices.artillery_device import ArtilleryDevice
```

Artillery/missile launcher control.

---

## Utility

### ShipGrinderDevice — `device_type = "ship_grinder"`

```python
from secontrol.devices.ship_grinder_device import ShipGrinderDevice
```

Grinder control for deconstruction.

### ShipToolDevice — `device_type = "ship_tool"`

```python
from secontrol.devices.ship_tool_device import ShipToolDevice
```

Generic ship tool base.

### ConveyorSorterDevice — `device_type = "conveyor_sorter"`

```python
from secontrol.devices.conveyor_sorter_device import ConveyorSorterDevice
```

Conveyor sorter filter configuration.
