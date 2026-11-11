"""
Ore Scanner for Space Engineers 2 — SE2GameAPI voxel scan + materials.

Same output contract as the SE1 ore_scanner.py:
  - scans voxels around a grid via the SE2GameAPI Redis protocol (se2:local:voxels:*),
  - keeps only ore materials (by the bridge material legend),
  - clusters deposits, saves JSON to ~/hermeswebui/se-data/scans/ore_latest.json
    and appends the JSONL ore database — so `--find` from the SE1 scanner works too.
  - prints GPS markers for copy-paste.

Usage:
    python examples/organized/radar/ore_scanner_se2.py --grid "Occupied Mine"
    python examples/organized/radar/ore_scanner_se2.py --grid "Renegade Hideout A" --radius 48
    python examples/organized/radar/ore_scanner_se2.py --find Iron
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent.parent / "src"))

from secontrol.se2 import Client  # noqa: E402

# reuse the SE1 scanner's clustering, GPS format, DB paths and --find logic
_spec = importlib.util.spec_from_file_location(
    "secontrol_ore_scanner", _HERE / "ore_scanner.py")
_scanner = importlib.util.module_from_spec(_spec)
sys.modules["secontrol_ore_scanner"] = _scanner
_spec.loader.exec_module(_scanner)

PREFIX = "se2:local:voxels"
ENQUEUE = """
if redis.call('LLEN', KEYS[1]) >= 64 then return 0 end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], 15)
return 1
"""
ORE_KEYWORDS = ("ore", "iron", "nickel", "gold", "silver", "chromium", "titanium",
                "uranium", "cobalt", "copper", "platinum", "ice", "silicon",
                "magnesium", "lead")


def is_ore_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return any(keyword in lowered for keyword in ORE_KEYWORDS)


def scan_ores(client: "Client", grid_name: str, radius: float, timeout: float = 240.0):
    """Run one voxel scan and return (ore_cells absolute, ship_position, grid_id)."""
    import redis as _redis
    db = _redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)

    autopilots = [d for d in client.devices(device_type="autopilot")]
    grid, = [d for d in autopilots if d._state["gridName"] == grid_name]
    props = grid.refresh()["properties"]
    ship_position = list(props["position"])
    grid_id = grid.grid_id

    state = json.loads(db.get("se2:local:state"))
    request_id = uuid.uuid4().hex
    request = {"requestId": request_id, "epoch": state["epoch"], "gridId": grid_id,
               "expiresAtMs": int((time.time() + 120) * 1000),
               "action": "scan", "radius": radius, "fresh": True}
    if not db.eval(ENQUEUE, 1, f"{PREFIX}:requests", json.dumps(request)):
        raise RuntimeError("voxel request queue is full")

    tiles: list[dict] = []
    status: dict = {}
    legend: dict[int, str] = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = db.get(f"{PREFIX}:scan:{request_id}")
        if raw:
            status = json.loads(raw)
            for entry in status.get("materialLegend") or []:
                idx, _, name = entry.partition("=")
                try:
                    legend[int(idx)] = name
                except ValueError:
                    continue
            count = status.get("publishedTiles", 0)
            for i in range(len(tiles), count):
                tile_raw = db.get(f"{PREFIX}:tile:{request_id}:{i}")
                if not tile_raw:
                    break
                tiles.append(json.loads(tile_raw))
            if status.get("state") in ("complete", "partial", "failed", "cancelled"):
                break
        time.sleep(0.25)

    ore_ids = {idx: name for idx, name in legend.items() if is_ore_name(name)}
    ore_cells: list[dict] = []
    total_voxels = 0
    for tile in tiles:
        import base64 as _b64
        content = _np_arr(_b64.b64decode(tile["content"]))
        nx, ny, nz = tile["size"]
        arr = content.reshape(nz, ny, nx)
        total_voxels += int((arr >= 1).sum())
        if not tile.get("material") or not ore_ids:
            continue
        material = _np_arr(_b64.b64decode(tile["material"])).reshape(nz, ny, nx)
        origin = tile["origin"]
        ax, ay, az = tile["axisX"], tile["axisY"], tile["axisZ"]
        solid = arr >= 1
        ore_mask = solid & np.isin(material, list(ore_ids))
        for x, y, z in zip(*np.nonzero(ore_mask)):
            name = ore_ids.get(int(material[x, y, z]), "Ore")
            point = (np.array(origin) + (x + 0.5) * np.array(ax)
                     + (y + 0.5) * np.array(ay) + (z + 0.5) * np.array(az)).tolist()
            ore_cells.append({"ore": name, "position": point})
    return ore_cells, total_voxels, len(tiles), status, ship_position, grid_id


def _np_arr(data: bytes):
    import numpy as np
    return np.frombuffer(data, dtype=np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser(description="SE2 ore scanner (SE2GameAPI voxels)")
    parser.add_argument("--grid", required=True, help="SE2 grid name")
    parser.add_argument("--radius", type=float, default=48.0, help="scan cube half-size (m)")
    parser.add_argument("--cluster_radius", type=float, default=50.0)
    parser.add_argument("--find", metavar="ORE", help="find nearest ORE deposits from latest scan")
    parser.add_argument("--find_n", type=int, default=3)
    args = parser.parse_args()

    if args.find:
        results = _scanner.find_nearest_ore(None, args.find, n=args.find_n)
        if not results:
            print(f"No '{args.find}' deposits found in latest scan.")
            return
        print(f"Nearest {args.find} deposits:")
        for i, r in enumerate(results):
            print(f"  {i+1}. {r['distance']}m — {r['ore_type']} ({r.get('deposits', '?')} deposits)")
            print(f"     {r['gps']}")
        return

    print(f"Connecting to SE2 grid: {args.grid}")
    with Client(timeout=9) as client:
        print(f"  scanning radius={args.radius} (voxel 1 m, materials on) ...")
        t0 = time.time()
        ore_cells, total_voxels, tile_count, status, ship_position, grid_id = \
            scan_ores(client, args.grid, args.radius)
        scan_time = time.time() - t0

    valuable = [c for c in ore_cells]
    type_counts = Counter(c["ore"] for c in valuable)
    print(f"\n  Scan time: {scan_time:.1f}s, tiles: {tile_count}, state: {status.get('state')}")
    print(f"  Solid voxels in volume: {total_voxels}")
    print(f"  Ore types: {dict(type_counts.most_common())}")

    clusters = _scanner.cluster_ore_deposits(valuable, cluster_radius=args.cluster_radius)

    print(f"\n  Clusters ({len(clusters)}):")
    gps_markers = []
    for i, cl in enumerate(clusters):
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(cl["center"], ship_position)))
        gps = _scanner.gps_string(f"{cl['ore_type']}_{i+1}", cl["center"])
        gps_markers.append(gps)
        print(f"    {i+1}. {cl['ore_type']}: {cl['deposit_count']} deposits, "
              f"spread={cl['spread_m']}m, {d:.0f}m from ship")
        print(f"       {gps}")

    ore_entries = []
    for cell in valuable:
        entry = {"ore_type": cell["ore"], "position": [round(p, 1) for p in cell["position"]]}
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(cell["position"], ship_position)))
        entry["distance_from_ship"] = round(d, 1)
        ore_entries.append(entry)

    scan_result = {
        "scan_time": datetime.now().isoformat(),
        "platform": "SE2GameAPI",
        "grid": {"name": args.grid, "id": grid_id},
        "ship_position": ship_position,
        "scan_config": {"radius": args.radius, "cluster_radius": args.cluster_radius},
        "scan_stats": {"ore_scan_time_s": round(scan_time, 1),
                       "total_deposits": len(ore_entries),
                       "tiles": tile_count,
                       "state": status.get("state")},
        "ore_summary": {k: {"count": v} for k, v in type_counts.items()},
        "ore_found": len(valuable) > 0,
        "clusters": clusters,
        "gps_markers": gps_markers,
        "all_deposits": ore_entries,
    }

    output_path = _scanner.SCANS_DIR / (
        f"ore_scan_se2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    _scanner.SCANS_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(scan_result, f, indent=2)
    latest = output_path.parent / "ore_latest.json"
    with open(latest, "w") as f:
        json.dump(scan_result, f, indent=2)
    _scanner.append_ore_scan_to_db(scan_result)
    print(f"\n  SAVED: {output_path}")
    print(f"  LATEST: {latest}")


if __name__ == "__main__":
    main()
