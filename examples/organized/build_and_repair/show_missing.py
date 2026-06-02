#!/usr/bin/env python3
"""Show Nanobot BuildAndRepair missing construction items."""

from __future__ import annotations

import argparse
import json
from typing import Any

from secontrol.common import close, prepare_grid


SCRIPT_VERSION = "build-and-repair-missing-v1-2026-05-31"


def normalize_missing(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("missingItemsList")
    if isinstance(items, list) and items:
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("key") or "?")
            amount = item.get("amount")
            result.append({"name": name, "amount": amount, "key": item.get("key")})
        return result

    missing = data.get("missingComponents") or data.get("missingItems") or {}
    if isinstance(missing, dict):
        return [{"name": str(key), "amount": value, "key": str(key)} for key, value in missing.items()]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Show missing items reported by Nanobot BuildAndRepair systems")
    parser.add_argument("--grid", default="", help="Grid name or id")
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

            missing = normalize_missing(data)
            if missing:
                print("missing:")
                for item in missing:
                    print(f"  {item['name']}: {item['amount']}")
            else:
                print("missing: none reported")

        return 0
    finally:
        if grid is not None:
            close(grid)


if __name__ == "__main__":
    raise SystemExit(main())
