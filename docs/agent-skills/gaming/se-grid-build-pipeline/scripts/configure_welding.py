#!/usr/bin/env python3
"""Configure welding so the operator (or Nanobot ships) can weld across grids.

Behavior:
  1. Enable every disabled `MyObjectBuilder_ShipWelder` (and BuildAndRepair
     equivalent) on the grid.
  2. For each BuildAndRepair / ship welder, force:
       WeldOptionFunctionalOnly = False   (so merge blocks and structural
                                          blocks get welded too — required
                                          for inter-grid welding)
     `WeldOptionFunctionalOnly` defaults to True in SE, which silently skips
     non-functional blocks (including Merge Blocks). That is the #1 cause of
     "projection completes but the new grid is not actually merged".

  3. Report welder count, enabled count, and `WeldOptionFunctionalOnly` value
     before/after.

Usage:
    python scripts/configure_welding.py skynet-farpost0
"""
from __future__ import annotations

import argparse
import sys
import time

from secontrol.common import prepare_grid


WELDER_SUBTYPES = {
    "MyObjectBuilder_ShipWelder",
    "MyObjectBuilder_SurvivalKit",  # Survival kit has built-in welder
}


def _is_welder(block_type: str) -> bool:
    return any(block_type.startswith(t) for t in WELDER_SUBTYPES)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grid", help="Grid name or id (substring match).")
    p.add_argument("--verify-delay", type=float, default=2.0,
                   help="Seconds to wait before read-after-write verify.")
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    print("Grid: {} ({})  blocks={}".format(grid.name, grid.grid_id, len(grid.blocks)))

    welders = [(bid, b) for bid, b in grid.blocks.items() if _is_welder(b.block_type)]
    print("Welders found: {}".format(len(welders)))

    if not welders:
        print("Nothing to configure.")
        return 0

    by_id = {bid: dev for bid, dev in grid.devices.items()}
    if hasattr(next(iter(grid.devices.values())), "block_id"):
        by_id = {getattr(dev, "block_id"): dev for dev in grid.devices.values() if getattr(dev, "block_id", None)}

    print()
    sent_enable = 0
    sent_wfo = 0
    for bid, b in welders:
        st = b.state or {}
        en = st.get("enabled")
        wfo = st.get("WeldOptionFunctionalOnly")
        print("  block_id={}  enabled={}  WeldOptionFunctionalOnly={}".format(bid, en, wfo))

        dev = by_id.get(bid)
        if dev is None:
            for did, d in grid.devices.items():
                if str(bid) in str(did):
                    dev = d
                    break
        if dev is None:
            print("    (no device wrapper, skipped)")
            continue

        if not en and hasattr(dev, "enable"):
            r = dev.enable()
            print("    enable() -> {}".format(r))
            sent_enable += 1
        if hasattr(dev, "set_weld_functional_only"):
            r = dev.set_weld_functional_only(False)
            print("    set_weld_functional_only(False) -> {}".format(r))
            sent_wfo += 1
        elif hasattr(dev, "run_action"):
            r = dev.run_action("WeldOptionFunctionalOnly_OnOff")
            print("    run_action(WeldOptionFunctionalOnly_OnOff) -> {}".format(r))
            sent_wfo += 1

    print()
    print("Sent: enable={}, WeldOptionFunctionalOnly=false={}".format(sent_enable, sent_wfo))

    time.sleep(args.verify_delay)
    grid2 = prepare_grid(args.grid)
    bad = 0
    for bid, b in [(bid, b) for bid, b in grid2.blocks.items() if _is_welder(b.block_type)]:
        st = b.state or {}
        if not st.get("enabled") or st.get("WeldOptionFunctionalOnly") not in (False, 0, None):
            bad += 1
            print("  STILL OFF / WFO!=False: block_id={}  state={}".format(bid, st))
    print()
    print("Verify: {} welder(s) need attention".format(bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
