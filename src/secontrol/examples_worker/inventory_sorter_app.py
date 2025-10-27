"""Inventory sorter application in the App(start/step) format.

The script connects to the player's grid, discovers cargo containers and
re-distributes items into tagged containers based on resource tags.

Usage (after installing dependencies and configuring environment variables):

    python -m secontrol.examples_worker.inventory_sorter_app

The sorter recognises container tags both in block names (square brackets) and
in the custom data (``tags: iron, ingot``). Tags are matched against item
subtype/type identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

from secontrol.base_device import Grid
from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice


_TAG_IN_NAME = re.compile(r"\[(?P<tags>[^\[\]]+)\]")


def _normalize_tag(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", text).strip("_")
    return cleaned.lower()


def _split_tags(text: str) -> Iterable[str]:
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


def _extract_tags_from_custom_data(device: ContainerDevice) -> Set[str]:
    data = device.custom_data()
    if not data:
        return set()
    tags: Set[str] = set()
    for raw_line in data.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip().lower() not in {"tags", "tag", "labels"}:
                continue
            tags.update(_split_tags(value))
        else:
            tags.update(_split_tags(line))
    return tags


def _derive_item_tags(item: Dict[str, object]) -> Set[str]:
    tags: Set[str] = set()
    subtype = item.get("subtype")
    if isinstance(subtype, str):
        tags.add(_normalize_tag(subtype))
    type_id = item.get("type")
    if isinstance(type_id, str):
        tags.add(_normalize_tag(type_id))
        if type_id.startswith("MyObjectBuilder_"):
            tail = type_id.removeprefix("MyObjectBuilder_")
            tags.add(_normalize_tag(tail))
    display = item.get("displayName")
    if isinstance(display, str):
        tags.add(_normalize_tag(display))
    # Derive generic categories (ingot, ore, component, ammo, tool, gas)
    for candidate in list(tags):
        if candidate.endswith("ingot"):
            tags.add("ingot")
        if candidate.endswith("ore"):
            tags.add("ore")
        if candidate.endswith("component"):
            tags.add("component")
        if candidate.endswith("ammo") or candidate.endswith("magazine"):
            tags.add("ammo")
        if candidate.endswith("tool"):
            tags.add("tool")
        if candidate.endswith("bottle") or candidate.endswith("gas"):
            tags.add("gas")
    return tags


@dataclass
class TaggedContainer:
    device: ContainerDevice
    tags: Set[str]


class App:
    def __init__(self, *, refresh_every: int = 10, max_transfers_per_step: int = 20):
        self.counter = 0
        self._grid: Optional[Grid] = None
        self._refresh_every = max(1, int(refresh_every))
        self._max_transfers = max(1, int(max_transfers_per_step))
        self._containers: List[TaggedContainer] = []
        self._tag_index: Dict[str, List[ContainerDevice]] = {}

    def start(self):
        self._grid = prepare_grid()
        self._refresh_containers()
        print(
            "Sorter started: %d containers, %d tagged"
            % (len(self._containers), sum(1 for c in self._containers if c.tags))
        )

    def step(self):
        if not self._grid:
            raise RuntimeError("Grid is not prepared. Call start() first.")
        self.counter += 1
        if self.counter % self._refresh_every == 1:
            self._refresh_containers()
        transfers = 0
        for container in self._containers:
            items = container.device.items()
            if not items:
                continue
            container_tags = container.tags
            for item in items:
                desired_tags = _derive_item_tags(item)
                # Skip if container already matches desired tags
                if desired_tags & container_tags:
                    continue
                destination = self._select_destination(container.device, desired_tags)
                if not destination:
                    continue
                subtype = item.get("subtype")
                if not isinstance(subtype, str) or not subtype:
                    continue
                try:
                    container.device.move_subtype(destination.device_id, subtype)
                    transfers += 1
                except Exception as exc:  # pragma: no cover - safety net for runtime issues
                    print(
                        f"Failed to move {subtype} from {container.device.name}"
                        f" to {destination.name}: {exc}"
                    )
                if transfers >= self._max_transfers:
                    break
            if transfers >= self._max_transfers:
                break
        if transfers:
            print(f"Step {self.counter}: transferred {transfers} stacks")
        else:
            print(f"Step {self.counter}: nothing to transfer")

    def close(self):
        if self._grid:
            try:
                close(self._grid)
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    # ------------------------------------------------------------------
    def _refresh_containers(self) -> None:
        if not self._grid:
            return
        containers: List[ContainerDevice] = []
        finder = getattr(self._grid, "find_devices_by_type", None)
        if callable(finder):
            try:
                containers = list(finder("container"))
            except Exception:
                containers = []
        if not containers:
            containers = [
                device
                for device in self._grid.devices.values()
                if isinstance(device, ContainerDevice)
            ]
        tagged_containers: List[TaggedContainer] = []
        for device in containers:
            tags = _extract_tags_from_name(device.name)
            tags.update(_extract_tags_from_custom_data(device))
            tagged_containers.append(TaggedContainer(device=device, tags=tags))
        tagged_containers.sort(key=lambda c: (c.device.name or "", str(c.device.device_id)))
        self._containers = tagged_containers
        tag_index: Dict[str, List[ContainerDevice]] = {}
        for container in tagged_containers:
            for tag in container.tags:
                tag_index.setdefault(tag, []).append(container.device)
        self._tag_index = tag_index

    def _select_destination(
        self, source: ContainerDevice, desired_tags: Set[str]
    ) -> Optional[ContainerDevice]:
        for tag in desired_tags:
            candidates = self._tag_index.get(tag)
            if not candidates:
                continue
            for candidate in candidates:
                if candidate.device_id == source.device_id:
                    continue
                return candidate
        return None


if __name__ == "__main__":
    app = App()
    app.start()
    try:
        while True:
            app.step()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
