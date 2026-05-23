# REPO_GUIDE.md — secontrol developer reference

Developer guide for working on the secontrol library itself (adding devices, fixing bugs, extending controllers, writing tests).

---

## Commands

```bash
# Install (editable dev mode)
pip install -e ".[dev]"

# Run tests
pytest tests/

# Build distribution
python -m build

# Upload to PyPI
twine upload dist/*
```

---

## Source layout

```
src/secontrol/
├── __init__.py          # Public API re-exports
├── _version.py          # __version__ = "0.3.1"
├── redis_client.py      # RedisEventClient — pub/sub, keyspace notifications
├── grids.py             # Grid, Grids, GridState, DamageEvent, GridDevicesEvent, GridIntegrityChange
├── base_device.py       # BaseDevice, BlockInfo, DamageDetails, DeviceMetadata, DEVICE_TYPE_MAP
├── common.py            # prepare_grid(), Grid.from_name(), resolve_*(), close(), get_all_grids()
├── admin.py             # AdminUtilitiesClient — spawn/remove/teleport grids, chat, mission screen
├── inventory.py         # InventoryItem, InventorySnapshot
├── item_types.py        # ItemType, ItemCategory, Item registry (Item.SteelPlate, Item.PlatinumOre...)
├── device_types.py      # Legacy compatibility wrapper
├── devices/             # 26 concrete device classes (see docs/DEVICE_REFERENCE.md)
│   ├── __init__.py      # DEVICE_TYPE_MAP registry, load_builtin_devices(), load_external_plugins()
│   ├── ai_device.py
│   ├── artillery_device.py
│   ├── assembler_device.py     # extends ContainerDevice — queue mgmt, blueprints
│   ├── battery_device.py
│   ├── build_and_repair_device.py
│   ├── cockpit_device.py
│   ├── connector_device.py      # extends ContainerDevice — lock/unlock, transfer_remote
│   ├── container_device.py     # inventory-aware base, tags, move_items, move_all
│   ├── conveyor_sorter_device.py
│   ├── display_device.py
│   ├── gas_generator_device.py
│   ├── gyro_device.py
│   ├── lamp_device.py           # color, intensity, radius
│   ├── large_turret_device.py
│   ├── nanobot_drill_system_device.py
│   ├── ore_detector_device.py
│   ├── projector_device.py      # load_blueprint_xml, load_prefab, offset/rotation
│   ├── reactor_device.py
│   ├── refinery_device.py
│   ├── remote_control_device.py # autopilot, goto, orientation vectors
│   ├── rover_device.py
│   ├── ship_drill_device.py
│   ├── ship_grinder_device.py
│   ├── ship_tool_device.py
│   ├── ship_welder_device.py
│   ├── thruster_device.py       # thrust override
│   ├── weapon_device.py
│   └── wheel_device.py
├── controllers/         # High-level automation controllers
│   ├── radar_controller.py      # RadarController — voxel scanning, occupancy grid, surface height
│   ├── space_navigator_controller.py  # SpaceNavigatorController — obstacle-avoiding space flight
│   ├── surface_flight_controller.py  # SurfaceFlightController — fly-over-surface autopilot
│   └── shared_map_controller.py     # SharedMapController — Redis-backed shared voxel maps
├── tools/               # Standalone CLI/GUI utilities (not public API)
│   ├── blueprint_editor.py
│   ├── check_redis_user.py
│   ├── create_restricted_redis_user.py
│   ├── device_load_monitor_gui.py
│   ├── navigation_tools.py      # fly_to_point, get_world_position, goto
│   ├── radar_navigation.py
│   ├── redis_example_sub.py
│   ├── redis_get_key.py
│   ├── telemetry_reader.py
│   ├── telemetry_reader_gui.py
│   ├── update_telemetry_example.py
│   └── radar_visualizer.py
└── dashboard/           # FastAPI web dashboard (optional dep)
    ├── app.py
    ├── redis_reader.py
    └── static/
```

