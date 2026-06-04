#!/usr/bin/env python3
"""Show Nanobot BuildAndRepair missing construction items."""

from __future__ import annotations

import argparse
import json
from typing import Any

from secontrol.common import close, prepare_grid
from secontrol.devices.build_and_repair_device import normalize_missing_items


SCRIPT_VERSION = "build-and-repair-missing-v2-delegate-components-2026-06-02"


def normalize_missing(data: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_missing_items(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show missing items reported by Nanobot BuildAndRepair systems")
    parser.add_argument("--grid", default="farpost", help="Grid name or id")
    parser.add_argument("--name", default="", help="Only show BaR blocks whose name contains this text")
    parser.add_argument("--json", action="store_true", help="Print raw status JSON")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait for a fresh telemetry update")
    args = parser.parse_args()

    print(f"SCRIPT_VERSION: {SCRIPT_VERSION}")
    grid = None
    try:
        grid = prepare_grid(args.grid or None, auto_wake=True)
        grid.refresh_devices()
        devices = grid.find_devices_by_type("nanobot_build_and_repair")
        if args.name:
            needle = args.name.lower()
            devices = [dev for dev in devices if needle in str(dev.name or "").lower()]

        print(f"Grid: {grid.name} ({grid.grid_id})")
        print(f"BuildAndRepair systems: {len(devices)}")
        if not devices:
            return 1

        for dev in devices:
            print("-" * 70)
            print(f"{dev.name} ({dev.device_id})")
            data = dev.status_snapshot(wait=args.wait) if hasattr(dev, "status_snapshot") else dict(dev.telemetry or {})
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))

            print(f"enabled={data.get('enabled')} functional={data.get('isFunctional')} working={data.get('isWorking')}")
            status = data.get("status")
            if isinstance(status, dict) and status:
                important = {k: v for k, v in status.items() if "state" in k or "status" in k or "mode" in k or "недоста" in k}
                if important:
                    print("status:", json.dumps(important, ensure_ascii=False))

            raw_info = str(data.get("rawDetailedInfo") or data.get("detailedInfo") or "").strip()
            if raw_info:
                print("detailedInfo:")
                print(raw_info)

            source = data.get("missingComponentsSource")
            if source:
                print(f"source: {source}")

            projectors = data.get("nanobotProjectorsChecked") or []
            if isinstance(projectors, list) and projectors:
                print("projectors checked:")
                for projector in projectors:
                    if not isinstance(projector, dict):
                        continue
                    print(
                        "  "
                        f"{projector.get('name') or projector.get('id')}: "
                        f"projecting={projector.get('isProjecting')} "
                        f"remaining={projector.get('remainingBlocks')} "
                        f"buildable={projector.get('buildableBlocks')}"
                    )

            missing = normalize_missing(data)
            if missing:
                print("missing:")
                for item in missing:
                    display = item.get("display_name") or item.get("name")
                    name = item.get("name")
                    suffix = f" ({name})" if display != name else ""
                    print(f"  {display}{suffix}: {item.get('amount')}")
            else:
                checked = data.get("missingComponentsDelegateChecked")
                diagnostics = data.get("missingComponentsDiagnostics") or []
                if checked is not None:
                    print(f"missing: none reported (delegates checked: {checked})")
                else:
                    print("missing: none reported")
                if isinstance(diagnostics, list) and diagnostics:
                    failed = [d for d in diagnostics if isinstance(d, dict) and d.get("error")]
                    if failed:
                        print("delegate errors:")
                        for diag in failed[:5]:
                            print(f"  {diag.get('property')}: {diag.get('error')}")

        return 0
    finally:
        if grid is not None:
            close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
