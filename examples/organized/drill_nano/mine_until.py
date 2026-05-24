#!/usr/bin/env python3
"""
mine_until.py — добывает руду до достижения целевого количества.

Usage:
    python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --amount 5000
    python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --amount 5000 --check-interval 5
"""

from __future__ import annotations

import argparse
import os
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice


def get_ore_amount(grid, ore_subtype: str) -> float:
    """Суммарное количество руды (ore) на гриде."""
    total = 0.0
    for item in grid.get_all_grid_items():
        subtype = item.get("item_subtype", "")
        display = item.get("display_name", "")
        if ore_subtype.lower() in subtype.lower() or ore_subtype.lower() in display.lower():
            total += item.get("amount", 0)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine ore until target amount is reached")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--ore", required=True, help="Ore type (e.g. Nickel, Gold, Uranium)")
    parser.add_argument("--amount", type=float, required=True, help="Target amount")
    parser.add_argument("--check-interval", type=int, default=5, help="Check interval in seconds")
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    print(f"Grid: {grid.name} (id={grid.grid_id})")

    drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]
    print(f"Drill: {drill.name} (id={drill.device_id})")

    baseline = get_ore_amount(grid, args.ore)
    print(f"Baseline {args.ore}: {baseline:.1f}")
    print(f"Target: {args.amount:.1f}")
    print()

    print("Starting drill...")
    sent = drill.start_drilling_ore([args.ore], collect_resources=["Ore"], work_mode="Collect")
    time.sleep(1.0)
    drill.update()
    props = (drill.telemetry or {}).get("properties", {})
    print(f"Commands sent: {sent}")
    print(f"WorkMode: {drill.get_work_mode()}")
    print(f"ScriptControlled: {props.get('Drill.ScriptControlled')}")
    print(f"OnOff: {props.get('OnOff')}")
    try:
        print(f"Enabled ores: {drill.debug_get_enabled_known_ores()}")
    except Exception as exc:
        print(f"Enabled ores: <unavailable: {exc}>")

    print(f"Mining {args.ore} until {args.amount:.1f} units...")
    start = time.time()
    while True:
        time.sleep(args.check_interval)
        current = get_ore_amount(grid, args.ore)
        elapsed = time.time() - start
        rate = (current - baseline) / elapsed if elapsed > 0 else 0
        mined = current - baseline
        remaining = args.amount - mined
        eta = remaining / rate if rate > 0 else float("inf")
        print(f"  [{elapsed:.0f}s] {args.ore}: {current:.1f} / {args.amount:.1f} "
              f"(+{mined:.1f}, rate={rate:.1f}/s, eta={eta:.0f}s)")

        if mined >= args.amount:
            print(f"\nTarget reached! Delta={mined:.1f} >= {args.amount:.1f}")
            break

    print("Stopping drill...")
    drill.stop_drilling()
    drill.turn_off()

    final = get_ore_amount(grid, args.ore)
    print(f"Final {args.ore}: {final:.1f} (+{final - baseline:.1f} from baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