---

## Key entry points

```python
# Preferred: create Grid by name
from secontrol import Grid
grid = Grid.from_name("MyShip")

# Legacy: prepare_grid (auto-selects first grid)
from secontrol.common import prepare_grid
grid = prepare_grid()              # auto-select
grid = prepare_grid("MyShip")     # by name
grid = prepare_grid("123456")     # by ID

# Low-level Redis
from secontrol import RedisEventClient
client = RedisEventClient()
```

---

## Grid lifecycle

1. `Grid.__init__()` → subscribes to `se:<owner>:grid:<id>:gridinfo`
2. `auto_wake=True` (default) → sends "wake" command, waits for telemetry
3. Devices appear in `grid.devices` dict (keyed by device_id string)
4. Events: `grid.on("devices", cb)`, `grid.on("integrity", cb)`, `grid.on("damage", cb)`

---

## Device access patterns

```python
from secontrol.devices.lamp_device import LampDevice
from secontrol.devices.connector_device import ConnectorDevice

# Find devices by type
lamps = grid.find_devices_by_type(LampDevice)
connectors = grid.find_devices_by_type(ConnectorDevice)

# Access by ID
device = grid.devices.get("123456")
device = grid.devices_by_num.get(123456)

# Send command
device.send_command({"cmd": "enable"})
```

---

## Adding a new device

1. Create `src/secontrol/devices/<name>_device.py` — subclass `BaseDevice`
2. Register in `src/secontrol/devices/__init__.py` → `DEVICE_TYPE_MAP`
3. Add `from secontrol.devices.<name>_device import <Name>Device` to `__init__.py`
4. Register SE type string in `src/secontrol/base_device.py` → `DEVICE_REGISTRY`
5. Add tests in `tests/`
6. Document in `docs/DEVICE_REFERENCE.md`

**BaseDevice subclass template:**
```python
from secontrol.base_device import BaseDevice

class MyDeviceDevice(BaseDevice):
    device_kind = "my_device"

    def my_method(self, arg):
        return self.send_command({"cmd": "my_command", "arg": arg})
```

**Key BaseDevice attributes:**
- `self.grid` — parent Grid
- `self.device_id` — string block ID
- `self.metadata` — BlockInfo dict from telemetry
- `self.telemetry` — current telemetry state
- `self.name` — display name
- `self.device_type` — SE type string (e.g. `MyObjectBuilder_MyDevice`)
- `send_command(cmd_dict)` — publish command to Redis
- `update()` — refresh telemetry from Redis

---

## Redis channel conventions

| Pattern | Purpose |
|---|---|
| `se:<owner>:grids` | Grid list (published by game server) |
| `se:<owner>:grid:<id>:gridinfo` | Single grid telemetry (keyspace notification) |
| `se:<owner>:grid:<id>:damage` | Damage events |
| `se:<owner>:grid:<id>:blueprint` | Exported blueprint XML |
| `se.<player>.commands.grid.<id>` | Outbound commands to a grid |
| `se.<player>.commands.admin` | Admin commands (spawn, remove, teleport) |
| `se.commands.ack` | Admin command acknowledgements |
| `se:<owner>:answer` | Scan command responses |
| `se:<owner>:map:*` | Shared map data keys |

---

## Further reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — module map and runtime design
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) — full public API reference
- [docs/DEVICE_REFERENCE.md](docs/DEVICE_REFERENCE.md) — all device classes with methods
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md) — common patterns and recipes
- [docs/design-docs/index.md](docs/design-docs/index.md) — design decisions log
- [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md) — known technical debt
- [docs/EXAMPLES.md](docs/EXAMPLES.md) — 100+ examples catalog by category and difficulty
- [examples/organized/](examples/organized/) — runnable example scripts
- [CHANGELOG.md](CHANGELOG.md) — version history