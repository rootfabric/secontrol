from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from secontrol.devices.container_device import ContainerDevice
from secontrol.common import resolve_owner_id, prepare_grid



def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    client, grid = prepare_grid()

    # Find container devices
    containers = grid.find_devices_by_type(ContainerDevice)
    print(f"Found {len(containers)} container device(s):")

    # Track last printed items per container id
    last_items: Dict[str, Tuple[Tuple[str, float], ...]] = {}

    def _normalize_items(payload: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append(
                {
                    "type": it.get("type") or it.get("Type") or "",
                    "subtype": it.get("subtype") or it.get("subType") or it.get("name") or "",
                    "amount": float(it.get("amount", 0.0)),
                    **({"displayName": it["displayName"]} if it.get("displayName") else {}),
                }
            )
        return out

    def _items_signature(items: List[Dict[str, Any]]) -> Tuple[Tuple[str, float], ...]:
        sig: List[Tuple[str, float]] = []
        for it in items:
            name = str(it.get("displayName") or it.get("subtype") or "").strip()
            amount = float(it.get("amount") or 0.0)
            sig.append((name, amount))
        return tuple(sig)

    for i, container in enumerate(containers, 1):
        # Print initial snapshot from the device
        init_items = container.items()
        last_items[str(container.device_id)] = _items_signature(init_items)
        label = f"{container.name or 'Container'} (ID: {container.device_id})"
        print(f"{label}: {init_items}")

        # Subscribe to device telemetry changes and print when items change
        def _on_update(_key: str, payload: Any, event: str, cont=container) -> None:
            if payload is None or event == "del":
                items_now: List[Dict[str, Any]] = []
            else:
                data = payload if isinstance(payload, dict) else {}
                items_now = _normalize_items(data)

            sig = _items_signature(items_now)
            cid = str(cont.device_id)
            if last_items.get(cid) != sig:
                last_items[cid] = sig
                label_now = f"{cont.name or 'Container'} (ID: {cont.device_id})"
                print(f"{label_now}: {items_now}")

        client.subscribe_to_key(container.telemetry_key, _on_update)

    if not containers:
        return

    # Keep the process alive to receive updates
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
        print(container.telemetry)



if __name__ == "__main__":
    main()
