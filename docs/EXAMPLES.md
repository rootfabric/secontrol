# Examples Reference — secontrol

> **Canonical path:** `examples/organized/`
> **Total:** 100+ runnable Python scripts across 18 categories, organized by difficulty (basic → intermediate → advanced).

Every example is a standalone script. Most can be run with:
```bash
python examples/organized/<category>/<difficulty>/<script>.py
```

Prerequisites: `pip install -e ".[dev]"`, Redis connection, Space Engineers gateway running.

---

## Quick-Start (basic/)

| Script | What it does |
|---|---|
| `basic/basic/fast_example.py` | Connect to grid, print all device names — minimal 4-line example |
| `basic/basic/toggle_device.py` | Toggle power state of first device on/off with telemetry readback |
| `basic/intermediate/gui_telemetry_viewer.py` | GUI-based telemetry viewer |
| `basic/intermediate/ore_scan.py` | Subscribe to OreDetector telemetry, run scan, print results |
| `basic/intermediate/nanobot_drill_filter_example.py` | Nanobot Drill filter configuration |

**Key patterns demonstrated:** `prepare_grid()`, `close()`, `device.is_enabled()`, `device.set_enabled()`, `device.telemetry`.

---

## Grid Management (grid/)

### basic/ — List, search, print

| Script | What it does |
|---|---|
| `list_grids.py` | Use `Grids` manager to list all grids for an owner |
| `search_grids.py` | Search grids by name/ID with `Grids.search(query)` |
| `print_devices.py` | Connect to grid, iterate `grid.devices`, print ID/name/type |

### intermediate/ — Events, rename, resources

| Script | What it does |
|---|---|
| `grid_events_demo.py` | Track all grids with detailed change events (blocks, devices, damage) |
| `grid_rename_example.py` | Rename grid via `grid.rename(new_name)` |
| `grid_rename_device_example.py` | Rename individual device blocks |
| `grid_show_resources.py` | Display grid resource summary |
| `grid_park_power_example.py` | Park mode: toggle power on all blocks |
| `random_color_blocks.py` | Randomize block colors |

### advanced/ — Damage, integrity, painting

| Script | What it does |
|---|---|
| `grid_damage_listener.py` | Subscribe to `DamageEvent` with attacker info and deformation tracking |
| `grid_damage_tracking.py` | Track damage over time with statistics |
| `grid_integrity_monitor.py` | Full integrity monitor: stats, trends, categories (healthy/damaged/critical/destroyed), interactive mode |
| `paint_grid_blocks.py` | Paint blocks with random/deliberate RGB colors via `grid.iter_blocks()` |
| `paint_image_on_grid.py` | Map image pixels to block colors |
| `upload_image_example.py` / `upload_image_example2.py` | Upload images to display panels |

**Key patterns:** `grid.on("damage", cb)`, `grid.on("integrity", cb)`, `grid.iter_blocks()`, `grid.rename()`, `BlockInfo`, `DamageEvent`, `GridIntegrityChange`.

---

## Beacons (beacon/)

| Script | What it does |
|---|---|
| `set_beacon_to_grid_name.py` | Set beacon content to match grid name — `beacon.send_command({"cmd": "set_name", "name": new_content})` |
| `rename_beacon_example.py` | Rename beacon content text visible to all players |

**Key patterns:** `grid.find_devices_by_type("beacon")`, `device.send_command({"cmd": "set_name", "name": ...})`.

---

## Connectors (connector/)

| Script | What it does |
|---|---|
| `basic/connector_full_demo.py` | Full connector demo: scan, lock/unlock, transfer items, telemetry |
| `basic/connector_scan_simple.py` | Find connector, print telemetry, connect |

**Key patterns:** `grid.find_devices_by_type(ConnectorDevice)`, `connector.connect()`, `connector.disconnect()`, `connector.transfer_to_nearby()`.

---

## Containers & Inventory (container/, inventory/)

### container/basic/

| Script | What it does |
|---|---|
| `container_simple_item_mover.py` | Move items between containers using tags in container names (`[ore]`, `[ingot]`) |

### container/intermediate/

| Script | What it does |
|---|---|
| `container.py` | Single container inventory inspection |
| `containers.py` | Multi-container inventory listing |
| `transfer_items_cross_grid.py` | Transfer items between containers on different grids |
| `transfer_items_script.py` | Scripted item transfer workflow |

### container/advanced/

| Script | What it does |
|---|---|
| `container_display_sync.py` | Sync container inventory to display panel |
| `pull_from_attached_ships.py` | Pull all items from docked subgrid ships into main grid |

### inventory/advanced/

