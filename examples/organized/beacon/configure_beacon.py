"""Configure a Space Engineers beacon radius and HUD label."""

from __future__ import annotations

import argparse
import time

from secontrol.common import close, prepare_grid, resolve_owner_id


def find_beacon(grid, name_part: str | None):
    beacons = [device for device in grid.devices.values() if device.device_type == "beacon"]
    if not beacons:
        raise RuntimeError(f"No beacons found on grid '{grid.name}'.")

    if not name_part:
        return beacons[0]

    needle = name_part.strip().lower()
    for beacon in beacons:
        haystack = f"{beacon.name} {(beacon.telemetry or {}).get('hudText', '')}".lower()
        if needle in haystack:
            return beacon

    available = ", ".join(f"'{beacon.name}'" for beacon in beacons)
    raise RuntimeError(f"Beacon containing '{name_part}' was not found. Available beacons: {available}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure beacon broadcast radius and HUD label")
    parser.add_argument("grid", nargs="?", default=None, help="Grid id or grid name")
    parser.add_argument("--beacon", default=None, help="Part of beacon terminal name or HUD label")
    parser.add_argument("--radius", type=float, default=None, help="Broadcast radius in meters")
    parser.add_argument("--text", default=None, help="HUD label text")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait before printing telemetry")
    args = parser.parse_args()

    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid(args.grid) if args.grid else prepare_grid()
    try:
        beacon = find_beacon(grid, args.beacon)
        print(f"Grid: {grid.name}")
        print(f"Beacon: {beacon.name} ({beacon.device_id})")
        print(f"Before: radius={(beacon.telemetry or {}).get('radius')}, hudText={(beacon.telemetry or {}).get('hudText')!r}")

        sent = 0
        if args.radius is not None:
            sent += beacon.send_command({"cmd": "set_radius", "radius": args.radius})
            print(f"Set radius command sent: {args.radius:g} m")

        if args.text is not None:
            sent += beacon.send_command({"cmd": "set_text", "text": args.text})
            print(f"Set HUD text command sent: {args.text!r}")

        if sent <= 0:
            print("No command was published. Check Redis connection and beacon selection.")
            return

        time.sleep(max(0.0, args.wait))
        beacon.update()
        beacon.wait_for_telemetry(timeout=5.0, wait_for_new=True, need_update=False)
        print(f"After: radius={(beacon.telemetry or {}).get('radius')}, hudText={(beacon.telemetry or {}).get('hudText')!r}")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
