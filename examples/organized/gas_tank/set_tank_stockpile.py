"""Turn Stockpile / "Накопитель" mode on or off for a gas tank.

Examples:
    python examples/organized/gas_tank/set_tank_stockpile.py skynet-baza0 --tank "Hydrogen Tank 2" --stockpile on
    python examples/organized/gas_tank/set_tank_stockpile.py skynet-baza0 --tank-id 126072844386138032 --stockpile off
"""

from __future__ import annotations

import argparse
import json

from secontrol.common import close, prepare_grid


def parse_bool(value: str) -> bool:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled", "stockpile"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled", "auto"}:
        return False
    raise argparse.ArgumentTypeError("expected one of: on/off, true/false, 1/0")


def find_tank(grid, *, tank_id: int | None, name_part: str | None):
    if tank_id is not None:
        tank = grid.get_device_by_id(tank_id)
        if tank is None:
            raise RuntimeError(f"Gas tank with id {tank_id} was not found on grid '{grid.name}'.")
        return tank

    tanks = [device for device in grid.devices.values() if device.device_type == "gas_tank"]
    if not tanks:
        raise RuntimeError(f"No gas tanks found on grid '{grid.name}'.")

    if not name_part:
        return tanks[0]

    needle = name_part.strip().lower()
    for tank in tanks:
        telemetry = tank.telemetry or {}
        haystack = f"{tank.name} {telemetry.get('subtype', '')} {telemetry.get('type', '')}".lower()
        if needle in haystack:
            return tank

    available = ", ".join(f"'{tank.name}' ({tank.device_id})" for tank in tanks)
    raise RuntimeError(f"Gas tank containing '{name_part}' was not found. Available tanks: {available}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure gas tank Stockpile / Накопитель mode")
    parser.add_argument("grid", help="Grid id or grid name")
    parser.add_argument("--tank", default=None, help="Part of tank terminal name")
    parser.add_argument("--tank-id", type=int, default=None, help="Exact tank entity id")
    parser.add_argument("--stockpile", type=parse_bool, required=True, help="Stockpile mode: on/off")
    parser.add_argument("--enable-block", action="store_true", help="Also turn the tank block on before changing stockpile")
    parser.add_argument("--timeout", type=float, default=3.0, help="Telemetry confirmation timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print final telemetry as JSON")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        tank = find_tank(grid, tank_id=args.tank_id, name_part=args.tank)
        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"Tank: {tank.name} ({tank.device_id})")
        print(f"Before: stockpile={tank.stockpile()} enabled={(tank.telemetry or {}).get('enabled')} filledPercent={tank.filled_percent():.2f}")

        if args.enable_block and hasattr(tank, "enable"):
            tank.enable()

        if not hasattr(tank, "set_stockpile_verified"):
            raise RuntimeError("Selected device does not support set_stockpile_verified(). Update secontrol Python package.")

        ok = tank.set_stockpile_verified(args.stockpile, timeout=args.timeout)
        tank.wait_for_telemetry(timeout=args.timeout, wait_for_new=True, need_update=True)

        print(f"After:  stockpile={tank.stockpile()} enabled={(tank.telemetry or {}).get('enabled')} filledPercent={tank.filled_percent():.2f}")
        print(f"Result: {'OK' if ok else 'FAILED'}")

        if args.json:
            print(json.dumps(tank.telemetry or {}, ensure_ascii=False, indent=2))
    finally:
        close(grid)


if __name__ == "__main__":
    main()
