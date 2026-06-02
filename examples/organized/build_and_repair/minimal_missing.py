#!/usr/bin/env python3
from __future__ import annotations

from secontrol.common import close, prepare_grid


GRID_NAME = "farpost0"
BAR_NAME = "BuildAndRepairSystem"


def main() -> int:
    grid = None

    try:
        grid = prepare_grid(GRID_NAME, auto_wake=True)
        grid.refresh_devices()

        systems = grid.find_devices_by_type("nanobot_build_and_repair")
        systems = [
            system
            for system in systems
            if BAR_NAME.lower() in str(system.name or "").lower()
        ]

        if not systems:
            print(f"Nanobot BuildAndRepair system not found on grid: {grid.name}")
            return 1

        for system in systems:
            print(f"Grid: {grid.name}")
            print(f"Device: {system.name} ({system.device_id})")

            report = system.missing_report(wait=2.0)

            print(f"Enabled: {report.get('enabled')}")
            print(f"Functional: {report.get('is_functional')}")
            print(f"Working: {report.get('is_working')}")
            print(f"Source: {report.get('source')}")

            projectors = report.get("projectors_checked") or []
            for projector in projectors:
                print(
                    "Projector: "
                    f"{projector.get('name')} | "
                    f"projecting={projector.get('isProjecting')} | "
                    f"remaining={projector.get('remainingBlocks')} | "
                    f"buildable={projector.get('buildableBlocks')}"
                )

            items = report.get("items") or []
            if not items:
                print("Missing items: none")
                continue

            print("Missing items:")
            for item in items:
                display_name = item.get("display_name") or item.get("name")
                name = item.get("name")
                amount = item.get("amount")
                print(f"  {display_name} ({name}): {amount}")

        return 0

    finally:
        if grid is not None:
            close(grid)


if __name__ == "__main__":
    raise SystemExit(main())