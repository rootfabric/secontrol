from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from secontrol.devices.container_device import ContainerDevice
from secontrol.common import resolve_owner_id, prepare_grid


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
                **(
                    {"displayName": it["displayName"]}
                    if it.get("displayName")
                    else {}
                ),
            }
        )
    return out


def _items_signature(items: List[Dict[str, Any]]) -> Tuple[Tuple[str, float], ...]:
    # Stable signature to detect changes without noisy formatting differences
    sig: List[Tuple[str, float]] = []
    for it in items:
        name = str(it.get("displayName") or it.get("subtype") or "").strip()
        amount = float(it.get("amount") or 0.0)
        sig.append((name, amount))
    return tuple(sig)


def _format_items(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "[]"
    parts = []
    for it in items:
        name = it.get("displayName") or it.get("subtype") or "?"
        amount = it.get("amount")
        parts.append(f"{amount} x {name}")
    return "[" + ", ".join(parts) + "]"


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    client, grid = prepare_grid()

    # Find container devices
    containers = grid.find_devices_by_type(ContainerDevice)
    print(f"Found {len(containers)} container device(s):")

    # Track last printed items per container id
    last_items: Dict[str, Tuple[Tuple[str, float], ...]] = {}

    def _setup_container_monitor(device: ContainerDevice, index: int) -> None:
        print(f"  {index}. {device.name} (ID: {device.device_id})")

        # Print initial items if available from device's telemetry
        initial_items = device.items()
        if initial_items:
            last_items[device.device_id] = _items_signature(initial_items)
            print(_format_items(initial_items))
        else:
            print("Loading...")

        def _on_update(_key: str, payload: Any, event: str) -> None:
            if payload is None or event == "del":
                items_now: List[Dict[str, Any]] = []
            else:
                # payload may be JSON string or dict; get_json in subscriber decodes when possible
                data = payload if isinstance(payload, dict) else {}
                items_now = _normalize_items(data)

            sig = _items_signature(items_now)
            # Print if changed, or if we haven't printed initial yet (i.e., device_id not in last_items)
            if device.device_id not in last_items or last_items.get(device.device_id) != sig:
                last_items[device.device_id] = sig
                print(_format_items(items_now))

        client.subscribe_to_key(device.telemetry_key, _on_update)

    for i, container in enumerate(containers, 1):
        _setup_container_monitor(container, i)

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
