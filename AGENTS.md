# AGENTS.md — secontrol developer reference

Quick-nav for humans and AI agents working in this repo.

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

## Env vars (required)

| Variable | Purpose |
|---|---|
| `REDIS_USERNAME` | Redis auth username (from outenemy.ru/se) |
| `REDIS_PASSWORD` | Redis auth password |
| `SE_OWNER_ID` | Space Engineers owner ID (auto-resolved if unset) |
| `SE_PLAYER_ID` | Player ID (falls back to owner ID) |

Place in `.env` at project root or export in shell.

## Source layout

```
src/secontrol/
  __init__.py          # Public API re-exports
  _version.py          # __version__ = "0.3.1"
  redis_client.py      # RedisEventClient — pub/sub, keyspace notifications
  grids.py             # Grid, Grids, GridState, DamageEvent, GridDevicesEvent, GridIntegrityChange
  base_device.py       # BaseDevice, BlockInfo, DamageDetails, DeviceMetadata, DEVICE_TYPE_MAP
  common.py            # prepare_grid(), Grid.from_name(), resolve_*(), close(), get_all_grids()
  admin.py             # AdminUtilitiesClient — spawn/remove/teleport grids, chat, mission screen
  inventory.py         # InventoryItem, InventorySnapshot
  item_types.py        # ItemType, ItemCategory, Item registry (Item.SteelPlate, Item.PlatinumOre...)
  device_types.py      # Legacy compatibility wrapper
  devices/             # 26 concrete device classes (see docs/DEVICE_REFERENCE.md)
    __init__.py        # DEVICE_TYPE_MAP registry, load_builtin_devices(), load_external_plugins()
    ai_device.py
    artillery_device.py
    assembler_device.py     # extends ContainerDevice — queue mgmt, blueprints
    battery_device.py
    build_and_repair_device.py
    cockpit_device.py
    connector_device.py     # extends ContainerDevice — lock/unlock, transfer_remote
    container_device.py     # inventory-aware base, tags, move_items, move_all
    conveyor_sorter_device.py
    display_device.py
    gas_generator_device.py
    gyro_device.py
    lamp_device.py           # color, intensity, radius
    large_turret_device.py
    nanobot_drill_system_device.py
    projector_device.py      # load_blueprint_xml, load_prefab, offset/rotation
    reactor_device.py
    refinery_device.py
    remote_control_device.py # autopilot, goto, orientation vectors
    rover_device.py
    ship_drill_device.py
    ship_grinder_device.py
    ship_tool_device.py
    ship_welder_device.py
    thruster_device.py       # thrust override
    weapon_device.py
    wheel_device.py
  controllers/         # High-level automation controllers
    radar_controller.py      # RadarController — voxel scanning, occupancy grid, surface height
    surface_flight_controller.py  # SurfaceFlightController — fly-over-surface autopilot
    shared_map_controller.py     # SharedMapController — Redis-backed shared voxel maps
  tools/               # Standalone CLI/GUI utilities (not public API)
    blueprint_editor.py
    check_redis_user.py
    create_restricted_redis_user.py
    device_load_monitor_gui.py
    navigation_tools.py      # fly_to_point, get_world_position, goto
    radar_navigation.py
    redis_example_sub.py
    redis_get_key.py
    telemetry_reader.py
    telemetry_reader_gui.py
    update_telemetry_example.py
    radar_visualizer.py
  dashboard/           # FastAPI web dashboard (optional dep)
    app.py
    redis_reader.py
    static/
admins/                # Admin-only scripts (require admin Redis credentials)
  tools/
    send_chat_message.py   # Send in-game chat via AdminUtilitiesClient
  ai_factions/
    admin_create_ai_faction_and_redis_user.py  # Create AI faction + Redis ACL user
    admin_spawn_grid_for_faction.py            # Spawn XML grid for a faction
    admin_assign_or_remove_grid.py             # Assign/remove grid from faction
```

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

## Grid lifecycle

1. `Grid.__init__()` → subscribes to `se:<owner>:grid:<id>:gridinfo`
2. `auto_wake=True` (default) → sends "wake" command, waits for telemetry
3. Devices appear in `grid.devices` dict (keyed by device_id string)
4. Events: `grid.on("devices", cb)`, `grid.on("integrity", cb)`, `grid.on("damage", cb)`

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

## Space movement rule

For normal ship movement in space, agents must use the space navigator workflow
instead of ad-hoc `RemoteControl.goto()` calls or one-off flight scripts.

Use:

```bash
python scripts/test_flight_nearest_asteroid.py --grid <grid-name>
```

or call `SpaceNavigatorController` from
`src/secontrol/controllers/space_navigator_controller.py` with the same
coarse/medium/fine scan behavior.

Exception: precise final parking, connector alignment, docking, and other
sub-meter/connector-specific maneuvers should use the dedicated parking/docking
workflow instead of the general space navigator.

## Agent Skills

Hermes agent skills для работы с SE — полный набор в [docs/agent-skills/](docs/agent-skills/).

| Скилл | Назначение |
|---|---|
| `secontrol-space-engineers` | **Основной SDK** — гриды, устройства, инвентарь, блюпринты, навигация |
| `se-grid-status-report` | Статус-репорт: блоки, повреждения, контейнеры |
| `se-projection-builder` | Проекционный цикл: XML → варка → покраска |
| `se-asteroid-approach` | Полёт к астероиду: скан → навигация → подход |
| `se-docking` | **Стыковка кораблей** — подход, разворот коннектором, сближение, auto-lock |
| `game-server-automation` | Redis pub/sub мониторинг, алерты |

Скрипты: `docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py`

Подробнее: [docs/agent-skills/README.md](docs/agent-skills/README.md)

## Docking workflow

Автоматическая стыковка корабля к базе через коннекторы.

```bash
# Полная стыковка (3 фазы: подлёт → разворот → сближение + lock)
python se-data/scripts/docking/dock.py [ship_id] [target_id] [approach_dist]

# Пример
python se-data/scripts/docking/dock.py 104571351454649539 84360909276756422 100
```

Фазы: (1) RC goto к точке 100м перед коннектором → (2) gyro P-controller разворот коннектором → (3) пошаговое сближение по оси коннекторов + auto-lock при `connectorStatus=Connectable`.

Документация: [docs/workflows/docking.md](docs/workflows/docking.md)

## Further reading

- [docs/workflows/docking.md](docs/workflows/docking.md) — docking system: design decisions, tech debt, validation
- [ARCHITECTURE.md](ARCHITECTURE.md) — module map and runtime design
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) — full public API reference
- [docs/DEVICE_REFERENCE.md](docs/DEVICE_REFERENCE.md) — all device classes with methods
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md) — common patterns and recipes
- [docs/design-docs/index.md](docs/design-docs/index.md) — design decisions log
- [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md) — known technical debt
- [README.md](README.md) — user-facing overview
- [docs/EXAMPLES.md](docs/EXAMPLES.md) — 100+ examples catalog by category and difficulty
- [examples/organized/](examples/organized/) — runnable example scripts
- Wiki: https://github.com/rootfabric/secontrol/wiki/home
