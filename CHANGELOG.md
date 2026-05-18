# Changelog

## [0.3.1] — 2025

- Added 26 concrete device classes (lamp, thruster, connector, assembler, projector, remote_control, ore_detector, etc.)
- Added `InventoryItem`, `InventorySnapshot` with typed inventory management
- Added `ContainerDevice` with tags, transfer helpers (`move_items`, `move_subtype`, `move_all`, `drain_to`)
- Added `ConnectorDevice` with remote transfer and scan capabilities
- Added `AssemblerDevice` with queue management and blueprint discovery
- Added `ProjectorDevice` with blueprint XML loading, offset/rotation control, export
- Added `OreDetectorDevice` with radar scanning and ore monitoring
- Added `RemoteControlDevice` with autopilot, goto, orientation vectors
- Added `RadarController` for voxel scanning, occupancy grid, surface height queries
- Added `SurfaceFlightController` for fly-over-surface autopilot
- Added `SharedMapController` for Redis-backed shared voxel maps
- Added `AdminUtilitiesClient` for spawn/remove/teleport grids, chat, mission screen
- Added `item_types.py` with `ItemType`, `ItemCategory`, `Item` registry
- Added `GridDevicesEvent`, `GridIntegrityChange`, `RemovedDeviceInfo` event types
- Added `grid.on("devices"|"integrity"|"damage", callback)` event system
- Added `devices_by_num` dict for numeric device ID lookup
- Added `subscribe_to_key_resilient()` with keyspace + channel + polling fallback
- Added dashboard module (FastAPI web UI, optional dependency)
- Added 60+ organized examples by device type and complexity

## [0.3.0] — 2025

- Bumped to version 0.3.0.
- Grid search via `Grids.search()`.
- Worker API integration with retries.
- `Grid.from_name()` factory method.
- `send_grid_command()` with auto-populated metadata fields.

## [0.2.x] — 2025

- Auto-wake on `Grid` construction: `Grid.__init__` now accepts `auto_wake=True` and wakes the grid automatically.
- Added device uptime visualization utilities (`tools/telemetry_reader.py`, `tools/telemetry_reader_gui.py`).
- Added retry logic for Redis operations and worker API access (`tenacity`).

## [0.1.0] — 2024-05-29

- Начальная публикация библиотеки `secontrol`.
- Добавлен высокоуровневый клиент `RedisEventClient` и утилиты для работы с гридами.
- Добавлены примеры использования и базовые тесты.
- Настроена упаковка проекта через `pyproject.toml`.
