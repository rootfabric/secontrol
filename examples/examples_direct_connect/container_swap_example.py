from __future__ import annotations

import time
from typing import Dict, Any, List

from secontrol.devices.container_device import ContainerDevice, Item
from secontrol.common import resolve_owner_id, prepare_grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    grid = prepare_grid()

    containers = grid.find_devices_by_type(ContainerDevice)
    print(f"Found {len(containers)} container device(s):")

    for i, container in enumerate(containers, 1):
        print(f"{i}. {container.name or 'Container'} (ID: {container.device_id})")

        items = container.items()
        if items:
            pretty = ", ".join(f"{it.amount} x {it.display_name or it.subtype or '?'}"
                              for it in items)
            print(f"   Items: {pretty}")
        else:
            print("   Items: empty")

    if len(containers) < 2:
        print("Need at least 2 containers to demonstrate swapping.")
        print("This example shows how to swap items between containers using a temporary transfer.")
        return

    # For demonstration, let's swap items between first two containers
    container1 = containers[0]
    container2 = containers[1]

    print(f"\nUsing containers:")
    print(f"  Container 1: {container1.name or 'Container'} (ID: {container1.device_id})")
    print(f"  Container 2: {container2.name or 'Container'} (ID: {container2.device_id})")

    # Get initial state
    items1_before = container1.items()
    items2_before = container2.items()

    print("\nInitial state:")
    print(f"  Container 1: {format_items(items1_before)}")
    print(f"  Container 2: {format_items(items2_before)}")

    # Example 1: Swap all items between containers
    print("\n=== Example 1: Swap all items between containers ===")

    # Move all from container1 to container2
    container1.move_all(container2.device_id)
    time.sleep(0.5)  # Wait for operation to complete

    # Move all from container2 (original container2 items) to container1
    container2.move_all(container1.device_id)
    time.sleep(0.5)

    items1_after = container1.items()
    items2_after = container2.items()

    print("After swapping all items:")
    print(f"  Container 1: {format_items(items1_after)}")
    print(f"  Container 2: {format_items(items2_after)}")

    # Example 2: Swap specific item types
    print("\n=== Example 2: Swap specific item types ===")

    # Let's try to swap SteelPlate items if they exist
    steel_plates_1 = container1.find_items_by_subtype("SteelPlate")
    steel_plates_2 = container2.find_items_by_subtype("SteelPlate")

    if steel_plates_1 and steel_plates_2:
        print("Found SteelPlate in both containers, swapping them...")

        # Move SteelPlate from container1 to container2
        container1.move_subtype(container2.device_id, "SteelPlate")
        time.sleep(0.5)

        # Move SteelPlate from container2 to container1
        container2.move_subtype(container1.device_id, "SteelPlate")
        time.sleep(0.5)

        items1_final = container1.items()
        items2_final = container2.items()

        print("After swapping SteelPlate items:")
        print(f"  Container 1: {format_items(items1_final)}")
        print(f"  Container 2: {format_items(items2_final)}")
    else:
        print("SteelPlate not found in both containers, skipping specific type swap.")

    # Example 3: Demonstrate partial amount swapping
    print("\n=== Example 3: Swap partial amounts ===")

    # Try to swap 10 units of any common item
    common_items = ["IronIngot", "SteelPlate", "InteriorPlate", "ConstructionComponent"]

    swapped = False
    for subtype in common_items:
        items_1 = container1.find_items_by_subtype(subtype)
        items_2 = container2.find_items_by_subtype(subtype)

        if items_1 and items_2 and items_1[0].amount >= 10 and items_2[0].amount >= 10:
            print(f"Swapping 10 units of {subtype}...")

            # Move 10 from container1 to container2
            container1.move_subtype(container2.device_id, subtype, amount=10)
            time.sleep(0.5)

            # Move 10 from container2 to container1
            container2.move_subtype(container1.device_id, subtype, amount=10)
            time.sleep(0.5)

            swapped = True
            break

    if not swapped:
        print("No suitable items found for partial amount swapping.")

    # Final state
    final_items1 = container1.items()
    final_items2 = container2.items()

    print("\nFinal state:")
    print(f"  Container 1: {format_items(final_items1)}")
    print(f"  Container 2: {format_items(final_items2)}")

    print("\nNote: This example demonstrates swapping items between containers.")
    print("To 'swap items within the same container', you would need to use")
    print("a temporary container as an intermediary for the transfer.")


def format_items(items: List[Item]) -> str:
    if not items:
        return "empty"
    return ", ".join(f"{it.amount} x {it.display_name or it.subtype or '?'}"
                    for it in items)


if __name__ == "__main__":
    main()