| Script | What it does |
|---|---|
| `inventory_transfer_demo.py` | Transfer items between container→refinery→assembler with `InventorySnapshot` |
| `inventory_sorter.py` | Sort items by category across containers |
| `grid_simple_transfer_test_uranium_ore_to_ref.py` | Move uranium ore to refinery |
| `grid_simple_transfer_test_platinum_ore_to_ref_and_work.py` | Move platinum ore to refinery and start processing |
| `grid_simple_transfer_uranium_ingots_from_ref_to_ignot.py` | Move uranium ingots from refinery output |

**Key patterns:** `ContainerDevice.get_inventory()`, `InventorySnapshot.items`, `ContainerDevice.move_items()`, `ContainerDevice.move_all()`, `ContainerDevice.tags`, `Item.*` constants.

---

## Autopilot & Navigation (autopilot/)

### old/ — Legacy examples

| Script | What it does |
|---|---|
| `drone_goto.py` | Fly drone to GPS coordinate using `goto()` |
| `simple_forward_align.py` | Align ship forward and fly straight |
| `simple_gravity_align.py` | Align to gravity vector |
| `ship_park_with_grid_align.py` | Park ship with grid alignment |
| `return_home.py` | Return drone to home position |
| `patrol_1_fix_point.py` | Patrol between fixed waypoints |
| `drone_dock_simple.py` / `drone_dock_highlevel.py` / `drone_dock_helpers.py` | Docking procedures |

### rc_simple/

| Script | What it does |
|---|---|
| `settings.py` | Remote Control device settings configuration |

### patrol/

| Script | What it does |
|---|---|
| `patrol.py` | Patrol with radar-based terrain awareness using `SurfaceFlightController` |
| `patrol_forward.py` | Forward patrol with distance tracking |

### go_home/

| Script | What it does |
|---|---|
| `drone_dock_to_connector_with_status_checks.py` | Full docking sequence: RC approach → connector alignment → lock with status monitoring |

### harvest/

| Script | What it does |
|---|---|
| `simple_harvest.py` | Nanobot Drill harvest with ore filtering |
| `simple_go_to_res.py` | Navigate to resource deposit |
| `simple_nano_focus_to_res.py` | Focus drill on specific resource |
| `simple_ores_filter.py` | Configure ore filter for drill |
| `harvest_full.py` | Complete harvest workflow |

### space/

| Script | What it does |
|---|---|
| `space_navigator_v3.py` | Two-phase asteroid approach: fast flight (30 m/s) → slow approach (5 m/s) with voxel distance stopping |
| `voxel_distance_meter.py` | Measure distance to nearest voxel surface |

**Key patterns:** `RemoteControlDevice.goto()`, `SurfaceFlightController`, `RadarController.scan_voxels()`, `goto()` from `tools/navigation_tools`.

---

## Radar & Scanning (radar/)

### basic/

| Script | What it does |
|---|---|
| `radar_controller_example.py` | Create `RadarController`, scan voxels with `ore_only=True`, print results |
| `radar_voxel_visualization.py` | Visualize voxel scan data |
| `radar_ore_then_voxels.py` | Two-pass scan: ore first, then full voxels |
| `asteroid_index_example.py` | Build asteroid index from scan data |

### intermediate/

| Script | What it does |
|---|---|
| `fly_over_surface_example.py` | `SurfaceFlightController.calculate_surface_point_at_altitude()` and `fly_forward_to_altitude()` |
| `fly_over_surface_far.py` | Long-range surface flight |
| `lift_over_surface_example.py` | Lift off while maintaining altitude over terrain |
| `radar_solid_visualization.py` | Visualize solid voxel points |
| `shared_map_memory.py` | Use `SharedMapController` for Redis-backed persistent maps |
| `simple_radar_tracker.py` | Track moving objects via radar |

### advanced/

| Script | What it does |
|---|---|
| `radar_pathfinding_to_target.py` | A* pathfinding with incremental radar map updates + rover auto-drive |
| `radar_real_map_and_pathfinding_test.py` | Real-world map pathfinding test |
| `radar_mock_map_and_pathfinding_test.py` | Mock map for pathfinding validation |

### Standalone

| Script | What it does |
|---|---|
| `ore_deposit_scanner.py` | Full ore deposit scanner: scans asteroid, saves JSON with ore coordinates, supports `--full_scan` for geometry |

**Key patterns:** `RadarController(radar, radius, cell_size, ore_only)`, `controller.scan_voxels()`, `SurfaceFlightController`, `SharedMapController`, `RawRadarMap`, `PathFinder`.

---

## Map Management (map/)

| Script | What it does |
|---|---|
| `scan_and_save_map.py` | Scan with `RadarController`, save to `SharedMapController` |
| `load_and_visualize_map.py` | Load saved map and visualize |
| `map_test.py` | Map operations test |
| `map_resourses.py` | Resource mapping |
| `map_zip.py` | Compress/export map data |
| `map_remove_points_in_radius_example.py` | Remove points within radius from map |

