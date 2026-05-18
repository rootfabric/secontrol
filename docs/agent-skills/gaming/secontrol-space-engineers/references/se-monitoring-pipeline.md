# Space Engineers Monitoring Pipeline

Continuous surveillance system for detecting players and foreign grids near owned grids.
Built from three scripts, scheduled via Hermes cron.

## Architecture

```
SE Scanner (every 5 min)
    ↓ se_player_scan.py
    └─ scans all grids via OreDetector telemetry
       ├─ players: t['players'] (needs includePlayers=True)
       ├─ foreign_grids: t['detectedgrids'] minus own grid IDs
       └─ writes: logs/active_alert.json

Alert Watcher (every 1 min)
    ↓ se_alert_watcher.py
    └─ reads active_alert.json
       ├─ detects new threat (hash deduplication)
       ├─ creates Kanban card via hermes kanban create
       └─ writes: logs/processed_alerts.json (dedup)

Alert Agent (on card dispatch)
    └─ se_alert_agent.py
       ├─ reads alert state
       ├─ collects our grid positions
       ├─ assesses risk (CRITICAL/HIGH/LOW)
       └─ writes: logs/journal.jsonl (permanent log)
```

## Files

| File | Purpose |
|------|---------|
| `~/.hermes/scripts/se_player_scan.py` | Scanner — polls all grids every 5 min |
| `~/.hermes/scripts/se_alert_watcher.py` | Watcher — checks alerts, creates Kanban cards |
| `~/.hermes/scripts/se_alert_agent.py` | Agent — assesses threats, writes journal |
| `~/.hermes/scripts/logs/active_alert.json` | Current alert state (players, foreign_grids) |
| `~/.hermes/scripts/logs/processed_alerts.json` | Dedup: alert hash → task_id |
| `~/.hermes/scripts/logs/scan_YYYY-MM-DD.jsonl` | All scan results |
| `~/.hermes/scripts/logs/journal.jsonl` | All threat events (permanent) |

## Known grid IDs (us)

Used to filter `detectedgrids` — anything not in this set is foreign:

```
DroneBase 2     → 134540402238780591
DroneBase        → 138748817302648345
taburet3         → 74055729860857332
taburet2         → 98945391841930411
taburet5         → 125173132660614842
Respawn Rover    → 82069157247683112
Core1            → 143139590779134749
skynet-baza1     → 118163643286714656
skynet-baza0     → 127817843801970018
```

## Risk Levels

| Level | Trigger | Kanban Priority | Skills |
|-------|---------|-----------------|--------|
| CRITICAL | foreign_grid detected | 100 | secontrol-space-engineers, dogfood |
| HIGH | player(s) detected | 60-70 | secontrol-space-engineers, dogfood |
| LOW | no threats | 10 | dogfood |

## Ore Detector Configuration Required

For player/grid detection to work, each Ore Detector needs:
- `scan.includePlayers = True`
- `scan.includeGrids = True`
- `scan.includeVoxels = True` (keep for ore scanning)

In the current setup:
- taburet3: only voxels enabled — needs in-game toggle
- Respawn Rover, taburet2: fully configured

## Cron Jobs

```bash
hermes cron list
# Should show:
# - SE Scanner 5min  (every 5m, no_agent, se_player_scan.py)
# - SE Alert Watcher (every 1m, no_agent, se_alert_watcher.py)
```

## Known Issues

- **HERMES_EXEC_ASK bug**: When running hermes kanban create from Python subprocess in WebUI
  context, `os.environ.pop("HERMES_EXEC_ASK", None)` must be called BEFORE subprocess.run().
  Pass `env=None` (inherit cleaned env). Do NOT use a custom `env={}` dict.
- **taburet3 detector only scans voxels** — includePlayers/includeGrids need to be toggled
  in-game for full threat detection on that grid.