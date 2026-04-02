# ARCHITECTURE.md — secontrol

## Overview

`secontrol` is a Python library that wraps the Space Engineers Redis gateway. A game server publishes telemetry and accepts commands via Redis channels. The library subscribes to those channels, deserializes state into typed Python objects, and provides helper methods to send commands back.

```
Space Engineers game server
        │
        │ Redis pub/sub  (se.<owner>.<channel>)
        ▼
  RedisEventClient          ← low-level: publish, subscribe, keyspace notifications
        │
        ├── Grids            ← monitors se:<owner>:grids — grid discovery
        │     └── Grid       ← monitors se:<owner>:grid:<id>:gridinfo — single grid state
        │           └── BaseDevice (subclasses per block type)
        │
        ├── AdminUtilitiesClient  ← administrative commands
        └── common.py helpers    ← prepare_grid(), resolve_*()
```

## Module responsibilities

| Module | Responsibility |
|---|---|
| `redis_client.py` | Connection, pub/sub, keyspace notifications, retries |
| `grids.py` | `Grids` (grid list manager), `Grid` (single grid state + devices), `GridState`, `DamageEvent` |
| `base_device.py` | `BaseDevice` base class, `BlockInfo`, `DamageDetails`, device registry (`get_device_class`) |
| `devices/` | 30+ concrete device classes registered in `DEVICE_TYPE_MAP` |
| `common.py` | `prepare_grid()`, `Grid.from_name()` helpers, env-var resolvers, `close()` |
| `admin.py` | `AdminUtilitiesClient` — publishes admin commands, reads acks |
| `inventory.py` | `InventoryItem`, `InventorySnapshot` — typed inventory state |
| `item_types.py` | `ItemType`, `ItemCategory` enums |
| `controllers/` | Higher-level autopilot/radar controllers built on top of `Grid`/`BaseDevice` |
| `tools/` | Standalone CLI/GUI utilities, not part of the library public API |

## Redis channel conventions

| Pattern | Purpose |
|---|---|
| `se:<owner>:grids` | Grid list (published by game server) |
| `se:<owner>:grid:<id>:gridinfo` | Single grid telemetry (keyspace notification) |
| `se:<owner>:grid:<id>:damage` | Damage events |
| `se.<player>.commands.grid.<id>` | Outbound commands to a grid |
| `se.commands.ack` | Admin command acknowledgements |

## Grid lifecycle

```
Grid.__init__()
  → subscribe to se:<owner>:grid:<id>:gridinfo
  → read initial state (get_json)
  → _aggregate_devices_from_subgrids()
  → [auto_wake=True] send "wake" command → game server starts publishing full telemetry
```

## Device class registration

Devices register themselves via `devices/__init__.py` → `DEVICE_TYPE_MAP`. Unknown device types fall back to `BaseDevice`. External plugins can extend the registry via `entry_points`.

## Key patterns

- **Event callbacks**: `grid.on("devices_changed", cb)` / `grid.on("damage", cb)`
- **Command dispatch**: `grid.send_grid_command("wake")` → `redis.publish(channel, json)`
- **Retry**: `tenacity` retries on Redis `ConnectionError` throughout the client layer
- **State**: Grid and device state is kept in-process, updated on every Redis notification

## Dependency graph (simplified)

```
common.py
  └── grids.py (Grid, Grids)
        └── base_device.py (BaseDevice)
              └── redis_client.py (RedisEventClient)
                    └── redis (PyPI)

devices/ ──────────────→ base_device.py
controllers/ ──────────→ grids.py, base_device.py
tools/ ────────────────→ grids.py, redis_client.py (standalone scripts)
```

## Versions

Current: **0.3.0** — see [CHANGELOG.md](CHANGELOG.md)
