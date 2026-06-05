"""
SharedMap Sync — загрузка локальных данных в Redis.

Читает последний скан (ore_latest.json) или JSONL-базу (ore_database.jsonl)
и записывает все найденные руды в SharedMap (Redis/SQLite).

Когда использовать:
  - Уже есть локальные данные от ore_scanner.py / ore_deposit_scanner.py
  - Нужно обновить SharedMap, чтобы другие агенты видели руды
  - После рестарта Redis — восстановить данные из файлов
  - После ручного копирования JSON-файлов с другого ПК

Usage:
    python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1                    # из ore_latest.json
    python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --source jsonl     # из ore_database.jsonl (все сканы)
    python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --source all       # latest + jsonl
    python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --dry-run          # без сохранения
    python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --storage sqlite   # SQLite вместо Redis
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from secontrol.controllers.shared_map_controller import SharedMapController

SCANS_DIR = Path.home() / "hermeswebui" / "se-data" / "scans"
ORE_DB_PATH = Path.home() / "hermeswebui" / "se-data" / "ore_database.jsonl"


def load_cells_from_latest() -> list[dict]:
    """Load ore cells from ore_latest.json."""
    path = SCANS_DIR / "ore_latest.json"
    if not path.exists():
        print(f"  File not found: {path}")
        return []

    with open(path) as f:
        data = json.load(f)

    cells = data.get("all_deposits", [])
    scan_time = data.get("scan_time", "unknown")
    grid = data.get("grid", {}).get("name", "unknown")
    print(f"  Source: {path.name}")
    print(f"  Scan time: {scan_time}, Grid: {grid}")
    return cells


def load_cells_from_jsonl() -> list[dict]:
    """Load ore cells from ore_database.jsonl (all scans merged, deduped)."""
    if not ORE_DB_PATH.exists():
        print(f"  File not found: {ORE_DB_PATH}")
        return []

    seen = set()
    cells = []
    scan_count = 0

    with open(ORE_DB_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            scan_count += 1
            for dep in data.get("all_deposits", []):
                pos = dep.get("position")
                if not pos:
                    continue
                key = (dep.get("ore_type"), round(pos[0], 0), round(pos[1], 0), round(pos[2], 0))
                if key not in seen:
                    seen.add(key)
                    cells.append({
                        "material": dep.get("ore_type"),
                        "position": pos,
                        "content": dep.get("content"),
                    })

    print(f"  Source: {ORE_DB_PATH.name}")
    print(f"  Scans read: {scan_count}")
    return cells


def main():
    parser = argparse.ArgumentParser(description="Sync local ore data to SharedMap (Redis/SQLite)")
    parser.add_argument("--grid", default="agent0", help="Grid name or ID (for owner_id)")
    parser.add_argument("--source", default="latest", choices=["latest", "jsonl", "all"],
                        help="Data source: latest=ore_latest.json, jsonl=ore_database.jsonl, all=both")
    parser.add_argument("--storage", default="redis", choices=["redis", "sqlite"], help="Storage backend")
    parser.add_argument("--chunk-size", type=float, default=100.0, help="SharedMap chunk size")
    parser.add_argument("--dry-run", action="store_true", help="Show data without saving")
    args = parser.parse_args()

    # Get owner_id from grid
    from secontrol.common import prepare_grid, close
    print(f"Connecting to grid: {args.grid}")
    grid = prepare_grid(args.grid)
    owner_id = grid.owner_id
    print(f"  Grid: {grid.name} (id={grid.grid_id})")
    print(f"  Owner ID: {owner_id}")
    close(grid)

    # Load cells
    print(f"\nLoading local data (source={args.source})...")
    cells = []

    if args.source in ("latest", "all"):
        latest_cells = load_cells_from_latest()
        cells.extend(latest_cells)
        print(f"  Latest cells: {len(latest_cells)}")

    if args.source in ("jsonl", "all"):
        jsonl_cells = load_cells_from_jsonl()
        if args.source == "all":
            existing_keys = set()
            for c in cells:
                pos = c.get("position")
                if pos:
                    key = (c.get("ore_type"), round(pos[0], 0), round(pos[1], 0), round(pos[2], 0))
                    existing_keys.add(key)
            new_cells = []
            for c in jsonl_cells:
                pos = c.get("position")
                if pos:
                    key = (c.get("material"), round(pos[0], 0), round(pos[1], 0), round(pos[2], 0))
                    if key not in existing_keys:
                        existing_keys.add(key)
                        new_cells.append(c)
            cells.extend(new_cells)
            print(f"  JSONL cells (new): {len(new_cells)}")
        else:
            cells = jsonl_cells
            print(f"  JSONL cells: {len(jsonl_cells)}")

    if not cells:
        print("\nNo ore data found locally. Run ore_scanner.py first.")
        return

    # Normalize: ensure 'material' key exists
    normalized = []
    for c in cells:
        normalized.append({
            "material": c.get("ore_type") or c.get("material") or "Unknown",
            "position": c.get("position"),
            "content": c.get("content"),
        })

    # Summary
    from collections import Counter
    types = Counter(c["material"] for c in normalized)
    print(f"\n  Total cells to sync: {len(normalized)}")
    print(f"  Ore types: {dict(types.most_common())}")

    if args.dry_run:
        print("\n[DRY-RUN] Data NOT saved.")
        return

    # Sync to SharedMap
    print(f"\nSyncing to SharedMap ({args.storage})...")
    shared_map = SharedMapController(
        owner_id=owner_id,
        chunk_size=args.chunk_size,
        storage_backend=args.storage,
    )
    shared_map.load()
    print(f"  Prefix: {shared_map.memory_prefix}")
    before = len(shared_map.get_known_ores())
    print(f"  Known ores before: {before}")

    shared_map.add_ore_cells(normalized, save=True)

    after = len(shared_map.get_known_ores())
    added = after - before
    print(f"  Known ores after: {after} (+{added})")
    print(f"\nDone! SharedMap synced.")


if __name__ == "__main__":
    main()
