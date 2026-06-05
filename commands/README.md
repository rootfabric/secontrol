# secontrol commands

Ready-to-run operational commands for Space Engineers agents.

These scripts are intended to be used directly by agents and operators. Keep educational API snippets in `examples/`; keep runnable workflows here.

## Diagnostics

```bash
python commands/diagnostics/list_grids.py
python commands/diagnostics/grid_report.py agent1
python commands/diagnostics/check_flight_ready.py --grid agent1
```

## Navigation

```bash
python commands/navigation/space_navigator_v5.py --grid agent1 --nearest-asteroid
python commands/navigation/space_navigator_v5.py --grid agent1 --target="GPS:Base:-137317:-111140:-82039:" --arrival 80
```

## Docking

```bash
python commands/docking/check_docking_status.py --grid agent1
python commands/docking/dock.py agent1 farpost0
python commands/docking/smooth_undock.py agent1 farpost0 40
```

## Radar and ores

```bash
python commands/radar/space_survey.py --grid agent1
python commands/radar/ore_scanner.py --grid agent1
python commands/radar/shared_map_report.py --grid agent1
python commands/radar/shared_map_deposits.py --grid agent1 --material Platinum --clusters --gps
```

## Mining

```bash
python commands/mining/mine_ore_robot_safe_live_move.py --grid agent1 --ore Platinum --amount 5000
```

## Production

```bash
python commands/production/grid_production.py --grid farpost0 --full
python commands/production/maintain_components.py --grid farpost0 --dry-run
python commands/production/maintain_components.py --grid farpost0
```

## Refinery

```bash
python commands/refinery/refinery_priority_operator.py --grid farpost0 --evaluate
python commands/refinery/refinery_priority_operator.py --grid farpost0 --apply
```

## Projector

```bash
python commands/projector/align_clone_projection.py farpost0 "C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-agent0\bp.sbc"
```

## Inventory

```bash
python commands/inventory/containers_show.py --grid farpost0
python commands/inventory/pull_items_from_docked_grid.py --source-grid agent1 --target-grid farpost0
```

## Rule for agents

1. Look for a ready command in `commands/`.
2. If no command exists, look for an SDK example in `examples/`.
3. If no example exists, read `docs/playbooks/developer.md` and then add code.
