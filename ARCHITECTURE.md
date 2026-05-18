# ARCHITECTURE.md — secontrol

## Overview

`secontrol` is a Python library that wraps the Space Engineers Redis gateway. A game server publishes telemetry and accepts commands via Redis channels. The library subscribes to those channels, deserializes state into typed Python objects, and provides helper methods to send commands back.

```
Space Engineers game server
        │
        │ Redis pub/sub  (se:<owner>:<channel>)
        ▼
  RedisEventClient          ← low-level: publish, subscribe, keyspace notifications
        │
        ├── Grids            ← monitors se:<owner>:grids — grid discovery
        │     └── Grid       ← monitors se:<owner>:grid:<id>:gridinfo — single grid state
        │           └── BaseDevice (subclasses per block type)
        │
        ├── AdminUtilitiesClient  ← administrative commands (spawn, remove, teleport, chat)
        ├── controllers/          ← high-level automation (radar, flight, shared maps)
        └── common.py helpers     ← prepare_grid(), resolve_*()
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `redis_client.py` | Connection, pub/sub, keyspace notifications, retries (`tenacity`), polling fallback |
| `grids.py` | `Grids` (grid list manager), `Grid` (single grid state + devices), `GridState`, `DamageEvent`, `GridDevicesEvent`, `GridIntegrityChange` |
| `base_device.py` | `BaseDevice` base class, `BlockInfo`, `DamageDetails`, `DeviceMetadata`, device registry (`DEVICE_TYPE_MAP`, `DEVICE_REGISTRY`) |
| `devices/` | 26 concrete device classes registered in `DEVICE_TYPE_MAP` |
| `common.py` | `prepare_grid()`, `Grid.from_name()` helpers, env-var resolvers, `close()`, `get_all_grids()` |
| `admin.py` | `AdminUtilitiesClient` — spawn/remove/teleport grids, voxels, chat, mission screen |
| `inventory.py` | `InventoryItem`, `InventorySnapshot` — typed inventory state |
| `item_types.py` | `ItemType`, `ItemCategory`, `Item` registry (e.g. `Item.SteelPlate`, `Item.PlatinumOre`) |
| `device_types.py` | Legacy compatibility wrapper (re-exports from `devices/`) |
| `controllers/` | `RadarController` (voxel scanning, occupancy grid), `SurfaceFlightController` (fly-over-surface), `SharedMapController` (Redis-backed shared maps) |
| `tools/` | Standalone CLI/GUI utilities (navigation, telemetry viewer, blueprint editor) — not part of public API |
| `dashboard/` | Optional FastAPI web dashboard for grid monitoring |

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

## Grid lifecycle

```
Grid.__init__()
  → subscribe to se:<owner>:grid:<id>:gridinfo
  → read initial state (get_json)
  → _aggregate_devices_from_subgrids()
  → [auto_wake=True] send "wake" command → game server starts publishing full telemetry
  → wait_until_ready() — polls until detailLevel != "summary" or devices appear
```

## Device class registration

Devices register themselves via `devices/__init__.py` → `DEVICE_TYPE_MAP`. Unknown device types fall back to `BaseDevice`. External plugins can extend the registry via `entry_points` (group: `secontrol.devices`).

The `DEVICE_REGISTRY` in `base_device.py` maps SE internal type strings (e.g. `MyObjectBuilder_Projector`) to simplified device type keys (e.g. `projector`).

## Key patterns

- **Event callbacks**: `grid.on("devices", cb)` / `grid.on("damage", cb)` / `grid.on("integrity", cb)`
- **Device events**: `device.on("telemetry", cb)` — fired on every telemetry update
- **Command dispatch**: `device.send_command({"cmd": "..."})` → `redis.publish(channel, json)`
- **Retry**: `tenacity` retries on Redis `ConnectionError` throughout the client layer
- **Resilient subscription**: `subscribe_to_key_resilient()` combines keyspace + channel + polling
- **State**: Grid and device state is kept in-process, updated on every Redis notification
- **Inventory transfer**: `ContainerDevice.move_items()` / `move_subtype()` / `move_all()` for cross-device transfers
- **Blueprint workflow**: `ProjectorDevice.load_blueprint_xml()` → welder builds → `remaining_blocks()` to track

## Dependency graph (simplified)

```
common.py
  └── grids.py (Grid, Grids)
        └── base_device.py (BaseDevice, DEVICE_TYPE_MAP)
              └── redis_client.py (RedisEventClient)
                    └── redis (PyPI)

devices/ ──────────────→ base_device.py, inventory.py
controllers/ ──────────→ grids.py, base_device.py, devices/, tools/
tools/ ────────────────→ grids.py, redis_client.py (standalone scripts)
dashboard/ ────────────→ grids.py, redis_client.py (FastAPI, optional)
item_types.py ─────────→ inventory.py
```

## External dependencies

| Package | Purpose |
|---|---|
| `redis>=4.5` | Redis client |
| `python-dotenv>=1.0` | `.env` file loading |
| `numpy>=1.26` | Occupancy grid math (RadarController) |
| `tenacity>=8.0` | Retry logic for Redis operations |
| `requests>=2.25` | HTTP requests (worker API) |

## Versions

Current: **0.3.1** — see [CHANGELOG.md](CHANGELOG.md)
