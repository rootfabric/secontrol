#!/usr/bin/env python3
"""Wait until the active projector on the grid reports zero remaining blocks.

Behavior:
  1. Resolve grid, pick the projector (same rules as setup_projection.py).
  2. Poll `remainingBlocks` (and `buildableBlocks`) every --poll-interval
     seconds, up to --timeout seconds.
  3. Exit 0 when remainingBlocks reaches 0. Exit 1 on timeout.

Usage:
    python scripts/wait_for_weld_complete.py skynet-farpost0
    python scripts/wait_for_weld_complete.py skynet-farpost0 \
        --projector-name "Projector 1" --timeout 600 --poll-interval 5
"""
from __future__ import annotations

import argparse
import sys
import time

from secontrol.common import prepare_grid
from secontrol.devices.projector_device import ProjectorDevice


def _pick_projector(grid, name):
    candidates = grid.find_devices_by_type(ProjectorDevice)
    if not candidates:
        raise SystemExit("ERROR: no Projector device on grid")
    if name:
        for dev in candidates:
            t = dev.telemetry or {}
            label = t.get("customName") or t.get("name") or ""
            if label.lower() == name.lower():
                return dev
        raise SystemExit("ERROR: projector {!r} not found".format(name))
    return candidates[0]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grid")
    p.add_argument("--projector-name", default=None)
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--poll-interval", type=float, default=5.0)
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    proj = _pick_projector(grid, args.projector_name)
    print("Watching projector {} on {} ({})".format(
        (proj.telemetry or {}).get("customName") or proj.device_id,
        grid.name, grid.grid_id,
    ))

    start = time.time()
    last_remaining = None
    while time.time() - start < args.timeout:
        time.sleep(args.poll_interval)
        grid = prepare_grid(args.grid)
        proj = _pick_projector(grid, args.projector_name)
        t = proj.telemetry or {}
        remaining = proj.remaining_blocks()
        buildable = proj.buildable_blocks()
        projected = t.get("projectedGridName")
        print("  t={:5.1f}s  remaining={}  buildable={}  projected={!r}".format(
            time.time() - start, remaining, buildable, projected))
        if remaining is not None and remaining <= 0 and last_remaining is not None and last_remaining > 0:
            print("DONE: weld complete.")
            return 0
        if remaining is not None:
            last_remaining = remaining

    print("TIMEOUT after {:.0f}s".format(args.timeout))
    return 1


if __name__ == "__main__":
    sys.exit(main())
