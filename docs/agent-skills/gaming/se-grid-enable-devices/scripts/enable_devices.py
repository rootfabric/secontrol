#!/usr/bin/env python3
"""Enable devices on a Space Engineers grid (read-after-write verified).

By default the script only touches "passive" device types (batteries,
connectors, thrusters, gyros, sensors, antennas, beacons, reactors,
lamps, LCD/text panels, ore detectors, AI behavior blocks). Production
blocks (refinery, assembler), ship tools (drill, welder, grinder,
nanobot), weapons, turrets, gas generators, projectors and wheels are
always skipped unless you explicitly opt in with --include-types.

The script is command-result-aware: it sends `enable()` only to devices
that currently report `enabled=false`, then re-reads telemetry after a
short delay and reports which ones are still OFF.

Usage:
    python enable_devices.py skynet-agent0
    python enable_devices.py skynet-agent0 --dry-run
    python enable_devices.py skynet-agent0 --include-types thruster,reactor
    python enable_devices.py skynet-agent0 --all
    python enable_devices.py skynet-agent0 --all --include-types weapon
    python enable_devices.py skynet-agent0 --exclude-types thruster
    python enable_devices.py skynet-agent0 --no-verify

Exit codes:
    0  - all targeted devices ended up ON
    1  - at least one device is still OFF after verify (or enable() failed)
    2  - misconfiguration (no grid, redis unreachable, etc.)
"""
from __future__ import annotations

import argparse
import sys
import time

from secontrol.common import prepare_grid

PASSIVE_TYPES: set[str] = {
    "battery",
    "connector",
    "thruster",
    "gyro",
    "sensor",
    "antenna",
    "beacon",
    "reactor",
    "lamp",
    "textpanel",
    "ore_detector",
    "parachute",
    "ai_behavior",
    "ai_recorder",
    "ai_flight_autopilot",
    "oxygentank",
    "gas_tank",
    "solarpanel",
    "hydrogenengine",
}

ACTIVE_TYPES: set[str] = {
    "ship_drill",
    "ship_welder",
    "ship_grinder",
    "ship_tool",
    "nanobot_build_and_repair",
    "nanobot_drill_system",
    "refinery",
    "assembler",
    "gas_generator",
    "conveyor_sorter",
    "weapon",
    "large_turret",
    "interior_turret",
    "artillery",
    "projector",
    "wheel",
    "ai_offensive",
    "ai_defensive",
    "ai_move_ground",
    "remote_control",
    "cockpit",
    "container",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Enable devices on a Space Engineers grid.",
    )
    p.add_argument(
        "grid",
        nargs="?",
        default=None,
        help="Grid name, id, or substring. Omit to auto-pick the only available grid.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Touch every device type (still respects --exclude-types).",
    )
    p.add_argument(
        "--include-types",
        action="append",
        default=[],
        help="Force-include device_type(s), comma-separated. Repeatable.",
    )
    p.add_argument(
        "--exclude-types",
        action="append",
        default=[],
        help="Force-exclude device_type(s), comma-separated. Repeatable.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be done, do not send commands.",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the read-after-write verification step.",
    )
    p.add_argument(
        "--verify-delay",
        type=float,
        default=2.0,
        help="Seconds to wait before re-reading state (default: 2.0).",
    )
    p.add_argument(
        "--command-pace",
        type=float,
        default=0.02,
        help="Seconds to sleep between enable() calls (default: 0.02).",
    )
    return p.parse_args()


def _split_csv(values: list[str]) -> set[str]:
    out: set[str] = set()
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.add(part)
    return out


def main() -> int:
    args = parse_args()
    includes = _split_csv(args.include_types)
    excludes = _split_csv(args.exclude_types)

    if args.all:
        allowed: set[str] | None = None
    else:
        allowed = set(PASSIVE_TYPES)
        allowed.update(includes)

    allowed_excludes = set(ACTIVE_TYPES) | excludes

    print(f"Connecting to grid '{args.grid or 'auto'}' ...")
    try:
        grid = prepare_grid(args.grid, auto_wake=True, wake_timeout=5.0)
    except (RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"redis error: {e}", file=sys.stderr)
        return 2

    time.sleep(1.0)

    rows: list[tuple[str, str, str, bool | None]] = []
    for did, dev in grid.devices.items():
        dtype = dev.device_type
        if allowed is not None and dtype not in allowed:
            continue
        if dtype in allowed_excludes:
            continue
        if not getattr(dev, "supports_enabled", True):
            continue
        try:
            enabled_now = dev.is_enabled()
        except Exception:
            enabled_now = None
        rows.append((str(did), dtype, getattr(dev, "name", None) or "", enabled_now))

    disabled = [r for r in rows if r[3] is False]
    already_on = [r for r in rows if r[3] is True]
    unknown = [r for r in rows if r[3] is None]

    print()
    grid_name = getattr(grid, "name", None) or args.grid or "(unknown)"
    print(f"Grid: {grid_name} (id={grid.grid_id})")
    print(
        f"Devices seen: {len(rows)} | already ON: {len(already_on)} "
        f"| currently OFF: {len(disabled)} | unknown: {len(unknown)}"
    )
    print()
    print(f"{'TYPE':<24} {'ID':<10} {'NAME':<32} NOW")
    print("-" * 80)
    for r in rows:
        flag = "ON " if r[3] is True else ("OFF" if r[3] is False else "?  ")
        print(f"{r[1]:<24} {r[0]:<10} {r[2][:32]:<32} {flag}")

    if not disabled:
        print("\nNothing to enable.")
        return 0

    if args.dry_run:
        print(f"\n[dry-run] Would enable {len(disabled)} devices.")
        return 0

    print(f"\nSending enable() to {len(disabled)} devices ...")
    sent_ok = 0
    sent_fail = 0
    for did, dtype, name, _ in disabled:
        dev = grid.devices[did]
        try:
            result = dev.enable()
        except Exception as e:
            sent_fail += 1
            print(f"  ! {dtype} {name} ({did}): {e}")
        else:
            if result:
                sent_ok += 1
            else:
                sent_fail += 1
        time.sleep(args.command_pace)

    print(f"  enable() returned: {sent_ok} ok, {sent_fail} failed")

    if args.no_verify:
        return 0 if sent_fail == 0 else 1

    print(f"\nVerifying (waiting {args.verify_delay:.1f}s for telemetry) ...")
    time.sleep(args.verify_delay)
    still_off: list[tuple[str, str, str, bool | None]] = []
    for did, dtype, name, _ in disabled:
        dev = grid.devices[did]
        try:
            now = dev.is_enabled()
        except Exception:
            now = None
        if now is not True:
            still_off.append((did, dtype, name, now))

    if still_off:
        print(f"  {len(still_off)} devices still OFF after verify:")
        for did, dtype, name, now in still_off:
            print(f"    {dtype} {name} ({did}) -> {now}")
        return 1

    print("  All previously-OFF devices are now ON.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
