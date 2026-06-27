#!/usr/bin/env python3
"""Enable all disabled ShipConnectors on a grid (optionally filtered by size).

Behavior:
  1. Resolve the source grid by name (substring match).
  2. Snapshot block count BEFORE enable.
  3. Send `enable()` to every disabled `MyObjectBuilder_ShipConnector*`
     that matches the size filter (`--size small|large|all`, default `small`).
  4. Read-after-write (2.5 s) and verify `enabled=True` on every targeted
     connector.

Usage:
    python scripts/enable_connectors.py skynet-farpost0
    python scripts/enable_connectors.py skynet-farpost0 --size all
    python scripts/enable_connectors.py skynet-farpost0 --verify-delay 3

Notes:
  - `enable()` powers on the connector terminal. It does NOT lock / connect
    the connector to its facing pair. If you also want the connector to
    physically snap to the opposite connector, follow up with
    `connector.lock()` or `connector.set_state(enabled=True, locked=True)`.
  - A powered connector without a facing partner stays in `Connectable`
    state and consumes a small amount of power.
"""
from __future__ import annotations

import argparse
import sys
import time

from secontrol.common import prepare_grid


_SIZE_SUBTYPE_HINTS = {
    "small": "Small",
    "large": "Large",
}


def _list_connectors(grid) -> list:
    out = []
    for bid, b in grid.blocks.items():
        if b.block_type and b.block_type.startswith("MyObjectBuilder_ShipConnector"):
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
                   help="Filter connectors by grid size (default: small).")
    p.add_argument("--verify-delay", type=float, default=2.5,
                   help="Seconds to wait before read-after-write verify (default: 2.5).")
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    print("Source grid: {}  (id={})".format(grid.name, grid.grid_id))
    blocks_before = len(grid.blocks)
    print("Blocks before: {}".format(blocks_before))

    targets = _list_connectors(grid)
    size_matches = [(bid, b) for bid, b in targets if _match_size(b.subtype, args.size)]
    to_enable = [(bid, b) for bid, b in size_matches
                 if isinstance(b.state, dict) and not b.state.get("enabled")]
    print("Connectors: {} total, {} match size={}, {} need enable".format(
        len(targets), len(size_matches), args.size, len(to_enable)))

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
        print("  {}  {}  enable() -> {}".format(bid, b.subtype, sent))

    time.sleep(args.verify_delay)

    grid2 = prepare_grid(args.grid)
    blocks_after = len(grid2.blocks)
    print()
    print("Blocks after:  {}  (delta {:+d})".format(blocks_after, blocks_after - blocks_before))
    print()
    print("Connectors after (size={}):".format(args.size))
    ok = 0
    for bid, b in size_matches:
        st = b.state or {}
        en = st.get("enabled")
        marker = "OK" if en else "STILL OFF"
        if en:
            ok += 1
        print("  block_id={}  {}  enabled={}  [{}]".format(bid, b.subtype, en, marker))

    print()
    print("Summary: {}/{} enabled.".format(ok, len(size_matches)))
    return 0 if ok == len(size_matches) else 1


if __name__ == "__main__":
    sys.exit(main())
