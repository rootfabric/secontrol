# Agent quick start

This guide is the shortest path from a fresh checkout to a working local agent environment.

## 1. Clone and install

```bash
git clone https://github.com/rootfabric/secontrol.git
cd secontrol

python -m venv .venv
. .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## 2. Configure Redis gateway access

Create `.env` in the repository root:

```env
REDIS_USERNAME=
REDIS_PASSWORD=
SE_OWNER_ID=
SE_PLAYER_ID=
```

`REDIS_USERNAME` and `REDIS_PASSWORD` are obtained from:

```text
https://www.outenemy.ru/se/
```

## 3. Verify installation

```bash
python -c "import secontrol; print(secontrol.__file__)"
python commands/diagnostics/list_grids.py
```

## 4. First useful commands

```bash
python commands/diagnostics/list_grids.py
python commands/diagnostics/check_flight_ready.py --grid agent1
python commands/radar/space_survey.py --grid agent1
python commands/radar/ore_scanner.py --grid agent1
python commands/navigation/space_navigator_v5.py --grid agent1 --nearest-asteroid
python commands/docking/check_docking_status.py --grid agent1
python commands/docking/dock.py agent1 farpost0
```

## 5. Where to go next

- Agent/operator guide: `docs/playbooks/operator.md`
- Developer guide: `docs/playbooks/developer.md`
- Admin guide: `docs/playbooks/admin.md`
- Commands catalog: `commands/README.md`
- SDK examples: `examples/README.md`
- Architecture: `ARCHITECTURE.md`
