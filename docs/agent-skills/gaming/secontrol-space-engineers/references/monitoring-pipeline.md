# SE Monitoring Pipeline — scripts

Location: `~/.hermes/scripts/` (symlinked or actual path).

## se_player_scan.py

```python
#!/usr/bin/env python3
"""Scan all grids for players and foreign grids. Run via cron every 5m."""

import sys, os, json, socket
from datetime import datetime, timezone

WORKSPACE = "/workspace"
sys.path.insert(0, os.path.join(WORKSPACE, "src"))

dotenv_path = os.path.join(WORKSPACE, ".env")
if os.path.exists(dotenv_path):
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

from secontrol.common import get_all_grids, resolve_owner_id, resolve_player_id
from secontrol import Grid, RedisEventClient

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
SCAN_LOG    = os.path.join(LOG_DIR, f"scan_{TODAY}.jsonl")
ALERT_FILE  = os.path.join(LOG_DIR, "active_alert.json")

OWN_GRID_IDS = {
    "134540402238780591",  # DroneBase 2
    "138748817302648345",  # DroneBase
    "74055729860857332",   # taburet3
    "98945391841930411",   # taburet2
    "82069157247683112",   # Respawn Rover
}

def redis_reachable() -> bool:
    try:
        host = os.environ.get("REDIS_URL", "redis://192.168.0.15:6379")
        host = host.replace("redis://", "").split(":")[0]
        port = 6379
        if ":" in host:
            h, p = host.split(":", 1)
            host, port = h, int(p)
        socket.create_connection((host, port), timeout=3).close()
        return True
    except Exception:
        return False

def scan():
    print(f"[{datetime.now(timezone.utc).isoformat()}] === Начало сканирования ===", flush=True)

    if not redis_reachable():
        print("⚠ Redis недоступен, пропуск", flush=True)
        return {"status": "redis_unreachable", "players": [], "foreign_grids": []}

    owner = resolve_owner_id()
    redis = RedisEventClient()
    grids_info = get_all_grids()
    player_id = resolve_player_id(owner)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "scanned_grids": [],
        "players": [],
        "foreign_grids": [],
    }

    for grid_id, grid_name in grids_info:
        try:
            grid = Grid(redis, owner, grid_id, player_id, grid_name, auto_wake=True)
        except Exception as e:
            print(f"  ❌ {grid_name}: {e}", flush=True)
            continue

        detectors = [d for d in grid.devices.values() if d.device_type == "ore_detector"]
        if not detectors:
            result["scanned_grids"].append({"name": grid_name, "detectors": 0})
            continue

        for det in detectors:
            t = det.telemetry
            scan_cfg = t.get("scan", {})

            # Players
            if scan_cfg.get("includePlayers"):
                players = t.get("players", [])
                for p in players:
                    result["players"].append({"grid": grid_name, "detector": det.name, "player": p})
                if players:
                    print(f"  ⚡ [{grid_name}/{det.name}] ИГРОКИ: {players}", flush=True)

            # Grids
            if scan_cfg.get("includeGrids"):
                detected_grids = t.get("detectedgrids", [])
                for dg in detected_grids:
                    if isinstance(dg, dict):
                        g_id = str(dg.get("gridId", dg.get("id", "")))
                        g_name = dg.get("name", dg.get("displayName", g_id))
                    elif isinstance(dg, (list, tuple)):
                        g_id = str(dg[0])
                        g_name = dg[1] if len(dg) > 1 else g_id
                    else:
                        g_id = str(dg)
                        g_name = str(dg)

                    is_foreign = g_id not in OWN_GRID_IDS
                    entry = {"grid": grid_name, "detector": det.name,
                             "detected_grid_id": g_id, "detected_grid_name": g_name,
                             "foreign": is_foreign}
                    result["foreign_grids"].append(entry)

                    if is_foreign:
                        print(f"  🚨 [{grid_name}/{det.name}] ЧУЖОЙ ГРИД: {g_name}", flush=True)

            result["scanned_grids"].append({
                "name": grid_name, "detectors": len(detectors),
                "include_players": scan_cfg.get("includePlayers", False),
                "include_grids": scan_cfg.get("includeGrids", False),
            })

        import time; time.sleep(0.3)

    return result

if __name__ == "__main__":
    result = scan()

    with open(SCAN_LOG, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    has_players      = len(result["players"]) > 0
    has_foreign_grids = any(e["foreign"] for e in result["foreign_grids"])

    alert_state = {
        "timestamp": result["timestamp"],
        "has_players": has_players,
        "has_foreign_grids": has_foreign_grids,
        "player_count": len(result["players"]),
        "foreign_grid_count": sum(1 for e in result["foreign_grids"] if e["foreign"]),
        "players": result["players"],
        "foreign_grids": [e for e in result["foreign_grids"] if e["foreign"]],
    }
    with open(ALERT_FILE, "w") as f:
        json.dump(alert_state, f, ensure_ascii=False, indent=2)

    print(f"\n--- SCAN RESULT ---\n{json.dumps({
        'players_found': has_players,
        'foreign_grids_found': has_foreign_grids,
        'player_count': alert_state['player_count'],
        'foreign_grid_count': alert_state['foreign_grid_count'],
    }, ensure_ascii=False, indent=2)}\n--- END ---", flush=True)
```

