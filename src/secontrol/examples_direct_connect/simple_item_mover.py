from __future__ import annotations

import re
import threading
import time
from typing import Dict, Tuple, Any, List, Set, Optional

from secontrol.base_device import Grid
from secontrol.devices.container_device import ContainerDevice, Item
from secontrol.common import resolve_owner_id, resolve_player_id, _is_subgrid
from secontrol.redis_client import RedisEventClient

_TAG_IN_NAME = re.compile(r"\[(?P<tags>[^\[\]]+)\]")


def _normalize_tag(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", text).strip("_")
    return cleaned.lower()


def _split_tags(text: str) -> List[str]:
    for raw in re.split(r"[\s,;:/|]+", text):
        normalized = _normalize_tag(raw)
        if normalized:
            yield normalized


def _extract_tags_from_name(name: Optional[str]) -> Set[str]:
    tags: Set[str] = set()
    if not name:
        return tags
    for match in _TAG_IN_NAME.finditer(name):
        tags.update(_split_tags(match.group("tags")))
    return tags


def run_for_grid(client: RedisEventClient, owner_id: str, player_id: str, grid_info: Dict[str, Any]) -> None:
    grid_id = str(grid_info.get('id'))
    grid_name = grid_info.get('name', 'unnamed')
    print(f"Starting mover for grid {grid_id} ({grid_name})")

    grid = Grid(client, owner_id, grid_id, player_id)

    containers = list(grid.find_devices_by_type(ContainerDevice))
    print(f"Found {len(containers)} container device(s) on grid {grid_name}:")

    if len(containers) < 2:
        print(f"Skipping grid {grid_name}: Need at least 2 containers.")
        return

    # Sort containers by device_id for consistency
    containers.sort(key=lambda c: c.device_id)

    def format_items(items):
        if not items:
            return 'none'
        return ', '.join(f'{it.amount} x {it.display_name or it.subtype or "?"}' for it in items)

    for i, c in enumerate(containers, 1):
        items = c.items()
        print(f"  {i}. {c.name or 'Container'} (ID: {c.device_id}): {format_items(items)}")

    # Cyclic transfer logic: move all to the "current target" which is the first empty one, then cycle
    current_target_idx = 0
    last_signatures = [ContainerDevice._items_signature(c.items()) for c in containers]

    def get_current_target_idx():
        # Find first empty container, starting from current
        for i in range(len(containers)):
            idx = (current_target_idx + i) % len(containers)
            if not containers[idx].items():
                return idx
        # If none empty, find first empty overall, or stay at current
        for i, c in enumerate(containers):
            if not c.items():
                return i
        return current_target_idx

    def update_target_if_needed():
        nonlocal current_target_idx
        target_items = containers[current_target_idx].items()
        if target_items:
            # print(f"[{grid_name}] Target {containers[current_target_idx].name} now has items, switching to next empty.")
            current_target_idx = get_current_target_idx()
            # print(f"[{grid_name}] New target: {containers[current_target_idx].name}")

    def move_all_to_target(target_idx):
        target = containers[target_idx]
        moved_any = False
        for i, source in enumerate(containers):
            if i == target_idx:
                continue
            items = source.items()
            batch = []
            for item in items:
                subtype = item.subtype
                if not subtype:
                    continue
                batch.append({"subtype": subtype})
            if batch:
                try:
                    source.move_items(target.device_id, batch)
                    # print(f"[{grid_name}] Moved batch from {source.name or 'Container'} to {target.name or 'Container'}")
                    # Update telemetry for source and target to speed up info

                    time.sleep(0.5)
                    # source.send_command({"cmd": "update"})
                    # target.send_command({"cmd": "update"})

                    moved_any = True
                except Exception as exc:
                    print(f"[{grid_name}] Failed to move batch from {source.name or 'Container'}: {exc}")
        return moved_any

    # On any telemetry change, check and move
    def _on_telemetry(dev, telemetry: Dict[str, Any], source_event: str) -> None:
        dev_cid = str(dev.device_id)
        dev_idx = next((i for i, c in enumerate(containers) if str(c.device_id) == dev_cid), -1)
        if dev_idx == -1:
            return

        items_now = dev.items()
        sig_now = ContainerDevice._items_signature(items_now)

        if last_signatures[dev_idx] == sig_now:
            return
        last_signatures[dev_idx] = sig_now

        # print(f"[{grid_name} update] {dev.name or 'Container'} changed: {format_items(items_now) if items_now else 'empty'}")

        # Update target if current has items now
        update_target_if_needed()

        # Try to move all to current target
        moved = move_all_to_target(current_target_idx)
        if moved:
            # After move, update target if now has items
            update_target_if_needed()

    # Subscribe to all containers
    for c in containers:
        c.on("telemetry", _on_telemetry)

    # Initial move
    update_target_if_needed()  # Set initial target
    move_all_to_target(current_target_idx)
    update_target_if_needed()

    print(f"Cyclic item mover for grid {grid_name} started. Monitoring for changes...")

    try:
        while True:
            time.sleep(0.5)
            for i, source in enumerate(containers):
                source.send_command({"cmd": "update"})
            # Also update the current target to detect changes
            containers[current_target_idx].send_command({"cmd": "update"})
    except KeyboardInterrupt:
        pass


def main() -> None:
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)
    print(f"Owner ID: {owner_id}")

    client = RedisEventClient()

    try:
        grids = client.list_grids(owner_id)
        if not grids:
            print("No grids found.")
            return

        # Filter non-subgrids
        non_subgrids = [g for g in grids if not _is_subgrid(g)]
        print(f"Found {len(non_subgrids)} main grids.")

        threads = []
        for grid_info in non_subgrids:
            print(grid_info)
            # if grid_info['id']=='126722876679139690':
            # if grid_info['id']=='79921505162482780':

            t = threading.Thread(target=run_for_grid, args=(client, owner_id, player_id, grid_info))
            threads.append(t)
            t.start()

            # if len(threads)>2:
            #     break



        # Wait for all threads
        for t in threads:
            t.join()

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
