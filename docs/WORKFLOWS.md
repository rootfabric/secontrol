# Workflows & Recipes — secontrol

Common patterns for agents and developers working with the secontrol library.

---

## 1. Getting Started

### Connect and list devices

```python
from secontrol import Grid

grid = Grid.from_name("MyShip")
print(f"Grid: {grid.name}, Devices: {len(grid.devices)}")

for device_id, device in grid.devices.items():
    print(f"  {device_id}: {device.device_type} — {device.name}")
```

### List all grids

```python
from secontrol.common import get_all_grids

grids = get_all_grids()
for grid_id, grid_name in grids:
    print(f"  {grid_id}: {grid_name}")
```

---

## 2. Device Control

### Toggle a lamp

```python
from secontrol.devices.lamp_device import LampDevice

lamps = grid.find_devices_by_type(LampDevice)
for lamp in lamps:
    lamp.set_color(rgb=(1.0, 0.0, 0.0))  # Red
    lamp.set_intensity(5.0)
    lamp.enable()
```

### Control a thruster

```python
from secontrol.devices.thruster_device import ThrusterDevice

thrusters = grid.find_devices_by_type(ThrusterDevice)
for t in thrusters:
    t.set_thrust(override=0.5, enabled=True)  # 50% thrust
```

### Lock/unlock connector

```python
from secontrol.devices.connector_device import ConnectorDevice

connectors = grid.find_devices_by_type(ConnectorDevice)
conn = connectors[0]
conn.connect()         # Lock
conn.disconnect()      # Unlock
conn.set_state(locked=True, enabled=True)
```

---

## 3. Inventory Management

### Check container contents

```python
from secontrol.devices.container_device import ContainerDevice

containers = grid.find_devices_by_type(ContainerDevice)
for c in containers:
    cap = c.capacity()
    print(f"{c.name}: {cap['fillRatio']:.1%} full ({cap['currentVolume']:.0f}/{cap['maxVolume']:.0f})")
    for item in c.items():
        print(f"  {item.amount:.1f} × {item.display_name or item.subtype}")
```

### Transfer items between containers

```python
from secontrol.devices.container_device import ContainerDevice
from secontrol.inventory import InventoryItem

source = grid.find_devices_by_type(ContainerDevice)[0]
dest = grid.find_devices_by_type(ContainerDevice)[1]

# Move specific item
source.move_subtype(dest, "Iron", amount=100.0)

# Move all items
source.move_all(dest, blacklist={"Uranium"})  # Keep Uranium
```

### Use typed item checks

```python
from secontrol.item_types import Item, is_ore, item_matches

for item in container.items():
    if item_matches(item, Item.PlatinumOre):
        print(f"Found {item.amount} Platinum ore!")
    if is_ore(item):
        print(f"  Ore: {item.subtype} × {item.amount}")
```

---

## 4. Production (Assembler)

### Add items to production queue

```python
from secontrol.devices.assembler_device import AssemblerDevice

assemblers = grid.find_devices_by_type(AssemblerDevice)
asm = assemblers[0]

asm.set_enabled(True)
asm.set_use_conveyor(True)

# Add by blueprint ID
asm.add_queue_item("SteelPlate", amount=100)
asm.add_queue_item("InteriorPlate", amount=50)

# Add by Item type
asm.add_queue_item(Item.SteelPlate.blueprint_id, amount=200)

asm.print_queue()
```

### Monitor production

```python
import time

while True:
    asm.update()
    print(f"Producing: {asm.is_producing()}, Progress: {asm.current_progress():.1%}")
    print(f"Queue: {len(asm.queue())} items")
    time.sleep(5)
```

---

## 5. Blueprint & Projection Workflow

### Load blueprint into projector and build

```python
from secontrol.devices.projector_device import ProjectorDevice
from secontrol.devices.ship_welder_device import ShipWelderDevice

projector = grid.find_devices_by_type(ProjectorDevice)[0]
welder = grid.find_devices_by_type(ShipWelderDevice)[0]

# Step 1: Disable welder before loading
welder.disable()

# Step 2: Load blueprint XML
with open("my_blueprint.xml") as f:
    xml = f.read()
projector.load_blueprint_xml(xml, keep=False)

# Step 3: Verify projection
print(f"Remaining blocks: {projector.remaining_blocks()}")
print(f"Buildable blocks: {projector.buildable_blocks()}")

# Step 4: Enable welder to build
welder.enable()

# Step 5: Monitor progress
import time
while projector.remaining_blocks() and projector.remaining_blocks() > 0:
    print(f"Remaining: {projector.remaining_blocks()}")
    time.sleep(5)
```

### Export grid to blueprint

```python
projector = grid.find_devices_by_type(ProjectorDevice)[0]
projector.request_grid_blueprint(include_connected=True)

import time
time.sleep(3)  # Wait for export

xml = projector.blueprint_xml()
if xml:
    with open("exported.xml", "w") as f:
        f.write(xml)
    print(f"Exported {len(xml)} bytes")
```

### Adjust projection offset/rotation

```python
# IMPORTANT: set_offset/set_rotation are ABSOLUTE
projector.set_offset(0, 0, 0)
projector.set_rotation(0, 0, 0)

# move_offset/rotate are DELTA
projector.move_offset(dy=1)    # Move down 1 block
projector.rotate(dz=90)        # Rotate 90° around Z
```

---

## 6. Radar & Scanning

### Basic radar scan

```python
from secontrol.devices.ore_detector_device import OreDetectorDevice

radar = grid.find_devices_by_type(OreDetectorDevice)[0]
radar.update()

# Quick scan
result = radar.scan_and_wait(timeout=15.0, include_voxels=True, ore_only=True)
ore_cells = result.get("oreCells", [])
for cell in ore_cells:
    print(f"  {cell.get('material')}: {cell.get('content')} at {cell.get('position')}")
```

