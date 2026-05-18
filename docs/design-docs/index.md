# Design Decisions

Chronological log of meaningful design decisions made during development.

---

## 2024-05 — Initial architecture: Redis pub/sub as transport

**Decision:** Use Redis keyspace notifications and pub/sub as the sole transport between the game server gateway and the Python library.

**Why:** The Space Engineers gateway already publishes all telemetry to Redis. A direct Redis subscription avoids polling and gives near-real-time updates with minimal overhead.

**Trade-off:** Requires Redis to be reachable from the script host. Local scripts connect to the hosted Redis instance at outenemy.ru.

---

## 2024 — Device class registry via `DEVICE_TYPE_MAP`

**Decision:** All device types are registered in a central dict (`devices/__init__.py`). `get_device_class(type_str)` returns the right subclass, falling back to `BaseDevice`.

**Why:** Avoids giant if/elif chains. Allows external plugins to register additional device types via `entry_points` without modifying the library.

**Files:** `base_device.py`, `devices/__init__.py`

---

## 2024 — `prepare_grid()` as primary entry point (now soft-deprecated)

**Decision:** `prepare_grid()` was the original one-call entry point. It resolves env vars, connects Redis, finds the grid, and returns a ready `Grid`.

**Status:** Soft-deprecated in favor of `Grid.from_name("MyShip")`, which is more explicit. `prepare_grid()` remains for backward compatibility.

**Files:** `common.py`

---

## 2025 — Redis retries via `tenacity`

**Decision:** Added retry logic around Redis publish and subscribe operations using the `tenacity` library (3 attempts, 0.1 s × attempt backoff).

**Why:** Redis connections to the hosted gateway occasionally drop. Scripts were failing silently or crashing on transient network blips.

**Files:** `redis_client.py`

---

## 2025 — Auto-wake on `Grid` construction (`auto_wake=True`)

**Decision:** `Grid.__init__` now accepts `auto_wake: bool = True` and calls `self.wake()` automatically at the end of construction.

**Why:** Every script needs to wake the grid before devices appear. Forgetting to call `wake()` was a common pain point. Making it the default removes boilerplate.

**Trade-off:** Direct `Grid()` construction now sends a Redis command immediately. Pass `auto_wake=False` to suppress (e.g. in `prepare_grid()` and `Grid.from_name()` which manage the wake timeout themselves).

**Files:** `grids.py` (`Grid.__init__`, `Grid.from_name`), `common.py` (`prepare_grid`)

---

## 2025 — ContainerDevice with tags and transfer helpers

**Decision:** `ContainerDevice` extends `BaseDevice` with inventory management, tag system (from block name `[tag]` and custom data), and cross-device transfer methods (`move_items`, `move_subtype`, `move_all`, `drain_to`).

**Why:** Inventory operations are the most common use case. Centralizing transfer logic in `ContainerDevice` avoids repetitive boilerplate in every script.

**Trade-off:** `ConnectorDevice`, `AssemblerDevice`, and `RefineryDevice` all inherit from `ContainerDevice`, which adds some complexity to the class hierarchy.

**Files:** `devices/container_device.py`, `devices/connector_device.py`, `devices/assembler_device.py`

---

## 2025 — Event system on Grid (`grid.on(event, callback)`)

**Decision:** Added `grid.on()` / `grid.off()` for `"devices"`, `"integrity"`, and `"damage"` events. Events fire `_emit()` which swallows callback exceptions.

**Why:** Scripts need to react to device changes (new blocks appearing, damage events) without polling. The event system decouples monitoring from command logic.

**Trade-off:** Callbacks run in the Redis subscription thread. Long-running callbacks can block telemetry processing.

**Files:** `grids.py`

---

## 2025 — Item type registry (`item_types.py`)

**Decision:** Created `ItemType`, `ItemCategory`, and `Item` registry for typed inventory checks. Access via `Item.SteelPlate`, `Item.PlatinumOre`, etc.

**Why:** String-based item checks (`item.subtype == "SteelPlate"`) are error-prone and scattered across scripts. A typed registry enables IDE autocompletion and centralized validation.

**Files:** `item_types.py`

---

## 2025 — Resilient Redis subscriptions

**Decision:** `subscribe_to_key_resilient()` combines three subscription paths: keyspace notifications, direct channel subscribe, and a lightweight polling loop. A 100ms de-duplication window prevents double-calling.

**Why:** Different SE bridge configurations expose telemetry differently. Some use keyspace notifications, some PUBLISH to channels, some only update key values. The resilient subscription handles all three.

**Files:** `redis_client.py`

---

## 2025 — RadarController with occupancy grid

**Decision:** `RadarController` builds a 3D numpy occupancy grid from radar voxel data. `get_surface_height()` queries the grid for surface altitude at any world coordinate.

**Why:** Flight-over-surface automation needs to know terrain height ahead. The occupancy grid is built once from a scan and queried many times, avoiding repeated full scans.

**Files:** `controllers/radar_controller.py`, `controllers/surface_flight_controller.py`

---

## 2026-05 — Examples documentation: catalog by category + difficulty

**Decision:** Document all 100+ examples in `docs/EXAMPLES.md` as a structured catalog organized by domain (grid, autopilot, radar, etc.) with difficulty levels (basic/intermediate/advanced). Each entry has a one-line description and key patterns demonstrated.

**Why:** Agents and developers need to quickly find relevant examples without browsing 18 directories. A flat catalog with cross-references to API docs reduces onboarding time and prevents duplicate code.

**Files:** `docs/EXAMPLES.md`, `AGENTS.md`
