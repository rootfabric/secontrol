from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from secontrol.devices.container_device import ContainerDevice, Item
from secontrol.common import resolve_owner_id, prepare_grid



def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    grid = prepare_grid()

    # Find container devices
    containers = grid.find_devices_by_type(ContainerDevice)
    print(f"Found {len(containers)} container device(s):")

    # Track last printed items per container id
    last_items: Dict[str, Tuple[Tuple[str, float], ...]] = {}

    def _items_signature(items: List[Item]) -> Tuple[Tuple[str, float], ...]:
        sig: List[Tuple[str, float]] = []
        for it in items:
            name = (it.display_name or it.subtype or "").strip()
            sig.append((name, float(it.amount)))
        return tuple(sig)

    def _items_payload(items: List[Item]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for it in items:
            entry = {
                "type": it.type,
                "subtype": it.subtype,
                "amount": float(it.amount),
            }
            if it.display_name:
                entry["displayName"] = it.display_name
            result.append(entry)
        return result

    for i, container in enumerate(containers, 1):
        # Print initial snapshot from the device
        init_items = container.items()
        last_items[str(container.device_id)] = _items_signature(init_items)
        label = f"{container.name or 'Container'} (ID: {container.device_id})"
        print(f"{label}: {_items_payload(init_items)}")

        def _on_telemetry(dev: ContainerDevice, telemetry: Dict[str, Any], source_event: str) -> None:
            items_now = dev.items()
            sig = _items_signature(items_now)
            cid = str(dev.device_id)
            if last_items.get(cid) == sig:
                return
            last_items[cid] = sig
            label_now = f"{dev.name or 'Container'} (ID: {dev.device_id})"
            print(f"{label_now}: {_items_payload(items_now)}")

        container.on("telemetry", _on_telemetry)

    if not containers:
        return

    # Keep the process alive to receive updates
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass



if __name__ == "__main__":
    main()
