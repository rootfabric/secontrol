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
  redis_client.py      # RedisEventClient — pub/sub, keyspace notifications
  grids.py             # Grid, Grids, GridState, DamageEvent
  base_device.py       # BaseDevice, BlockInfo, DamageDetails
  common.py            # prepare_grid(), resolve_*(), close(), get_all_grids()
  admin.py             # AdminUtilitiesClient
  inventory.py         # InventoryItem, InventorySnapshot
  item_types.py        # ItemType, ItemCategory
  devices/             # 30+ device classes (lamp, thruster, connector…)
  controllers/         # RadarController, SurfaceFlightController, SharedMapController
  tools/               # CLI/GUI utilities (telemetry viewer, blueprint editor…)
```

## Key entry points

- **`prepare_grid()`** — create a `Grid` from env vars, auto-wakes
- **`Grid.from_name("MyShip")`** — create `Grid` by name lookup, auto-wakes
- **`Grid(...)`** — direct construction, also auto-wakes by default (`auto_wake=True`)
- **`RedisEventClient()`** — low-level Redis wrapper

## Further reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — module map and runtime design
- [docs/design-docs/index.md](docs/design-docs/index.md) — design decisions log
- [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md) — known technical debt
- [README.md](README.md) — user-facing overview
- [examples/organized/](examples/organized/) — 113+ usage examples by device type
- Wiki: https://github.com/rootfabric/secontrol/wiki/home