## se_alert_watcher.py

```python
#!/usr/bin/env python3
"""Check for new alerts every 1m. Launch agent if threats found."""

import sys, os, json, subprocess
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ALERT_FILE     = os.path.join(SCRIPT_DIR, "logs", "active_alert.json")
PROCESSED_FILE = os.path.join(SCRIPT_DIR, "logs", "processed_alerts.json")
AGENT_SCRIPT   = os.path.join(SCRIPT_DIR, "se_alert_agent.py")
GUARD_FILE     = os.path.join(SCRIPT_DIR, "logs", "agent_running.lock")

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)

def alert_hash(alert: dict) -> str:
    import hashlib
    key = json.dumps({
        "players": [(p["grid"], p["detector"], str(p["player"]))
                    for p in alert.get("players", [])],
        "foreign_grids": [(e["grid"], e["detector"], e["detected_grid_id"])
                          for e in alert.get("foreign_grids", [])],
    }, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()

def main():
    if os.path.exists(GUARD_FILE):
        print(f"[{datetime.now(timezone.utc).isoformat()}] Агент уже работает, пропуск", flush=True)
        return

    alert = load_json(ALERT_FILE)
    if not alert:
        return
    if not (alert.get("has_players") or alert.get("has_foreign_grids")):
        return

    ahash = alert_hash(alert)
    processed = load_json(PROCESSED_FILE)
    if ahash in processed:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Алерт уже обработан, пропуск", flush=True)
        return

    print(f"[{datetime.now(timezone.utc).isoformat()}] ⚡ Угроза! Запуск агента...", flush=True)

    with open(GUARD_FILE, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())

    try:
        result = subprocess.run(
            [sys.executable, AGENT_SCRIPT],
            capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR,
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-10:]:
                print(line, flush=True)
        if result.returncode != 0 and result.stderr:
            print(f"STDERR: {result.stderr[:500]}", flush=True)
    except subprocess.TimeoutExpired:
        print("⚠ Агент превысил таймаут (120с)", flush=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)
    finally:
        if os.path.exists(GUARD_FILE):
            os.remove(GUARD_FILE)

if __name__ == "__main__":
    main()
```

## se_alert_agent.py

See the main skill file for the full agent script. Key points:
- Reads `active_alert.json` and `processed_alerts.json`
- Deduplicates by MD5 hash of player/grid info
- Writes one entry per incident to `journal.jsonl`
- Gathers our grid positions via RemoteControl telemetry
- Assesses risk (CRITICAL/HIGH/LOW)
- Marks alert as processed to avoid duplicate runs