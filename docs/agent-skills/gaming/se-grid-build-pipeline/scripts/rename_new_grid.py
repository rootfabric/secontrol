#!/usr/bin/env python3
"""Rename the new (just-detached) grid by id or by 'Static Grid ...' name.

Behavior:
  1. Resolve the grid by id, name substring, or "Static Grid" auto-detect
     (picks the only grid whose name matches ^Static Grid \\d+$ if --auto-new).
  2. Snapshot the current name + block count.
  3. Send rename().
  4. Read-after-write (default 2.5 s) and verify the new name is reflected
     in `get_all_grids()`.

Usage:
    python scripts/rename_new_grid.py 88851142445348052 skynet-scout6
    python scripts/rename_new_grid.py "Small Grid 8052" skynet-scout6
    python scripts/rename_new_grid.py --auto-new skynet-scout6
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from secontrol.common import prepare_grid, get_all_grids


_STATIC_GRID_RE = re.compile(r"^(Static Grid \d+|Small Grid \d+|Large Grid \d+)$")


def _pick_auto_new():
    """Return the id of the most recently seen 'Static/Small/Large Grid NNNN' grid."""
    candidates = []
    for gid, name in get_all_grids():
        if name and _STATIC_GRID_RE.match(name):
            candidates.append((gid, name))
    if not candidates:
        raise SystemExit("ERROR: --auto-new found no Static/Small/Large Grid")
    if len(candidates) > 1:
        names = ", ".join("{} ({})".format(n, g) for g, n in candidates)
        raise SystemExit(
            "ERROR: --auto-new ambiguous, multiple auto-named grids: {}".format(names)
        )
    return candidates[0][0]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("target", nargs="?", help="Grid id, name, or substring. Omit when --auto-new.")
    p.add_argument("new_name", help="Desired grid name (e.g. skynet-scout6).")
    p.add_argument("--auto-new", action="store_true",
                   help="Auto-pick the single auto-named (Static/Small/Large Grid NNNN) grid.")
    p.add_argument("--verify-delay", type=float, default=2.5)
    args = p.parse_args()

    if args.auto_new:
        target = str(_pick_auto_new())
        print("Auto-detected new grid: {}".format(target))
    else:
        if not args.target:
            raise SystemExit("ERROR: pass a target or --auto-new")
        target = args.target

    grid = prepare_grid(target)
    print("Before: id={}  name={!r}  blocks={}".format(
        grid.grid_id, grid.name, len(grid.blocks)))

    r = grid.rename(args.new_name)
    print("rename({!r}) -> {}".format(args.new_name, r))

    time.sleep(args.verify_delay)
    names = {n for _, n in get_all_grids()}
    if args.new_name in names:
        print("Verified: {!r} is now in get_all_grids()".format(args.new_name))
        return 0
    print("NOT verified after {:.1f}s — telemetry lag or rename failed.".format(args.verify_delay))
    return 1


if __name__ == "__main__":
    sys.exit(main())
