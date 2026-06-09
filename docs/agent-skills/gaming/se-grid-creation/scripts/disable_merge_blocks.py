#!/usr/bin/env python3
"""Disable all enabled Merge blocks on a grid and report the new (detached) grid.

Behavior:
  1. Resolve the source grid by name (substring match).
  2. Snapshot block count BEFORE disable.
  3. Send `disable()` to every enabled `MyObjectBuilder_MergeBlock`.
  4. Read-after-write (2.5 s) and verify `enabled=False` on every merge block.
  5. Snapshot block count AFTER disable. If it dropped, the merged subgrid
     has detached and now lives as a separate grid — list all grids and
     print the one that wasn't there before, so the operator can capture
     its id and rename it via `Grid.rename()`.

Notes:
  - Disabling a Merge block only breaks the mechanical lock. If a Connector
    on the same side is still Connected, the new grid will stay snapped to
    the base. Call `connector.disconnect()` + `connector.set_state(locked=False)`
    afterwards (no skill helper yet — see SKILL.md §3.2).

Usage:
    python scripts/disable_merge_blocks.py skynet-farpost0
    python scripts/disable_merge_blocks.py skynet-farpost0 --verify-delay 3
"""
from __future__ import annotations

import argparse
import sys
import time

from secontrol.common import get_all_grids, prepare_grid


def _list_merge_blocks(grid) -> list:
    out = []
    for bid, b in grid.blocks.items():
        if b.block_type and b.block_type.startswith("MyObjectBuilder_MergeBlock"):
            out.append((bid, b))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grid", help="Source grid name (substring match).")
    p.add_argument("--verify-delay", type=float, default=2.5,
                   help="Seconds to wait before read-after-write verify (default: 2.5).")
    args = p.parse_args()

    before_ids = {gid for gid, _ in get_all_grids()}

    grid = prepare_grid(args.grid)
    print(f"Source grid: {grid.name}  (id={grid.grid_id})")
    blocks_before = len(grid.blocks)
    print(f"Blocks before: {blocks_before}")

    targets = _list_merge_blocks(grid)
    enabled_targets = [(bid, b) for bid, b in targets
                       if isinstance(b.state, dict) and b.state.get("enabled")]
    print(f"Merge blocks: {len(targets)} total, {len(enabled_targets)} enabled")

    if not enabled_targets:
        print("Nothing to disable.")
        return 0

    print()
    print("Disabling:")
    for bid, b in enabled_targets:
        for did, dev in grid.devices.items():
            if str(bid) in str(did) or (hasattr(dev, "block_id") and str(dev.block_id) == str(bid)):
                sent = dev.disable() if hasattr(dev, "disable") else None
                print(f"  {bid}  {b.subtype}  disable() -> {sent}")
                break
        else:
            print(f"  {bid}  {b.subtype}  no device wrapper, skipped")

    time.sleep(args.verify_delay)

    grid2 = prepare_grid(args.grid)
    blocks_after = len(grid2.blocks)
    print()
    print(f"Blocks after:  {blocks_after}  (delta {blocks_after - blocks_before:+d})")
    print()
    print("Merge blocks after:")
    for bid, b in _list_merge_blocks(grid2):
        st = b.state or {}
        en = st.get("enabled")
        marker = "OK" if not en else "STILL ON"
        print(f"  block_id={bid}  {b.subtype}  enabled={en}  [{marker}]")

    if blocks_after < blocks_before:
        after_ids = {gid for gid, _ in get_all_grids()}
        new_ids = sorted(after_ids - before_ids)
        print()
        print("=== NEW GRID DETECTED ===")
        if new_ids:
            for nid in new_ids:
                print(f"  >>> Capture this id for rename: {nid}")
        else:
            print("  block count dropped but get_all_grids() did not surface a new id.")
            print("  Re-run: python -c \"from secontrol.common import get_all_grids; list(get_all_grids())\"")
        print()
        print("Next steps:")
        print("  1. Disconnect any Connector on the new grid (still snaps to base):")
        print("       from secontrol.common import prepare_grid")
        print("       g = prepare_grid(<NEW_GRID_NAME_OR_ID>)")
        print("       for d in g.devices.values():")
        print("           if getattr(d, 'device_type', '') == 'connector' and d.is_enabled():")
        print("               d.disconnect(); d.set_state(locked=False)")
        print("  2. Rename:  g.rename('skynet-agent3')")
        return 0

    print("No new grid detached (block count unchanged).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
