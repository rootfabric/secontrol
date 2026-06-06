"""Configure a Space Engineers radio antenna radius and HUD label."""

from __future__ import annotations

import argparse
import time

from secontrol.common import close, prepare_grid, resolve_owner_id


def parse_bool(value: str) -> bool:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    raise argparse.ArgumentTypeError("expected one of: on/off, true/false, 1/0")


def find_antenna(grid, name_part: str | None):
    antennas = [device for device in grid.devices.values() if device.device_type in {"antenna", "radio_antenna"}]
    if not antennas:
        raise RuntimeError(f"No radio antennas found on grid '{grid.name}'.")

    if not name_part:
        return antennas[0]

    needle = name_part.strip().lower()
    for antenna in antennas:
        haystack = f"{antenna.name} {(antenna.telemetry or {}).get('hudText', '')} {(antenna.telemetry or {}).get('antennaText', '')}".lower()
        if needle in haystack:
            return antenna

    available = ", ".join(f"'{antenna.name}'" for antenna in antennas)
    raise RuntimeError(f"Antenna containing '{name_part}' was not found. Available antennas: {available}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure antenna broadcast radius and HUD label")
    parser.add_argument("grid", nargs="?", default=None, help="Grid id or grid name")
    parser.add_argument("--antenna", default=None, help="Part of antenna terminal name or HUD label")
    parser.add_argument("--radius", type=float, default=None, help="Broadcast radius in meters")
    parser.add_argument("--text", default=None, help="HUD label text")
    parser.add_argument("--broadcasting", type=parse_bool, default=None, help="Enable or disable antenna broadcasting: on/off")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait before printing telemetry")
    args = parser.parse_args()

    owner_id = resolve_owner_id()
    print(f"Using owner id: {owner_id}")

    grid = prepare_grid(args.grid) if args.grid else prepare_grid()
    try:
        antenna = find_antenna(grid, args.antenna)
        telemetry = antenna.telemetry or {}
        print(f"Grid: {grid.name}")
        print(f"Antenna: {antenna.name} ({antenna.device_id})")
        print(
            "Before: "
            f"radius={telemetry.get('radius')}, "
            f"hudText={telemetry.get('hudText')!r}, "
            f"enableBroadcasting={telemetry.get('enableBroadcasting')}, "
            f"isBroadcasting={telemetry.get('isBroadcasting')}"
        )

        sent = 0
        if args.radius is not None:
            sent += antenna.send_command({"cmd": "set_radius", "radius": args.radius})
            print(f"Set radius command sent: {args.radius:g} m")

        if args.text is not None:
            sent += antenna.send_command({"cmd": "set_text", "text": args.text})
            print(f"Set HUD text command sent: {args.text!r}")

        if args.broadcasting is not None:
            sent += antenna.send_command({"cmd": "set_broadcasting", "enabled": args.broadcasting})
            print(f"Set broadcasting command sent: {args.broadcasting}")

        if sent <= 0:
            print("No command was published. Check Redis connection and antenna selection.")
            return

        time.sleep(max(0.0, args.wait))
        antenna.update()
        antenna.wait_for_telemetry(timeout=5.0, wait_for_new=True, need_update=False)
        telemetry = antenna.telemetry or {}
        print(
            "After: "
            f"radius={telemetry.get('radius')}, "
            f"hudText={telemetry.get('hudText')!r}, "
            f"enableBroadcasting={telemetry.get('enableBroadcasting')}, "
            f"isBroadcasting={telemetry.get('isBroadcasting')}"
        )
    finally:
        close(grid)


if __name__ == "__main__":
    main()
