from __future__ import annotations

import time
from typing import Dict, Tuple, Any, List

from secontrol.devices.container_device import ContainerDevice, Item
from secontrol.common import resolve_owner_id, prepare_grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    grid = prepare_grid()

    containers = grid.find_devices_by_type(ContainerDevice)
    print(f"Found {len(containers)} container device(s):")

    # Remember last printed signature per device
    last_sig: Dict[str, Tuple[Tuple[str, float], ...]] = {}

    for i, container in enumerate(containers, 1):
        print(f"{i}. {container.name or 'Container'} (ID: {container.device_id}) {container.capacity()}")

        # Initial snapshot from device cache
        init_items = container.items()
        sig = ContainerDevice._items_signature(init_items)
        last_sig[str(container.device_id)] = sig

        if init_items:
            pretty = ", ".join(f"{it.amount} x {it.display_name or it.subtype or '?'}" for it in init_items)
            print(f"[init] [{container.device_id}] [{container.name or ''}] [{pretty}]")
        else:
            print(f"[init] [{container.device_id}] loading...")

        # Subscribe to device-level telemetry (single, internal subscription)
        def _on_telemetry(dev, telemetry: Dict[str, Any], source_event: str) -> None:
            # dev — это конкретный девайс, который сгенерил событие.
            # Нам не нужно тянуть внешнюю переменную container.

            if not isinstance(dev, ContainerDevice):
                return  # безопасно игнорируем не-контейнеры, на всякий случай

            cid = str(dev.device_id)

            # текущее содержимое (ContainerDevice.items() уже кэширует items из handle_telemetry)
            items_now = dev.items()
            sig_now = ContainerDevice._items_signature(items_now)

            if last_sig.get(cid) != sig_now:
                last_sig[cid] = sig_now

                if items_now:
                    pretty_now = ", ".join(
                        f"{it.amount} x {it.display_name or it.subtype or '?'}"
                        for it in items_now
                    )
                else:
                    pretty_now = ""

                print(f"[update] [{cid}] [{dev.name or ''}] [{pretty_now}]")


        container.on("telemetry", _on_telemetry)

    if not containers:
        return

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
