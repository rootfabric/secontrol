from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Optional

from secontrol.common import prepare_grid

DEFAULT_GRID = "skynet-farpost0"
DEFAULT_NAME = "Батарея 44"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enable, disable or toggle a Space Engineers battery block.")
    parser.add_argument("command", nargs="?", choices=("on", "off", "toggle", "status"), default="toggle")
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--id", type=int, dest="device_id", default=None)
    parser.add_argument("--mode", choices=("auto", "recharge", "discharge", "semiauto"), default=None)
    parser.add_argument("--timeout", type=float, default=4.0)
    parser.add_argument("--startup-wait", type=float, default=1.5)
    return parser.parse_args()


def find_battery(grid: Any, *, name: str, device_id: Optional[int]) -> Any:
    for device in grid.devices.values():
        if device.device_type != "battery":
            continue
        if device_id is not None and int(device.device_id) == int(device_id):
            return device
        if device_id is None and device.name == name:
            return device
    return None


def fmt(value: Any, default: str = "N/A") -> str:
    return default if value is None else str(value)


def print_status(device: Any, label: str) -> None:
    telemetry = device.telemetry or {}
    status = device.functional_status() if hasattr(device, "functional_status") else {
        "enabled": device.is_enabled(),
        "chargeMode": telemetry.get("chargeMode"),
        "currentStoredPowerMWh": telemetry.get("currentStoredPower"),
        "maxStoredPowerMWh": telemetry.get("maxStoredPower"),
        "maxOutputMW": telemetry.get("maxOutputMW", telemetry.get("maxOutput")),
    }

    print(
        f"{label}: id={device.device_id} name={device.name!r} "
        f"enabled={status.get('enabled')} source={fmt(status.get('enabledSource'))} "
        f"terminalOnOff={fmt(status.get('terminalOnOff'))} "
        f"functionalEnabled={fmt(status.get('functionalEnabled'))} "
        f"isFunctional={fmt(status.get('isFunctional'))} "
        f"isWorking={fmt(status.get('isWorking'))} "
        f"mode={fmt(status.get('chargeMode'))} "
        f"charge={fmt(status.get('currentStoredPowerMWh'))}/{fmt(status.get('maxStoredPowerMWh'))} MWh "
        f"maxOut={fmt(status.get('maxOutputMW'))} MW"
    )


def main() -> int:
    args = parse_args()

    grid = prepare_grid(args.grid)
    time.sleep(max(0.0, args.startup_wait))

    device = find_battery(grid, name=args.name, device_id=args.device_id)
    if device is None:
        selector = f"id={args.device_id}" if args.device_id is not None else f"name={args.name!r}"
        print(f"Battery not found: {selector}")
        return 1

    print_status(device, "before")

    ok: bool | int = True
    if args.command == "on":
        ok = device.enable_verified(timeout=args.timeout) if hasattr(device, "enable_verified") else device.enable()
        print(f"enable_verified() -> {ok}")
    elif args.command == "off":
        ok = device.disable_verified(timeout=args.timeout) if hasattr(device, "disable_verified") else device.disable()
        print(f"disable_verified() -> {ok}")
    elif args.command == "toggle":
        if device.is_enabled():
            ok = device.disable_verified(timeout=args.timeout) if hasattr(device, "disable_verified") else device.disable()
            print(f"disable_verified() -> {ok}")
        else:
            ok = device.enable_verified(timeout=args.timeout) if hasattr(device, "enable_verified") else device.enable()
            print(f"enable_verified() -> {ok}")

    if args.mode:
        if hasattr(device, "set_mode_verified"):
            mode_ok = device.set_mode_verified(args.mode, timeout=args.timeout)
        else:
            mode_ok = device.set_mode(args.mode)
        print(f"set_mode_verified({args.mode!r}) -> {mode_ok}")
        ok = bool(ok) and bool(mode_ok)

    try:
        device.wait_for_telemetry(timeout=1.0, wait_for_new=True, need_update=True)
    except Exception:
        pass

    print_status(device, "after")
    return 0 if bool(ok) else 2


if __name__ == "__main__":
    sys.exit(main())
