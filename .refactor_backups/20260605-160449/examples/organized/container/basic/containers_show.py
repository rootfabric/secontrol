"""Показать содержимое всех контейнеров на гриде.

Использование:
    python examples/organized/container/basic/containers_show.py --grid farpost0
    python examples/organized/container/basic/containers_show.py --grid agent0 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from secontrol.common import prepare_grid, close
from secontrol.devices.container_device import ContainerDevice


def show_containers(grid, *, as_json: bool = False) -> None:
    containers = grid.find_devices_containers()

    if as_json:
        result = []
        for device in containers:
            items = device.inventory_items()
            entry = {
                "device": device.name,
                "type": device.device_type,
                "id": str(device.device_id),
                "items": [
                    {"name": i.display_name or i.subtype, "subtype": i.subtype, "amount": round(i.amount, 2)}
                    for i in (items or [])
                ],
            }
            result.append(entry)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    print(f"Грид: {grid.name} ({grid.grid_id})")
    print(f"Контейнеров: {len(containers)}")
    print("=" * 60)

    total = 0.0
    for device in containers:
        items = device.inventory_items()
        if not items:
            continue
        count = sum(i.amount for i in items)
        total += count

        print(f"\n[{device.name}] ({device.device_type})")
        for item in sorted(items, key=lambda i: -i.amount):
            name = item.display_name or item.subtype or "?"
            amt = item.amount
            print(f"  {name}: {int(amt) if amt == int(amt) else round(amt, 2)}")

    summary = defaultdict(float)
    for device in containers:
        for item in (device.inventory_items() or []):
            summary[item.display_name or item.subtype] += item.amount

    if summary:
        print(f"\n{'=' * 60}")
        print("ИТОГО:")
        for name, amt in sorted(summary.items(), key=lambda x: -x[1]):
            val = int(amt) if amt == int(amt) else round(amt, 2)
            print(f"  {name}: {val}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Показать содержимое контейнеров грида")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--json", action="store_true", help="Вывод в JSON")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        show_containers(grid, as_json=args.json)
    finally:
        close(grid)


if __name__ == "__main__":
    main()