**Key patterns:** `SharedMapController`, `RadarController`, persistent Redis-backed maps.

---

## Projector & Blueprints (projector/)

| Script | What it does |
|---|---|
| `grid_blueprint_exporter.py` | Export grid blueprint to XML via `projector.request_grid_blueprint(include_connected=True)` |
| `grid_blueprint_loader.py` | Load XML blueprint into projector via `projector.load_blueprint_xml()` |
| `print_blueprints.py` | Print available blueprints |
| `grid_blueprint.xml` | Example blueprint XML file |

**Key patterns:** `ProjectorDevice.request_grid_blueprint()`, `ProjectorDevice.load_blueprint_xml()`, `ProjectorDevice.load_prefab()`.

---

## Display Panels (display/)

### basic/

| Script | What it does |
|---|---|
| `display_hello.py` | Set text on LCD panels: `display.set_text("Hello world!")` |
| `display_image_rgb.py` | Send RGB image to LCD panel (uses Pillow for image generation) |

### intermediate/

| Script | What it does |
|---|---|
| `display_demo.py` | Display functions demo |

### advanced/

| Script | What it does |
|---|---|
| `display_benchmark.py` / `display_benchmark_my.py` | Display rendering performance benchmarks |
| `displays_benchmark.py` | Multi-display benchmark |

**Key patterns:** `DisplayDevice.set_text()`, `DisplayDevice.set_image_rgb()`, `grid.find_devices_by_type(DisplayDevice)`.

---

## Rover Control (rover/)

### basic/

| Script | What it does |
|---|---|
| `rover_simple_control.py` | Create `RoverDevice`, find wheels, drive forward/stop |
| `rover_move_forward_20m.py` | Drive forward 20 meters using position tracking |

### intermediate/

| Script | What it does |
|---|---|
| `rover_wheel_control.py` | Direct wheel suspension control |

### advanced/

| Script | What it does |
|---|---|
| `rover_track_player_move_to_point.py` | Radar-based player tracking: scan → extract player position → `rover.move_to_point()` |

**Key patterns:** `RoverDevice(grid)`, `rover.wheels`, `rover.drive_forward()`, `rover.move_to_point()`, `rover.stop()`.

---

## Refinery (refinery/)

| Script | What it does |
|---|---|
| `intermediate/refinery_queue_example.py` | View/add/clear refinery queue: `refinery.queue()`, blueprint management |
| `intermediate/refinery_priority.py` | Auto-manage refinery priority: scan containers for ores, set top-3 priority items |

**Key patterns:** `RefineryDevice.queue()`, `RefineryDevice.add_to_queue()`, `RefineryDevice.clear_queue()`, `ContainerDevice.inventory_items()`.

---

## Assembler (assembler/)

| Script | What it does |
|---|---|
| `intermediate/assembler_queue_viewer.py` | View/clear assembler queue: `assembler.queue()` |
| `intermediate/assembler_queue_clear.py` | Clear assembler queue |
| `intermediate/assembler_blueprints_viewer.py` | List available blueprints |
| `advanced/assembler_produce.py` | Full production workflow: check inventory → calculate needed materials → queue production |

**Key patterns:** `AssemblerDevice.queue()`, `AssemblerDevice.add_to_queue()`, `AssemblerDevice.blueprints()`, `Item.SteelPlate` constants.

---

## Lamp Control (lamp/)

| Script | What it does |
|---|---|
| `intermediate/lamp_blink.py` | Blink lamps on/off with configurable interval |
| `intermediate/lamp_blind.py` | Flash all lamps to maximum brightness |

**Key patterns:** `LampDevice.set_enabled()`, `LampDevice.set_color()`, `LampDevice.set_intensity()`.

---

## Artillery (artillery/)

| Script | What it does |
|---|---|
| `basic/artillery_fire.py` | Check ammo, fire once: `artillery.shoot_once()`, `artillery.ammo_status()` |

**Key patterns:** `ArtilleryDevice.shoot_once()`, `ArtilleryDevice.ammo_status()`, `ArtilleryDevice.is_reloading()`.

---

## Drill (drill/)

| Script | What it does |
|---|---|
| `simple_drill.py` | Enable/disable ship drill: `drill.set_enabled(True/False)` |

**Key patterns:** `ShipDrillDevice`, `grid.get_first_device()`.

---

## Parking & Docking (examples/organized/parking/)

| Script | What it does |
|---|---|
| `check_docking_status.py` | Показать статус парковки всех гридов (коннектор → Connected/Unconnected/Connectable) |
| `park_drone.py` | Park drone above base connector: find connector position, fly to coordinates |
| `park_drone_auto.py` | Automated parking with position feedback |
| `park_mode.py` | Enter/exit park mode |
| `analyze_park.py` | Analyze parking alignment |
| `final_dock.py` | Monitor connector status, auto-connect when `Connectable` |
| `fly_forward_10m.py` | Simple forward flight test |
| `lift_drone.py` | Lift drone vertically |
| `undock_drone.py` | Undock from connector |
| `undock_and_fix.py` | Undock and fix orientation |
| `return_drone_to_base.py` | Navigate drone back to base |

