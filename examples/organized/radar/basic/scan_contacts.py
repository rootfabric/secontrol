"""Scan for nearby grids and players using radar (no voxels).

Fast contact-only scan — skips voxel geometry entirely.
Reports all detected grids and players with positions and distances.

Usage:
    python scan_contacts.py                        # default grid (skynet-farpost0)
    python scan_contacts.py --grid skynet-baza1    # specific grid
    python scan_contacts.py --radius 1000          # custom scan radius
"""

import argparse
import math
from typing import Any, Dict, List, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position


def get_own_position(grid) -> Optional[List[float]]:
    """Get own world position from cockpit or remote control."""
    for dev_type in ("cockpit", "remote_control"):
        devices = grid.find_devices_by_type(dev_type)
        if devices:
            dev = devices[0]
            dev.update()
            pos = get_world_position(dev)
            if pos:
                return list(pos)
    return None


def contact_position(contact: Dict[str, Any]) -> Optional[List[float]]:
    """Extract position as [x, y, z] from contact dict."""
    pos = contact.get("position")
    if isinstance(pos, dict):
        try:
            return [float(pos["x"]), float(pos["y"]), float(pos["z"])]
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        try:
            return [float(pos[0]), float(pos[1]), float(pos[2])]
        except (TypeError, ValueError):
            return None
    return None


def contact_name(contact: Dict[str, Any]) -> str:
    """Get display name from contact."""
    for key in ("name", "displayName", "playerName", "gridName"):
        value = contact.get(key)
        if value not in (None, ""):
            return str(value)
    return f"id={contact.get('id', '?')}"


def distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan for nearby grids and players")
    parser.add_argument("--grid", default="skynet-farpost0", help="Grid name to scan from")
    parser.add_argument("--radius", type=float, default=500, help="Scan radius in meters")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)

    try:
        radar = grid.get_first_device(OreDetectorDevice)
        print(f"Radar: {radar.name} (id={radar.device_id})")
        print(f"Scanning from: {grid.name} (id={grid.grid_id})")
        print(f"Radius: {args.radius}m")
        print()

        own_position = get_own_position(grid)

        controller = RadarController(radar, radius=args.radius, cell_size=10, ore_only=False)
        contacts = controller.scan_contacts()

        if not contacts:
            print("No contacts found.")
            return

        grids = [c for c in contacts if isinstance(c, dict) and c.get("type") == "grid"]
        players = [c for c in contacts if isinstance(c, dict) and c.get("type") == "player"]

        print(f"\n{'='*60}")
        print(f"  RESULTS: {len(grids)} grid(s), {len(players)} player(s)")
        print(f"{'='*60}")

        if grids:
            print(f"\n  GRIDS:")
            print(f"  {'Name':<30} {'Distance':>10}  {'Position'}")
            print(f"  {'-'*30} {'-'*10}  {'-'*40}")
            for g in grids:
                pos = contact_position(g)
                name = contact_name(g)
                if own_position and pos:
                    dist = distance(own_position, pos)
                    print(f"  {name:<30} {dist:>9.0f}m  ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
                elif pos:
                    print(f"  {name:<30} {'?':>10}  ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
                else:
                    print(f"  {name:<30} {'?':>10}  (no position)")

        if players:
            print(f"\n  PLAYERS:")
            print(f"  {'Name':<30} {'Distance':>10}  {'Position'}")
            print(f"  {'-'*30} {'-'*10}  {'-'*40}")
            for p in players:
                pos = contact_position(p)
                name = contact_name(p)
                if own_position and pos:
                    dist = distance(own_position, pos)
                    print(f"  {name:<30} {dist:>9.0f}m  ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
                elif pos:
                    print(f"  {name:<30} {'?':>10}  ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
                else:
                    print(f"  {name:<30} {'?':>10}  (no position)")

        print(f"\n{'='*60}")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
