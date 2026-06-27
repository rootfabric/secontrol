#!/usr/bin/env python3
"""Enable all disabled Merge blocks on a grid (optionally filtered by grid size).

Behavior:
  1. Resolve the source grid by name (substring match).
  2. Snapshot block count BEFORE enable.
  3. Send `enable()` to every disabled `MyObjectBuilder_MergeBlock` that
     matches the size filter (`--size small|large|all`, default `small`).
  4. Read-after-write (2.5 s) and verify `enabled=True` on every targeted
     merge block.

Usage:
    python scripts/enable_merge_blocks.py skynet-farpost0
    python scripts/enable_merge_blocks.py skynet-farpost0 --size all
    python scripts/enable_merge_blocks.py skynet-farpost0 --verify-delay 3

Notes:
  - In Space Engineers, enabling a Merge block on a face that already has a
    matching Merge block on the opposite subgrid mechanically locks the two
    subgrids into a single CubeGrid for physics.
  - Merge != power sharing: the mechanical lock alone does not create a power
    connection. Make sure there is also a connected ShipConnector or direct
    power conveyor between the subgrids if the goal is to feed power through.
"""
from __future__ import annotations

import argparse
import sys
import time

from secontrol.common import prepare_grid


_SIZE_SUBTYPE_HINTS = {
    "small": "SmallShip",
    "large": "LargeShip",
}


def _list_merge_blocks(grid) -> list:
    out = []
    for bid, b in grid.blocks.items():
        if b.block_type and b.block_type.startswith("MyObjectBuilder_MergeBlock"):
            out.append((bid, b))
    return out


def _match_size(subtype: str, size: str) -> bool:
    if size == "all":
        return True
    hint = _SIZE_SUBTYPE_HINTS[size]
    return hint in (subtype or "")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grid", help="Source grid name (substring match).")
    p.add_argument("--size", choices=("small", "large", "all"), default="small",
                   help="Filter merge blocks by grid size (default: small).")
    p.add_argument("--verify-delay", type=float, default=2.5,
                   help="Seconds to wait before read-after-write verify (default: 2.5).")
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    print(f"Source grid: {grid.name}  (id={grid.grid_id})")
    blocks_before = len(grid.blocks)
    print(f"Blocks before: {blocks_before}")

    targets = _list_merge_blocks(grid)
    size_matches = [(bid, b) for bid, b in targets if _match_size(b.subtype, args.size)]
    to_enable = [(bid, b) for bid, b in size_matches
                 if isinstance(b.state, dict) and not b.state.get("enabled")]
    print(f"Merge blocks: {len(targets)} total, "
          f"{len(size_matches)} match size={args.size}, "
          f"{len(to_enable)} need enable")

    if not to_enable:
        print("Nothing to enable.")
        return 0

    print()
    print("Enabling:")
    for bid, b in to_enable:
        sent = None
        for did, dev in grid.devices.items():
            if str(bid) in str(did) or (hasattr(dev, "block_id") and str(dev.block_id) == str(bid)):
                if hasattr(dev, "enable"):
                    sent = dev.enable()
                break
        print(f"  {bid}  {b.subtype}  enable() -> {sent}")

    time.sleep(args.verify_delay)

    grid2 = prepare_grid(args.grid)
    blocks_after = len(grid2.blocks)
    print()
    print(f"Blocks after:  {blocks_after}  (delta {blocks_after - blocks_before:+d})")
    print()
    print(f"Merge blocks after (size={args.size}):")
    ok = 0
    for bid, b in size_matches:
        st = b.state or {}
        en = st.get("enabled")
        marker = "OK" if en else "STILL OFF"
        if en:
            ok += 1
        print(f"  block_id={bid}  {b.subtype}  enabled={en}  [{marker}]")

    print()
    print(f"Summary: {ok}/{len(size_matches)} enabled.")
    return 0 if ok == len(size_matches) else 1


if __name__ == "__main__":
    sys.exit(main())
