#!/usr/bin/env python3
"""End-to-end undock for a freshly-welded grid on a base.

Wrapper around `examples/organized/parking/manual_thrust_undock.py` with safe
defaults for a freshly-built scout/small grid:

  - Distance 30 m (configurable).
  - Override 18 % (configurable).
  - Pre-check: grid name resolved; connector not Connected; battery enabled;
    thrusters enabled.

If any pre-check fails, the script tries to recover automatically
(enable battery, enable thrusters) and aborts only when that's not possible.

Usage:
    python scripts/undock_new_grid.py skynet-scout6
    python scripts/undock_new_grid.py skynet-scout6 --distance 50 --override 25
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from secontrol.common import prepare_grid
from secontrol.devices.battery_device import BatteryDevice
from secontrol.devices.connector_device import ConnectorDevice


REPO_ROOT = Path(__file__).resolve().parents[4]
UNDOCK_SCRIPT = REPO_ROOT / "examples" / "organized" / "parking" / "manual_thrust_undock.py"


def _enable_all(grid, predicate, label: str) -> int:
    sent = 0
    for bid, b in grid.blocks.items():
        st = b.state or {}
        if not predicate(b):
            continue
        if st.get("enabled"):
            continue
        for did, dev in grid.devices.items():
            if str(bid) in str(did) or (hasattr(dev, "block_id") and str(dev.block_id) == str(bid)):
                if hasattr(dev, "enable"):
                    dev.enable()
                    sent += 1
                break
    print("Auto-enable {}: sent {}".format(label, sent))
    return sent


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grid", help="New grid name or id.")
    p.add_argument("--distance", type=float, default=30.0, help="Meters to back off (default: 30).")
    p.add_argument("--override", type=float, default=18.0, help="Thrust override %% (default: 18).")
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    print("Pre-undock: {} ({})  blocks={}".format(grid.name, grid.grid_id, len(grid.blocks)))

    conns = grid.find_devices_by_type(ConnectorDevice)
    if conns:
        c = conns[0]
        t = c.telemetry or {}
        if t.get("connectorIsConnected"):
            print("Connector still Connected — disconnecting first.")
            c.disconnect()
            c.set_state(locked=False)

    if not any(b.block_type and "Thrust" in b.block_type for bid, b in grid.blocks.items()):
        print("ERROR: no thrusters on grid — cannot undock by thrust.")
        return 2
    _enable_all(grid, lambda b: b.block_type and "Thrust" in b.block_type, "thrusters")
    _enable_all(grid, lambda b: b.block_type and "Battery" in b.block_type, "batteries")

    print()
    print("Launching manual_thrust_undock.py {} {} {} ...".format(
        grid.name, args.distance, args.override))
    rc = subprocess.run(
        [sys.executable, str(UNDOCK_SCRIPT), grid.name, str(args.distance), str(args.override)],
        check=False,
    )
    return rc.returncode


if __name__ == "__main__":
    sys.exit(main())
