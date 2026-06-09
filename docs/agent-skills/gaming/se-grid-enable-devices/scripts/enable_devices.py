#!/usr/bin/env python3
"""Enable devices on a Space Engineers grid with read-after-write verification.

The script is intentionally conservative by default: it enables safe/passive
blocks only. Use --all if you really want to touch every block type that exposes
an enable/set_enabled command.

Important details:
- ON is sent even to devices that already report enabled=true, because telemetry
  can be stale for some blocks.
- Verification re-reads telemetry several times.
- Device selection does not trust supports_enabled=False blindly. Some devices
  can still be enabled through set_enabled()/enable(), and reactors are one of
  the important cases.

Usage:
    python enable_devices.py skynet-agent0
    python enable_devices.py skynet-agent0 --dry-run
    python enable_devices.py skynet-agent0 --only-off
    python enable_devices.py skynet-agent0 --include-types reactor,battery
    python enable_devices.py skynet-agent0 --all
    python enable_devices.py skynet-agent0 --all --exclude-types weapon,large_turret,interior_turret,artillery
    python enable_devices.py skynet-agent0 --debug-skipped
    python enable_devices.py skynet-agent0 --no-verify

Exit codes:
    0  - all targeted devices ended up ON
    1  - at least one targeted device is still not confirmed ON
    2  - misconfiguration, grid not found, Redis unavailable, etc.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

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
    "oxygen_tank",
    "gas_tank",
    "solarpanel",
    "solar_panel",
    "hydrogenengine",
    "hydrogen_engine",
}

SKIPPED_BY_DEFAULT_TYPES: set[str] = {
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

ENABLE_PRIORITY: dict[str, int] = {
    "reactor": 0,
    "battery": 1,
    "hydrogenengine": 2,
    "hydrogen_engine": 2,
    "solarpanel": 3,
    "solar_panel": 3,
    "gas_tank": 4,
    "oxygentank": 4,
    "oxygen_tank": 4,
    "connector": 5,
    "antenna": 6,
    "beacon": 6,
    "gyro": 7,
    "thruster": 8,
}

TRUTHY = {"1", "true", "yes", "on", "enabled"}
FALSY = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class DeviceRow:
    key: Any
    device_id: str
    device_type: str
    name: str
    enabled: bool | None
    device: Any


@dataclass(frozen=True)
class SkippedRow:
    device_id: str
    device_type: str
    name: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enable devices on a Space Engineers grid.")
    parser.add_argument(
        "grid",
        nargs="?",
        default=None,
        help="Grid name, id, or substring. Omit to auto-pick the only available grid.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Touch every device type that has set_enabled()/enable(). Respects only --exclude-types.",
    )
    parser.add_argument(
        "--include-types",
        action="append",
        default=[],
        help="Force-include device_type(s), comma-separated. Repeatable.",
    )
    parser.add_argument(
        "--exclude-types",
        action="append",
        default=[],
        help="Force-exclude device_type(s), comma-separated. Repeatable.",
    )
    parser.add_argument(
        "--only-off",
        action="store_true",
        help="Send ON only to devices that currently report enabled=false.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be done, do not send commands.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the read-after-write verification step.",
    )
    parser.add_argument(
        "--verify-delay",
        type=float,
        default=2.0,
        help="Seconds to wait before the first telemetry refresh (default: 2.0).",
    )
    parser.add_argument(
        "--verify-attempts",
        type=int,
        default=4,
        help="How many telemetry refresh attempts to make during verification (default: 4).",
    )
    parser.add_argument(
        "--verify-interval",
        type=float,
        default=0.75,
        help="Seconds between verification attempts after the first one (default: 0.75).",
    )
    parser.add_argument(
        "--command-pace",
        type=float,
        default=0.05,
        help="Seconds to sleep between enable commands (default: 0.05).",
    )
    parser.add_argument(
        "--debug-skipped",
        action="store_true",
        help="Print devices skipped by filters or missing enable command.",
    )
    return parser.parse_args()


def _split_csv(values: list[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        for part in str(value).split(","):
            item = _normalize_type(part)
            if item:
                result.add(item)
    return result


def _normalize_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "oxygen_tank": "oxygentank",
        "solar_panel": "solarpanel",
        "hydrogen_engine": "hydrogenengine",
        "text_panel": "textpanel",
        "ore_detector_block": "ore_detector",
    }
    return aliases.get(text, text)


def _telemetry(device: Any) -> dict[str, Any]:
    data = getattr(device, "telemetry", None)
    return data if isinstance(data, dict) else {}


def _device_type(device: Any) -> str:
    dtype = _normalize_type(getattr(device, "device_type", ""))
    if dtype:
        return dtype

    data = _telemetry(device)
    raw_type = str(data.get("type") or "").lower()
    raw_subtype = str(data.get("subtype") or "").lower()
    class_name = device.__class__.__name__.lower()

    if "reactor" in raw_type or "reactor" in raw_subtype or "reactor" in class_name:
        return "reactor"
    if "battery" in raw_type or "battery" in raw_subtype or "battery" in class_name:
        return "battery"
    if "hydrogentank" in raw_subtype or "oxygentank" in raw_type or "gastank" in class_name:
        return "gas_tank"

    return dtype


def _device_id(key: Any, device: Any) -> str:
    value = getattr(device, "device_id", None)
    if value is None:
        value = getattr(device, "id", None)
    if value is None:
        value = _telemetry(device).get("id")
    if value is None:
        value = key
    return str(value)


def _device_name(device: Any) -> str:
    name = getattr(device, "name", None)
    if name is None:
        name = _telemetry(device).get("name")
    return str(name or "")


def _parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    return None


def _read_enabled(device: Any) -> bool | None:
    # Do not trust supports_enabled=False here. In older secontrol builds some
    # real blocks, including reactors, may still expose set_enabled()/enable().
    is_enabled = getattr(device, "is_enabled", None)
    if callable(is_enabled):
        try:
            value = _parse_bool(is_enabled())
            if value is not None:
                return value
        except Exception:
            pass

    data = _telemetry(device)
    for key in ("terminalOnOff", "enabled", "functionalEnabled"):
        value = _parse_bool(data.get(key))
        if value is not None:
            return value

    return None


def _read_working(device: Any) -> bool | None:
    data = _telemetry(device)
    for key in ("isWorking", "working"):
        value = _parse_bool(data.get(key))
        if value is not None:
            return value
    functional_status = getattr(device, "functional_status", None)
    if callable(functional_status):
        try:
            status = functional_status()
            if isinstance(status, dict):
                return _parse_bool(status.get("isWorking"))
        except Exception:
            return None
    return None


def _has_enable_command(device: Any) -> bool:
    return callable(getattr(device, "set_enabled", None)) or callable(getattr(device, "enable", None))


def _send_enable(device: Any) -> int:
    set_enabled = getattr(device, "set_enabled", None)
    if callable(set_enabled):
        return int(set_enabled(True) or 0)

    enable = getattr(device, "enable", None)
    if callable(enable):
        return int(enable() or 0)

    raise NotImplementedError(f"{device.__class__.__name__} has no enable/set_enabled method")


def _refresh_grid_devices(grid: Any) -> None:
    refresh_devices = getattr(grid, "refresh_devices", None)
    if callable(refresh_devices):
        try:
            refresh_devices()
            return
        except Exception as exc:
            print(f"  warning: grid.refresh_devices() failed: {exc}", file=sys.stderr)

    refresh = getattr(grid, "refresh", None)
    if callable(refresh):
        try:
            refresh()
            return
        except Exception as exc:
            print(f"  warning: grid.refresh() failed: {exc}", file=sys.stderr)

    wake = getattr(grid, "wake", None)
    if callable(wake):
        try:
            wake(timeout=1.0)
        except Exception as exc:
            print(f"  warning: grid.wake() failed: {exc}", file=sys.stderr)


def _fresh_device(grid: Any, row: DeviceRow) -> Any:
    devices = getattr(grid, "devices", {})
    try:
        by_key = devices.get(row.key)
        if by_key is not None:
            return by_key
    except Exception:
        pass

    try:
        by_id = devices.get(row.device_id)
        if by_id is not None:
            return by_id
    except Exception:
        pass

    get_by_id = getattr(grid, "get_device_by_id", None)
    if callable(get_by_id):
        try:
            by_id = get_by_id(int(row.device_id))
            if by_id is not None:
                return by_id
        except Exception:
            pass

    return row.device


def _selection_filter(
    device: Any,
    dtype: str,
    allowed: set[str] | None,
    skipped: set[str],
) -> str | None:
    if not dtype:
        return "empty device_type"
    if allowed is not None and dtype not in allowed:
        return "not in selected types"
    if dtype in skipped:
        return "skipped by default/exclude-types"
    if not _has_enable_command(device):
        return "no set_enabled()/enable() command"
    return None


def _sort_key(row: DeviceRow) -> tuple[int, str, str]:
    return (ENABLE_PRIORITY.get(row.device_type, 50), row.device_type, row.name.lower())


def _select_rows(
    grid: Any,
    allowed: set[str] | None,
    skipped: set[str],
) -> tuple[list[DeviceRow], list[SkippedRow]]:
    rows: list[DeviceRow] = []
    skipped_rows: list[SkippedRow] = []

    for key, device in getattr(grid, "devices", {}).items():
        dtype = _device_type(device)
        reason = _selection_filter(device, dtype, allowed, skipped)
        device_id = _device_id(key, device)
        name = _device_name(device)

        if reason is not None:
            skipped_rows.append(SkippedRow(device_id, dtype or "?", name, reason))
            continue

        rows.append(
            DeviceRow(
                key=key,
                device_id=device_id,
                device_type=dtype,
                name=name,
                enabled=_read_enabled(device),
                device=device,
            )
        )

    rows.sort(key=_sort_key)
    return rows, skipped_rows


def _print_rows(rows: list[DeviceRow], targets: list[DeviceRow]) -> None:
    print(f"{'TYPE':<24} {'ID':<20} {'NAME':<32} NOW  WORK ACTION")
    print("-" * 100)
    target_keys = {(row.key, row.device_id) for row in targets}
    for row in rows:
        enabled = "ON " if row.enabled is True else ("OFF" if row.enabled is False else "?  ")
        working_value = _read_working(row.device)
        working = "YES " if working_value is True else ("NO  " if working_value is False else "?   ")
        action = "enable" if (row.key, row.device_id) in target_keys else "skip"
        print(
            f"{row.device_type:<24} {row.device_id:<20} "
            f"{row.name[:32]:<32} {enabled}  {working} {action}"
        )


def _print_skipped(skipped_rows: list[SkippedRow]) -> None:
    if not skipped_rows:
        print("\nSkipped devices: 0")
        return

    counts = Counter(row.reason for row in skipped_rows)
    print("\nSkipped devices by reason:")
    for reason, count in counts.most_common():
        print(f"  {count:>4}  {reason}")

    print("\nSkipped device list:")
    print(f"{'TYPE':<24} {'ID':<20} {'NAME':<32} REASON")
    print("-" * 100)
    for row in skipped_rows:
        print(f"{row.device_type:<24} {row.device_id:<20} {row.name[:32]:<32} {row.reason}")


def main() -> int:
    args = parse_args()
    includes = _split_csv(args.include_types)
    excludes = _split_csv(args.exclude_types)

    if args.all:
        allowed: set[str] | None = None
        skipped = set(excludes)
    else:
        allowed = set(PASSIVE_TYPES) | includes
        skipped = (set(SKIPPED_BY_DEFAULT_TYPES) - includes) | excludes

    print(f"Connecting to grid '{args.grid or 'auto'}' ...")
    try:
        grid = prepare_grid(args.grid, auto_wake=True, wake_timeout=5.0)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"redis error: {exc}", file=sys.stderr)
        return 2

    time.sleep(1.0)
    _refresh_grid_devices(grid)

    rows, skipped_rows = _select_rows(grid, allowed, skipped)
    already_on = [row for row in rows if row.enabled is True]
    currently_off = [row for row in rows if row.enabled is False]
    unknown = [row for row in rows if row.enabled is None]
    reactors_selected = [row for row in rows if row.device_type == "reactor"]
    reactors_skipped = [row for row in skipped_rows if row.device_type == "reactor"]

    targets = currently_off if args.only_off else rows
    targets.sort(key=_sort_key)

    print()
    grid_name = getattr(grid, "name", None) or args.grid or "(unknown)"
    grid_id = getattr(grid, "grid_id", "?")
    print(f"Grid: {grid_name} (id={grid_id})")
    print(
        f"Devices selected: {len(rows)} | already ON: {len(already_on)} "
        f"| currently OFF: {len(currently_off)} | unknown: {len(unknown)} "
        f"| enable targets: {len(targets)}"
    )
    print(f"Reactors selected: {len(reactors_selected)} | reactors skipped: {len(reactors_skipped)}")
    print()
    _print_rows(rows, targets)

    if reactors_skipped:
        print("\nWARNING: some reactors were skipped:")
        for row in reactors_skipped:
            print(f"  reactor {row.name} ({row.device_id}): {row.reason}")
        print("Use --debug-skipped for the full skipped-device list.")

    if args.debug_skipped:
        _print_skipped(skipped_rows)

    if not targets:
        print("\nNothing to enable.")
        return 0

    if args.dry_run:
        print(f"\n[dry-run] Would send ON to {len(targets)} devices.")
        return 0

    print(f"\nSending ON to {len(targets)} devices ...")
    sent_ok = 0
    sent_fail = 0
    command_failures: list[tuple[DeviceRow, str]] = []

    for row in targets:
        device = _fresh_device(grid, row)
        try:
            result = _send_enable(device)
        except Exception as exc:
            sent_fail += 1
            command_failures.append((row, str(exc)))
            print(f"  ! {row.device_type} {row.name} ({row.device_id}): {exc}")
        else:
            if result > 0:
                sent_ok += 1
            else:
                sent_fail += 1
                command_failures.append((row, "command returned 0"))
                print(f"  ! {row.device_type} {row.name} ({row.device_id}): command returned 0")
        time.sleep(max(0.0, args.command_pace))

    print(f"  ON command returned: {sent_ok} ok, {sent_fail} failed")

    if args.no_verify:
        return 0 if sent_fail == 0 else 1

    print(f"\nVerifying (first wait {args.verify_delay:.1f}s) ...")
    time.sleep(max(0.0, args.verify_delay))

    still_not_on: list[tuple[DeviceRow, bool | None]] = []
    attempts = max(1, int(args.verify_attempts))
    interval = max(0.0, float(args.verify_interval))

    for attempt in range(1, attempts + 1):
        _refresh_grid_devices(grid)
        still_not_on.clear()

        for row in targets:
            device = _fresh_device(grid, row)
            now = _read_enabled(device)
            if now is not True:
                still_not_on.append((row, now))

        if not still_not_on:
            break

        if attempt < attempts:
            print(
                f"  verify attempt {attempt}/{attempts}: "
                f"{len(still_not_on)} devices not confirmed ON yet; retrying ..."
            )
            time.sleep(interval)

    if still_not_on:
        print(f"  {len(still_not_on)} targeted devices are still not confirmed ON:")
        for row, now in still_not_on:
            device = _fresh_device(grid, row)
            working = _read_working(device)
            print(
                f"    {row.device_type} {row.name} ({row.device_id}) "
                f"enabled={now} working={working}"
            )

        if command_failures:
            print("\n  Command failures:")
            for row, error in command_failures:
                print(f"    {row.device_type} {row.name} ({row.device_id}): {error}")
        return 1

    print("  All targeted devices are confirmed ON.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
