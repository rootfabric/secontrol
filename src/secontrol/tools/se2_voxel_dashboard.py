"""SE2 voxel dashboard: 3D visualization of SE2GameAPI voxel scans via RadarVisualizer.

Reads a live scan from the SE2 Game API Redis protocol (se2:local:voxels:*),
decodes tiles into world-space points and renders them with the same PyVista
visualizer used by the SE1 radar tools, together with surrounding grids
(contacts) and the scanned ship position.

Usage:
    python -m secontrol.tools.se2_voxel_dashboard --list
    python -m secontrol.tools.se2_voxel_dashboard --grid-name "Blue Miner" --radius 32
    python -m secontrol.tools.se2_voxel_dashboard --grid-name "Blue Miner" --watch
    python -m secontrol.tools.se2_voxel_dashboard --replay C:/SE2GameAPI/artifacts/voxel-scan.json

Requires: pip install pyvista redis  (secontrol on PYTHONPATH or installed).
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from ..se2 import Client
from .radar_visualizer import RadarVisualizer

PREFIX = "se2:local:voxels"
ENQUEUE = """
if redis.call('LLEN', KEYS[1]) >= 64 then return 0 end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], 15)
return 1
"""


def grid_catalog(client: Client) -> dict[str, str]:
    """gridId -> gridName from autopilot devices."""
    out = {}
    for device in client.devices(device_type="autopilot"):
        out[device.grid_id] = device._state["gridName"]
    return out


def request_scan(client: Client, grid_id: str, radius: float, fresh: bool) -> str | None:
    db = client.redis
    epoch = client.snapshot(fresh=True)["epoch"]
    request = {"requestId": uuid.uuid4().hex, "epoch": epoch, "gridId": grid_id,
               "expiresAtMs": int((time.time() + 120) * 1000),
               "action": "scan", "radius": radius, "fresh": fresh}
    if not db.eval(ENQUEUE, 1, f"{PREFIX}:requests", json.dumps(request)):
        raise RuntimeError("voxel request queue is full")
    return request["requestId"]


def collect_scan(client: Client, request_id: str, timeout: float = 240.0) -> dict[str, Any] | None:
    """Poll the scan status/tiles until complete; returns the viewer document."""
    db = client.redis
    deadline = time.monotonic() + timeout
    tiles: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        raw = db.get(f"{PREFIX}:scan:{request_id}")
        if raw:
            status = json.loads(raw)
            count = status.get("publishedTiles", 0)
            for i in range(len(tiles), count):
                tile_raw = db.get(f"{PREFIX}:tile:{request_id}:{i}")
                if not tile_raw:
                    break
                tiles.append(json.loads(tile_raw))
            state = status.get("state", "").lower()
            if state in ("complete", "partial", "failed", "cancelled"):
                return {"status": status, "tiles": tiles}
        time.sleep(0.25)
    return None


ORE_KEYWORDS = ("ore", "iron", "nickel", "gold", "silver", "chromium", "titanium",
                "uranium", "cobalt", "copper", "platinum", "ice", "silicon", "magnesium")


def is_ore_name(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in ORE_KEYWORDS)


def decode_tiles(document: dict[str, Any], threshold: int = 1):
    """Return (points, voxel size, ore cells [{position, name}]) centered on the grid."""
    status = document["status"]
    grid_pos = np.array(status["grid"]["position"], dtype=np.float64)
    legend = {}
    for entry in status.get("materialLegend") or []:
        index, _, name = entry.partition("=")
        try:
            legend[int(index)] = name
        except ValueError:
            continue
    ore_ids = {idx: name for idx, name in legend.items() if is_ore_name(name)}
    chunks: list[np.ndarray] = []
    ore_cells: list[dict[str, Any]] = []
    voxel_size = 1.0
    for tile in document.get("tiles", []):
        content = np.frombuffer(base64.b64decode(tile["content"]), dtype=np.uint8)
        nx, ny, nz = tile["size"]
        arr = content.reshape(nz, ny, nx)
        material = None
        if tile.get("material") and ore_ids:
            material = np.frombuffer(base64.b64decode(tile["material"]), dtype=np.uint8).reshape(nz, ny, nx)
        solid = arr >= threshold
        if material is not None:
            ore_mask = solid & np.isin(material, list(ore_ids))
        else:
            ore_mask = np.zeros_like(solid)
        xs, ys, zs = np.nonzero(solid)
        if xs.size == 0:
            continue
        origin = np.array(tile["origin"], dtype=np.float64)
        ax = np.array(tile["axisX"], dtype=np.float64)
        ay = np.array(tile["axisY"], dtype=np.float64)
        az = np.array(tile["axisZ"], dtype=np.float64)
        voxel_size = float(np.linalg.norm(ax))
        # local fractional voxel coords: cell centres
        fx, fy, fz = xs + 0.5, ys + 0.5, zs + 0.5
        world = (origin[None, :]
                 + fx[:, None] * ax[None, :]
                 + fy[:, None] * ay[None, :]
                 + fz[:, None] * az[None, :])
        chunks.append(world - grid_pos)
        if ore_mask.any():
            ox, oy, oz = np.nonzero(ore_mask)
            ore_world = (origin[None, :]
                         + (ox + 0.5)[:, None] * ax[None, :]
                         + (oy + 0.5)[:, None] * ay[None, :]
                         + (oz + 0.5)[:, None] * az[None, :]) - grid_pos
            for row, m in zip(ore_world, material[ore_mask]):
                ore_cells.append({"position": row.tolist(), "ore": ore_ids.get(int(m), "Ore")})
    if not chunks:
        return np.zeros((0, 3)), voxel_size, []
    return np.vstack(chunks), voxel_size, ore_cells


def _radar_module():
    """Load SE1 radar visualization helpers (envelope, ore grids, colors)."""
    import importlib.util
    path = Path(__file__).resolve().parents[3] / "examples" / "organized" / "radar" / "basic" / \
        "radar_voxel_visualization.py"
    spec = importlib.util.spec_from_file_location("secontrol_radar_voxel_viz", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def visualize(document: dict[str, Any], client: Client | None) -> None:
    points, voxel, ore_cells = decode_tiles(document)
    if points.shape[0] == 0:
        print("no non-zero voxels in scan; nothing to visualize")
        return
    scan_grid_id = document["status"]["gridId"]
    # surrounding grids as contacts (positions relative to the scanned grid)
    scan = None
    contacts = []
    if client is not None:
        snapshot = client.snapshot(fresh=True)
        scan = next((d for d in snapshot["devices"]
                     if d.get("type") == "autopilot" and d.get("gridId") == scan_grid_id), None)
        scan_pos = np.array(scan["properties"]["position"], dtype=np.float64) if scan else None
        for d in snapshot["devices"]:
            if d.get("type") == "autopilot" and d.get("gridId") != scan_grid_id:
                pos = d["properties"]["position"]
                rel = [pos[i] - scan_pos[i] for i in range(3)] if scan_pos is not None else pos
                contacts.append({"type": "grid", "name": d["gridName"], "position": rel})

    # uniform occupancy grid for RadarVisualizer: quantize world points to voxel cells
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    cell = max(voxel, 1e-6)
    size = np.maximum(np.ceil((hi - lo) / cell).astype(int) + 1, 1)
    if float(np.prod(size)) > 24_000_000:
        cell = float(np.ceil(max(hi - lo) / 256))
        size = np.maximum(np.ceil((hi - lo) / cell).astype(int) + 1, 1)
    metadata = {"size": [int(size[0]), int(size[1]), int(size[2])],
                "cellSize": cell, "origin": lo.tolist()}
    solid = points.tolist()
    name = document["status"]["grid"].get("gridName", scan_grid_id)
    ore_names = {c.get("ore") for c in ore_cells}
    print(f"{len(solid)} voxels, cell {cell:.2f} m, grid {size.tolist()}, "
          f"contacts {len(contacts)}, ore voxels {len(ore_cells)} ({', '.join(sorted(n for n in ore_names if n))})")

    # Clear rendering: dark background, translucent rock surface, colored ore cubes, labels.
    import pyvista as pv
    module = _radar_module()
    plotter = pv.Plotter()
    plotter.set_background("black", top="darkslategray")

    occ = module.build_occ_grid(solid, metadata)
    if occ is not None and np.any(occ):
        pts, faces, env_cells, total_cells, face_count = \
            module.build_outer_envelope_mesh_data(occ, metadata)
        if pts.size and faces.size:
            mesh = pv.PolyData(pts, faces)
            plotter.add_mesh(mesh, style="surface", color="lightgray", opacity=0.45,
                             label=f"Rock surface ({env_cells}/{total_cells} cells)")
    ore_grids, label_points = module.build_ore_grids(ore_cells, metadata)
    summary = []
    for ore_name, ogrid in sorted(ore_grids.items()):
        count = int(np.sum(ogrid))
        if count <= 0:
            continue
        color = module.ore_color(ore_name)
        module.add_occ_mesh(plotter, ogrid, metadata, f"ore_{ore_name}",
                            f"{ore_name} ({count})", color, opacity=0.95, show_edges=True)
        summary.append(f"{ore_name}: {count}")
        pts_named = label_points.get(ore_name, [])
        if pts_named:
            centroid = np.mean(np.asarray(pts_named, dtype=float), axis=0)
            plotter.add_point_labels(np.asarray([centroid]), [f"{ore_name} ({count})"],
                                     point_size=0, font_size=14, text_color=color,
                                     shape_opacity=0.4, always_visible=True)
    grid_points, grid_labels = [], []
    for contact in contacts:
        pos = contact.get("position")
        if pos:
            grid_points.append(pos)
            dist = float(np.linalg.norm(np.asarray(pos, dtype=float)))
            grid_labels.append(f"{contact.get('name', 'Grid')} ({dist:.0f} m)")
    if grid_points:
        plotter.add_mesh(pv.PolyData(grid_points), color="blue", point_size=18,
                         render_points_as_spheres=True, label="Grids")
        plotter.add_point_labels(np.asarray(grid_points, dtype=float), grid_labels,
                                 point_size=0, font_size=11, text_color="lightblue",
                                 shape_opacity=0.4, always_visible=True)
    plotter.add_mesh(pv.PolyData(np.asarray([[0.0, 0.0, 0.0]])), color="lime",
                     point_size=16, render_points_as_spheres=True, label=name)
    hud = f"SE2 voxels: {len(solid)}  cell {cell:.1f} m  radius {document['status'].get('radius')}"
    if summary:
        hud += "\nOres: " + ", ".join(summary)
    else:
        hud += "\nOres: none in scan"
    plotter.add_text(hud, position="upper_left", font_size=10, color="white")
    plotter.add_text(name, position="upper_right", font_size=12, color="white")
    plotter.show(title=f"SE2 Voxel Dashboard: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="list grids and exit")
    parser.add_argument("--grid-id")
    parser.add_argument("--grid-name")
    parser.add_argument("--radius", type=float, default=32.0)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--watch", action="store_true", help="repeat scans after each finishes")
    parser.add_argument("--replay", help="visualize a recorded scan JSON instead of scanning")
    parser.add_argument("--url", default="redis://127.0.0.1:6379/0")
    args = parser.parse_args()

    if args.replay:
        with open(args.replay, encoding="utf-8") as fh:
            visualize(json.load(fh), None)
        return

    client = Client(url=args.url, timeout=9)
    catalog = grid_catalog(client)
    if args.list:
        for grid_id, name in catalog.items():
            print(f"{grid_id}\t{name}")
        return
    grid_id = args.grid_id or (next((k for k, v in catalog.items() if v == args.grid_name), None)
                               if args.grid_name else None)
    if not grid_id:
        sys.exit("grid not found; use --list (or pass --grid-id)")

    try:
        while True:
            print(f"scanning {catalog.get(grid_id, grid_id)} radius={args.radius} ...")
            request_id = request_scan(client, grid_id, args.radius, args.fresh)
            document = collect_scan(client, request_id)
            if document is None:
                print("scan timed out")
            else:
                state = document["status"].get("state")
                print(f"scan {state}: {document['status'].get('publishedTiles', 0)} tiles")
                visualize(document, client)
            if not args.watch:
                break
    finally:
        client.close()


if __name__ == "__main__":
    main()
