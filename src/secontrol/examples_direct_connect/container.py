from __future__ import annotations

import time

from secontrol.devices.container_device import ContainerDevice
from secontrol.common import resolve_owner_id, prepare_grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    client, grid = prepare_grid()

    containers = grid.find_devices_by_type(ContainerDevice)
    print(f"Found {len(containers)} container device(s):")

    last_items = {}

    for i, container in enumerate(containers, 1):
        print(f"{i}. {container.name or 'Container'} (ID: {container.device_id})")

        init_items = container.items()
        if init_items:
            last_items[str(container.device_id)] = ContainerDevice._items_signature(init_items)
            print(ContainerDevice._format_items(init_items))
        else:
            print("Loading...")

        def _on_update(_key: str, payload, event: str, cont=container) -> None:
            items_now = ContainerDevice._normalize_items(payload if isinstance(payload, dict) and event != "del" else None)
            sig = ContainerDevice._items_signature(items_now)
            cid = str(cont.device_id)
            if last_items.get(cid) != sig:
                last_items[cid] = sig
                print(ContainerDevice._format_items(items_now))

        client.subscribe_to_key(container.telemetry_key, _on_update)

    if not containers:
        return

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
