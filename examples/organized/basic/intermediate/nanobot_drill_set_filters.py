#!/usr/bin/env python3
"""Set Nanobot Drill and Fill ore filters from Python.

Examples:
    python examples/organized/basic/intermediate/nanobot_drill_set_filters.py
    python examples/organized/basic/intermediate/nanobot_drill_set_filters.py --grid taburet2 Iron Nickel Cobalt
    python examples/organized/basic/intermediate/nanobot_drill_set_filters.py --grid taburet2 --none
    python examples/organized/basic/intermediate/nanobot_drill_set_filters.py --grid taburet2 --all
    python examples/organized/basic/intermediate/nanobot_drill_set_filters.py --grid taburet2 --drill "Nanobot Drill" --mode Collect Ice

The command sent to the C# adapter is:
    {"cmd": "set", "payload": {"property": "OreFilter", "value": [slot indices]}}
    {"cmd": "set", "payload": {"property": "ResourceFilter", "value": ["Ore"]}}
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Iterable, Optional, Union

from secontrol.common import close, prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

DEFAULT_GRID = "taburet"
DEFAULT_ORES = ["Iron", "Nickel", "Cobalt", "Magnesium"]
DEFAULT_RESOURCES = ["Ore"]
RESOURCE_CLASS_IDS = {
    "ingot": 1,
    "ingots": 1,
    "ore": 2,
    "ores": 2,
    "stone": 3,
    "stones": 3,
    "rock": 3,
    "rocks": 3,
    "gravel": 4,
}


def _split_filter_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for part in str(value).replace(";", ",").replace("|", ",").split(","):
            item = part.strip()
            if item:
                result.append(item)
    return result


def _find_drill(grid: Any, selector: Optional[str]) -> NanobotDrillSystemDevice:
    drills = list(grid.find_devices_by_type(NanobotDrillSystemDevice))
    if not drills:
        raise RuntimeError(f"No Nanobot Drill System devices found on grid {grid.grid_id}")

    if not selector:
        return drills[0]

    selector_text = str(selector).strip()
    if selector_text.isdigit():
        by_id = getattr(grid, "devices_by_num", {}).get(int(selector_text))
        if isinstance(by_id, NanobotDrillSystemDevice):
            return by_id

    for drill in drills:
        if str(getattr(drill, "device_id", "")) == selector_text:
            return drill

    selector_lower = selector_text.lower()
    exact = [drill for drill in drills if (drill.name or "").lower() == selector_lower]
    if exact:
        return exact[0]

    partial = [drill for drill in drills if selector_lower in (drill.name or "").lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = [f"{drill.name} ({drill.device_id})" for drill in partial]
        raise RuntimeError(f"Drill selector is ambiguous: {names}")

    names = [f"{drill.name} ({drill.device_id})" for drill in drills]
    raise RuntimeError(f"Drill {selector_text!r} not found. Available drills: {names}")


def _build_filter_value(args: argparse.Namespace) -> Union[str, list[str]]:
    selected_modes = int(args.all) + int(args.none)
    if selected_modes > 1:
        raise ValueError("Use only one of --all or --none")

    ores = _split_filter_values(args.ores)
    if selected_modes and ores:
        raise ValueError("Do not pass ore names together with --all or --none")

    if args.all:
        return "all"
    if args.none:
        return "none"

    return ores or list(DEFAULT_ORES)


def _build_resource_filter_value(args: argparse.Namespace) -> Union[str, list[str], None]:
    selected_modes = int(args.all_resources) + int(args.no_resources)
    if selected_modes > 1:
        raise ValueError("Use only one of --all-resources or --no-resources")

    resource_text = str(args.resources or "").strip()
    if resource_text.lower() in {"", "keep", "current", "unchanged", "skip", "false"} and not selected_modes:
        return None

    if args.all_resources:
        return "all"
    if args.no_resources:
        return "none"

    resources = _split_filter_values([resource_text])
    return resources or list(DEFAULT_RESOURCES)


def _resolve_filter_payload(
    drill: NanobotDrillSystemDevice,
    filter_value: Union[str, list[str]],
) -> Union[str, list[int]]:
    if isinstance(filter_value, str):
        return filter_value

    explicit_indices: list[int] = []
    ore_names: list[str] = []

    for item in filter_value:
        text = str(item).strip()
        if not text:
            continue
        try:
            explicit_indices.append(int(text))
            continue
        except ValueError:
            ore_names.append(text)

    resolved = list(explicit_indices)
    if ore_names:
        resolved.extend(drill._compute_slot_indices_for_ore_names(ore_names))

    unique_sorted = sorted(set(resolved))
    if not unique_sorted:
        raise RuntimeError(
            "No ore slots matched the requested filter. Check Drill.DrillPriorityList telemetry."
        )
    return unique_sorted


def _resolve_resource_payload(filter_value: Union[str, list[str], None]) -> Union[str, list[Union[int, str]], None]:
    if filter_value is None:
        return None
    if isinstance(filter_value, str):
        return filter_value

    resolved: list[Union[int, str]] = []
    for item in filter_value:
        text = str(item).strip()
        if not text:
            continue
        try:
            resolved.append(int(text))
        except ValueError:
            resolved.append(RESOURCE_CLASS_IDS.get(text.lower(), text))

    if not resolved:
        raise RuntimeError("No resource filters were provided")
    return resolved


def _send_script_control(drill: NanobotDrillSystemDevice) -> int:
    return drill.send_command(
        {
            "cmd": "scriptcontrol",
            "value": True,
        }
    )


def _send_work_mode(drill: NanobotDrillSystemDevice, mode: str) -> int:
    normalized = str(mode or "").strip().lower()
    if normalized in {"", "keep", "current", "unchanged", "none", "false"}:
        return 0

    mode_map = {
        "fill": 0,
        "collect": 1,
        "drill": 2,
    }
    value: Union[int, str]
    if normalized in mode_map:
        value = mode_map[normalized]
    else:
        try:
            value = int(normalized)
        except ValueError:
            value = mode

    return drill.send_command(
        {
            "cmd": "set",
            "payload": {
                "property": "Drill.WorkMode",
                "value": value,
            },
        }
    )


def _print_state(drill: NanobotDrillSystemDevice, label: str) -> None:
    drill.update()
    drill.wait_for_telemetry(timeout=5)

    telemetry = drill.telemetry or {}
    properties = telemetry.get("properties") or {}
    enabled = None
    try:
        enabled = drill.debug_get_enabled_known_ores()
    except Exception as exc:  # keep example diagnostics best-effort
        enabled = f"<cannot decode known ores: {exc}>"

    print(f"\n{label}")
    print(f"  workMode: {properties.get('Drill.WorkMode') or telemetry.get('drill_workmode')}")
    print(f"  collectPriorityList: {properties.get('Drill.CollectPriorityList')}")
    print(
        "  componentClassList:",
        properties.get("Drill.ComponentClassList") or telemetry.get("drill_componentclasslist"),
    )
    print(
        "  scriptControlled:",
        properties.get("Drill.ScriptControlled")
        or telemetry.get("drill_scriptcontrolled")
        or telemetry.get("scriptControlled"),
    )
    print(f"  oreFilterIndices: {telemetry.get('oreFilterIndices')}")
    resource_indices = telemetry.get("resourceFilterIndices")
    if resource_indices is None:
        resource_indices = telemetry.get("collectFilterIndices")
    print(f"  resourceFilterIndices: {resource_indices}")
    print(f"  enabledKnownOres: {enabled}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set ore filters on a Nanobot Drill and Fill block.",
    )
    parser.add_argument(
        "--grid",
        "-g",
        default=DEFAULT_GRID,
        help="Grid name or grid entity id, for example taburet2 or 105430401719413217.",
    )
    parser.add_argument(
        "--drill",
        "-d",
        help="Optional Nanobot Drill block name or device entity id. Defaults to the first drill on the grid.",
    )
    parser.add_argument(
        "--mode",
        default="Collect",
        help="WorkMode to request with the filter command. Use Collect for selective ore collection. Use keep to leave current mode.",
    )
    parser.add_argument("--all", action="store_true", help="Enable all ore slots.")
    parser.add_argument("--none", action="store_true", help="Disable all ore slots.")
    parser.add_argument(
        "--resources",
        default=",".join(DEFAULT_RESOURCES),
        help=(
            "Resource collection filters for Drill.ComponentClassList, for example Ore or Ingot,Ore. "
            "Use keep to skip. Default: Ore."
        ),
    )
    parser.add_argument("--all-resources", action="store_true", help="Enable all resource collection slots.")
    parser.add_argument("--no-resources", action="store_true", help="Disable all resource collection slots.")
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Turn the Nanobot Drill block on after applying filters.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1.0,
        help="Seconds to wait before reading telemetry after the command.",
    )
    parser.add_argument(
        "ores",
        nargs="*",
        help=f"Ore names or slot indices. Comma-separated values are accepted too. Default: {', '.join(DEFAULT_ORES)}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    filter_value = _build_filter_value(args)
    resource_filter_value = _build_resource_filter_value(args)

    grid = prepare_grid(args.grid)
    try:
        drill = _find_drill(grid, args.drill)
        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"Nanobot Drill: {drill.name} ({drill.device_id})")

        _print_state(drill, "Before")

        filter_payload = _resolve_filter_payload(drill, filter_value)
        resource_payload = _resolve_resource_payload(resource_filter_value)
        payload: dict[str, Any] = {
            "cmd": "set",
            "payload": {
                "property": "OreFilter",
                "value": filter_payload,
                "workMode": args.mode,
            },
        }
        resource_command: Optional[dict[str, Any]] = None
        if resource_payload is not None:
            resource_command = {
                "cmd": "set",
                "payload": {
                    "property": "ResourceFilter",
                    "value": resource_payload,
                },
            }

        print("\nEnabling script control and setting work mode...")
        print(f"Script control command published to {_send_script_control(drill)} channel(s)")
        mode_sent = _send_work_mode(drill, args.mode)
        if mode_sent:
            print(f"WorkMode command published to {mode_sent} channel(s)")

        print("\nSending payload:")
        print(json.dumps(payload, indent=2))
        sent = drill.send_command(payload)
        print(f"Published to {sent} channel(s)")

        if resource_command is not None:
            print("\nSending resource filter payload:")
            print(json.dumps(resource_command, indent=2))
            sent = drill.send_command(resource_command)
            print(f"Published to {sent} channel(s)")

        print("\nDisabling script control for auto-mining...")
        drill.send_command(
            {
                "cmd": "set",
                "payload": {
                    "property": "Drill.ScriptControlled",
                    "value": False,
                },
            }
        )
        print("ScriptControlled set to False")

        if args.enable:
            drill.send_command({"cmd": "enable"})
            print("Enable command sent")

        time.sleep(max(0.0, args.wait))
        _print_state(drill, "After")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
