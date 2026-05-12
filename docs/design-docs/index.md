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

---

## 2024 — `prepare_grid()` as primary entry point (now soft-deprecated)

**Decision:** `prepare_grid()` was the original one-call entry point. It resolves env vars, connects Redis, finds the grid, and returns a ready `Grid`.

**Status:** Soft-deprecated in favor of `Grid.from_name("MyShip")`, which is more explicit. `prepare_grid()` remains for backward compatibility.

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