**Key patterns:** `Grid.from_name()`, `connector.telemetry.get("position")`, `connector.telemetry.get("connectorStatus")`, `RemoteControlDevice.goto()`.

**Full documentation:** `examples/organized/parking/README.md`

---

## Diagnostics (diagnostics/)

| Script | What it does |
|---|---|
| `check_grids.py` | List all grids, verify Redis connection |
| `check_generator.py` / `check_generator_build.py` / `check_generator_raw.py` | Generator status checks at different levels |
| `check_drone_status.py` / `check_dronebase.py` | Drone health checks |
| `check_base_devices.py` | List all devices on base grid |
| `check_gen_blocks.py` / `check_gen_final.py` / `check_gen_now.py` / `check_gen_status.py` | Generator block inspection |
| `diag_connector.py` | Connector diagnostics |
| `diag_control.py` | Remote control diagnostics |
| `diagnose_welder.py` | Welder status check |
| `find_drone.py` / `find_drone_tab3.py` / `find_clone.py` / `find_taburet2.py` | Locate specific grids by name/ID |

**Key patterns:** `RedisEventClient()`, `client.list_grids()`, `Grids(client, owner_id)`, telemetry inspection.

---

## Utilities (utils/)

| Script | What it does |
|---|---|
| `list_all_grids.py` | List all grids with metadata (subgrid status, static, parent) |
| `weld_generator.py` | Enable welder to build projector blocks on DroneBase |
| `build_generator.py` | Build generator via projector+welder workflow |
| `rename_clone.py` / `rename_taburet.py` | Rename grids |
| `repair_rc.py` | Repair Remote Control device |
| `fix_control.py` | Fix control surface settings |

**Key patterns:** `Grid.from_name()`, `grid.find_devices_by_type("ship_welder")`, projector+welder workflow.

---

## Worker API (worker/)

| Script | What it does |
|---|---|
| `worker_api_example.py` | Create/manage programs via Worker API: list, create, upload code, run |
| `worker_get_logs_program.py` | Retrieve program execution logs |
| `example_app_params.py` | Pass parameters to worker programs |
| `WorkerApi.py` | WorkerApiClient helper class |

**Note:** These examples use a separate Worker API, not the core secontrol device API.

---

## Memory (memory/)

| Script | What it does |
|---|---|
| `memory_example.py` | Store/retrieve structured data in Redis: `client.set_memory()`, `client.get_memory()` |

**Key patterns:** Direct Redis key access for persistent data storage.

---

## AI (ai/)

| Script | What it does |
|---|---|
| `simple_agent.py` | Minimal AI agent skeleton (empty template) |

---

## Difficulty Levels

| Level | Meaning |
|---|---|
| **basic** | Single device, single action, minimal setup. Good starting point. |
| **intermediate** | Multi-device coordination, event handling, configuration. |
| **advanced** | Cross-grid operations, pathfinding, image processing, full workflows. |
| *(no level)* | Standalone utility or diagnostic script. |

---

## Common Patterns Across All Examples

### 1. Connection
```python
# Preferred (v0.3+)
from secontrol import Grid
grid = Grid.from_name("MyShip")

# Legacy (still works)
from secontrol.common import prepare_grid
grid = prepare_grid("MyShip")
```

### 2. Device Discovery
```python
from secontrol.devices.connector_device import ConnectorDevice

# By class
connectors = grid.find_devices_by_type(ConnectorDevice)

# By string alias
connectors = grid.find_devices_by_type("connector")

# First match
connector = grid.get_first_device(ConnectorDevice)
```

### 3. Telemetry Access
```python
device.telemetry              # dict of current telemetry
device.is_enabled()           # power state
device.set_enabled(True)      # toggle power
device.name                   # display name
device.device_id              # numeric ID string
device.device_type            # type string
```

### 4. Cleanup
```python
from secontrol.common import close
close(grid)                   # unsubscribe, clean up
# or
grid.close()
```

### 5. Event Subscriptions
```python
grid.on("damage", callback)       # DamageEvent
grid.on("integrity", callback)    # integrity changes
grid.on("devices", callback)      # device list changes
```

---

## See Also

- [API_REFERENCE.md](API_REFERENCE.md) — Full public API
- [DEVICE_REFERENCE.md](DEVICE_REFERENCE.md) — All device classes with methods
- [WORKFLOWS.md](WORKFLOWS.md) — Common patterns and recipes
- [../AGENTS.md](../AGENTS.md) — Quick-start guide
