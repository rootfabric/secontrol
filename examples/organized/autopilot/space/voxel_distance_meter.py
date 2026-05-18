#!/usr/bin/env python3
"""
Voxel Distance Meter — измеряет расстояние от корабля до ближайшего вокселя.

Диагностический скрипт: запускаешь, получаешь список ближайших вокселей
с расстояниями от корабля. Помогает понять, что видит сканер.

Usage:
    python3 voxel_distance_meter.py                       # skynet-baza0
    python3 voxel_distance_meter.py --grid skynet-baza1   # другой грид
    python3 voxel_distance_meter.py --cell 10 --radius 500  # мелкие воксели
    python3 voxel_distance_meter.py --ore-only            # только руда
    python3 voxel_distance_meter.py --loop                # непрерывный режим
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import List, Tuple

WORKSPACE = "/workspace"
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position


def get_world_position_safe(rc: RemoteControlDevice) -> Tuple[float, float, float] | None:
    try:
        rc.update()
        pos = get_world_position(rc)
        return pos if pos else None
    except Exception:
        return None


def format_coord(v: float) -> str:
    return f"{v:+.1f}"


def distance(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def main():
    parser = argparse.ArgumentParser(description="Measure distance from ship to nearest voxels")
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name")
    parser.add_argument("--radius", type=float, default=5000, help="Scan radius (m)")
    parser.add_argument("--cell", type=float, default=100, help="Voxel cell size (m)")
    parser.add_argument("--beam-x", type=int, default=100, help="Beam width (cells)")
    parser.add_argument("--beam-y", type=int, default=100, help="Beam height (cells)")
    parser.add_argument("--ore-only", action="store_true", help="Scan ore deposits only")
    parser.add_argument("--loop", action="store_true", help="Continuous scanning")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between scans in loop mode")
    parser.add_argument("--top", type=int, default=20, help="Show top N nearest voxels")
    args = parser.parse_args()

    print("=" * 60)
    print("  Voxel Distance Meter")
    print("=" * 60)
    print(f"Grid: {args.grid}")
    print(f"Scan: radius={args.radius}m, cell={args.cell}m, beam={args.beam_x}x{args.beam_y} cells")
    print(f"Mode: {'ore-only' if args.ore_only else 'all voxels'}")
    print()

    grid = prepare_grid(args.grid)
    radar: OreDetectorDevice = grid.get_first_device(OreDetectorDevice)
    rc: RemoteControlDevice = grid.get_first_device(RemoteControlDevice)

    if not radar:
        print("ERROR: OreDetector not found on grid")
        close(grid)
        return

    if not rc:
        print("ERROR: RemoteControl not found on grid")
        close(grid)
        return

    print(f"OreDetector ID: {radar.device_id}")
    print(f"RemoteControl ID: {rc.device_id}")
    print()

    ctrl = RadarController(
        radar,
        radius=args.radius,
        cell_size=args.cell,
        boundingBoxX=args.beam_x,
        boundingBoxY=args.beam_y,
        ore_only=args.ore_only,
    )

    scan_num = 0
    try:
        while True:
            scan_num += 1
            ship_pos = get_world_position_safe(rc)
            if not ship_pos:
                print(f"[Scan #{scan_num}] ERROR: cannot get ship position")
                time.sleep(args.interval)
                continue

            print(f"{'─' * 60}")
            print(f"[Scan #{scan_num}] Ship: ({format_coord(ship_pos[0])}, "
                  f"{format_coord(ship_pos[1])}, {format_coord(ship_pos[2])})")

            t0 = time.time()
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
            except Exception as e:
                print(f"  Scan error: {e}")
                time.sleep(args.interval)
                continue
            elapsed = time.time() - t0

            n = len(solid) if solid else 0
            n_ore = len(ore_cells) if ore_cells else 0
            print(f"  Scan time: {elapsed:.2f}s | Solid points: {n} | Ore cells: {n_ore}")

            if not solid:
                print("  No voxels detected — clear space")
                if not args.loop:
                    break
                time.sleep(args.interval)
                continue

            # Calculate distances from ship to each solid voxel
            voxel_dists: List[Tuple[float, Tuple[float, float, float]]] = []
            for pt in solid:
                d = distance(ship_pos, (pt[0], pt[1], pt[2]))
                voxel_dists.append((d, (pt[0], pt[1], pt[2])))

            # Sort by distance
            voxel_dists.sort(key=lambda x: x[0])

            # Stats
            all_dists = [d for d, _ in voxel_dists]
            print(f"  Distance range: {min(all_dists):.1f}m — {max(all_dists):.1f}m")
            print(f"  Average: {sum(all_dists)/len(all_dists):.1f}m")

            # Show top N nearest
            show_n = min(args.top, len(voxel_dists))
            print(f"\n  Top {show_n} nearest voxels:")
            print(f"  {'#':>3}  {'Distance':>10}  {'Coordinates'}")
            print(f"  {'─'*3}  {'─'*10}  {'─'*40}")
            for i, (d, pt) in enumerate(voxel_dists[:show_n]):
                marker = " ◀ NEAREST" if i == 0 else ""
                print(f"  {i+1:3d}  {d:10.1f}m  ({format_coord(pt[0])}, {format_coord(pt[1])}, {format_coord(pt[2])}){marker}")

            # Show ore cells if any
            if ore_cells and n_ore > 0:
                print(f"\n  Ore cells ({n_ore}):")
                ore_dists = []
                for cell in ore_cells:
                    cx = cell.get("centerX") or cell.get("center", {}).get("x", 0)
                    cy = cell.get("centerY") or cell.get("center", {}).get("y", 0)
                    cz = cell.get("centerZ") or cell.get("center", {}).get("z", 0)
                    d = distance(ship_pos, (cx, cy, cz))
                    ore_dists.append((d, cell))
                ore_dists.sort(key=lambda x: x[0])
                for i, (d, cell) in enumerate(ore_dists[:10]):
                    ore_type = cell.get("ore", cell.get("type", "?"))
                    print(f"    {i+1}. {ore_type}: {d:.1f}m")

            # Key info for scanner logic
            nearest = voxel_dists[0][0]
            print(f"\n  → Ближайший воксель: {nearest:.1f}m от корабля")
            if nearest < 1000:
                print(f"    ⚠️  В зоне OBSTACLE_RANGE (< 1000m)")
            else:
                print(f"    ✅ Дальше 1000m — не препятствие для сканера")

            if not args.loop:
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
    finally:
        close(grid)
        print("\nDone.")


if __name__ == "__main__":
    main()