### Advanced scan with RadarController

```python
from secontrol.controllers.radar_controller import RadarController

radar = grid.find_devices_by_type(OreDetectorDevice)[0]
rc = RadarController(radar, cell_size=10.0, radius=5000, boundingBoxX=100, boundingBoxY=100, boundingBoxZ=100)

solid, metadata, contacts, ore_cells = rc.scan_voxels(filter_no_stone=True)
print(f"Solid points: {len(solid)}, Valuable ores: {len(ore_cells)}")

# Get surface height at a point
height = rc.get_surface_height(1000.0, 2000.0)
if height:
    print(f"Surface height: {height:.1f}m")
```

---

## 7. Navigation & Autopilot

### Fly to a GPS coordinate

```python
from secontrol.devices.remote_control_device import RemoteControlDevice

rc = grid.find_devices_by_type(RemoteControlDevice)[0]
rc.set_mode("oneway")
rc.set_collision_avoidance(True)
rc.goto("GPS:Base:1000:2000:3000:", speed=10.0, gps_name="Base")
```

### Monitor position

```python
import time

while True:
    rc.update()
    pos = rc.world_position()
    if pos:
        print(f"Position: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")
    time.sleep(1)
```

### Get orientation vectors

```python
forward, up, right = rc.get_orientation_vectors_world()
print(f"Forward: {forward}")
print(f"Up: {up}")
print(f"Right: {right}")
```

---

## 8. Admin Operations

### Spawn a grid

```python
from secontrol.admin import AdminUtilitiesClient

admin = AdminUtilitiesClient()

with open("ship.xml") as f:
    xml = f.read()

result = admin.spawn_grid(
    xml,
    position={"x": 1000, "y": 2000, "z": 3000},
    forward={"x": 0, "y": 0, "z": 1},
    up={"x": 0, "y": 1, "z": 0},
)
print(f"Spawn result: {result}")
```

### Remove a grid

```python
admin.remove_grid(grid_id=123456)
```

### Teleport a grid

```python
admin.teleport_grid(
    grid_id=123456,
    position={"x": 5000, "y": 6000, "z": 7000},
)
```

### Send chat message

```python
admin.send_chat_message("Hello from secontrol!", broadcast=True)
```

---

## 9. Event-Driven Patterns

### Monitor device changes

```python
def on_devices_changed(grid, event, source):
    if event.added:
        for device in event.added:
            print(f"  Added: {device.device_type} {device.name}")
    if event.removed:
        for device in event.removed:
            print(f"  Removed: {device.device_type} {device.name}")

grid.on("devices", on_devices_changed)
```

### Monitor damage events

```python
def on_damage(grid, event, source):
    if event.block:
        print(f"Damage to {event.block.block_type}: {event.damage}")
    print(f"Attacker: {event.attacker}")

grid.on("damage", on_damage)
```

### Monitor integrity changes

```python
def on_integrity(grid, event, source):
    for change in event["changes"]:
        if change.is_damaged and not change.was_damaged:
            print(f"Block {change.name} took damage: {change.previous_integrity} → {change.current_integrity}")

grid.on("integrity", on_integrity)
```

---

## 10. Error Handling Patterns

### Resilient device access

```python
import time

def get_device_with_retry(grid, device_type, max_retries=3):
    for attempt in range(max_retries):
        devices = grid.find_devices_by_type(device_type)
        if devices:
            return devices[0]
        grid.update()
        time.sleep(1)
    raise RuntimeError(f"No {device_type.__name__} found after {max_retries} retries")
```

### Safe command sending

```python
def safe_command(device, cmd, retries=3):
    for attempt in range(retries):
        try:
            result = device.send_command(cmd)
            return result
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(0.5)
```

---

## 11. Multi-Grid Patterns

### Control multiple grids

```python
from secontrol.common import get_all_grids
from secontrol import Grid

all_grids = get_all_grids()
grids = {}
for grid_id, grid_name in all_grids:
    grids[grid_name] = Grid.from_name(grid_name)

# Enable all assemblers across all grids
for name, grid in grids.items():
    from secontrol.devices.assembler_device import AssemblerDevice
    for asm in grid.find_devices_by_type(AssemblerDevice):
        asm.set_enabled(True)
        print(f"Enabled assembler on {name}: {asm.name}")
```

---

## 12. Common Pitfalls

1. **`prepare_grid()` uses STRING args** — passing an int selects the wrong grid. Use `Grid.from_name()` instead.

2. **`set_offset`/`set_rotation` are ABSOLUTE** — they set the value. Use `move_offset`/`rotate` for DELTA changes.

3. **Auto-wake sends Redis command** — `Grid()` constructor sends "wake" by default. Use `auto_wake=False` to suppress.

4. **Devices appear after wake** — `grid.devices` is empty until wake completes and telemetry arrives.

5. **`enable()` on RC = autopilot** — `RemoteControlDevice.enable()` enables autopilot mode, not just the block.

6. **Blueprint XML can bloat** — `ComponentContainer` data can inflate XML from ~40KB to ~800KB. Strip to minimal XML before loading.

7. **Telemetry polling needs delay** — Use 0.3–1.0s delay between telemetry polls to avoid overwhelming Redis.

8. **Nanobot Drill in space** — area=75×75×75m, periodically disables itself. Re-enable with `set OnOff True`. `ScriptControlled=False`, `start_drilling()` required.

9. **Thrusters REQUIRE hasPilot or RemoteControl** — thrusters won't respond without a pilot seat or RC on the grid.

10. **Newly built ships have disabled blocks** — most blocks start disabled after construction. Enable all first.
