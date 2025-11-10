"""Inventory sorter application in the App(start/step) format.

The script connects to the player's grid, discovers cargo containers and
re-distributes items into tagged containers based on resource tags.
Additionally, it collects items from the output inventories of assemblers,
refineries, and ship grinders (cleaners), without interfering with input inventories.

Usage (after installing dependencies and configuring environment variables):

    python -m secontrol.examples_worker.inventory_sorter_app

The sorter recognises container tags both in block names (square brackets) and
in the custom data (``tags: iron, ingot``). Tags are matched against item
subtype/type identifiers.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Set

from secontrol.devices.container_device import ContainerDevice, Item
from secontrol.item_types import ORE, INGOT, COMPONENT, TOOL, AMMO, is_ore, is_ingot, is_component, is_tool, is_ammo
from secontrol.common import close, prepare_grid
from secontrol.base_device import Grid




def _normalize_tag(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", text).strip("_")
    return cleaned.lower()


def _derive_item_tags(item: Item) -> Set[str]:
    tags: Set[str] = set()

    # Добавляем базовые теги из subtype, type и display_name
    subtype = item.subtype
    if isinstance(subtype, str):
        tags.add(_normalize_tag(subtype))

    type_id = item.type
    if isinstance(type_id, str):
        tags.add(_normalize_tag(type_id))
        if type_id.startswith("MyObjectBuilder_"):
            tail = type_id.removeprefix("MyObjectBuilder_")
            tags.add(_normalize_tag(tail))

    display = item.display_name
    if isinstance(display, str):
        tags.add(_normalize_tag(display))

    # Используем новые категории предметов для точного определения типов
    if is_ore(item):
        tags.add("ore")
    if is_ingot(item):
        tags.add("ingot")
    if is_component(item):
        tags.add("component")
    if is_tool(item):
        tags.add("tool")
    if is_ammo(item):
        tags.add("ammo")

    # Дополнительные категории на основе анализа строк (для совместимости)
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

    # Add tool tag for physical gun objects (welders, grinders, drills, etc.)
    if "physicalgunobject" in tags:
        tags.add("tool")

    return tags


class App:
    def __init__(self, grid=None, grid_id=None, *, refresh_every: int = 10, max_transfers_per_step: int = 20):
        self.counter = 0
        self._grids: List[Grid] = []
        self._grid = grid  # переданный извне grid объект
        self._grid_id = self._grid.grid_id
        self._refresh_every = max(1, int(refresh_every))
        self._max_transfers = max(1, int(max_transfers_per_step))
        self._containers: List[ContainerDevice] = []
        self._tag_index: Dict[str, List[ContainerDevice]] = {}
        self._production_devices: List[ContainerDevice] = []

    def start(self):
        from secontrol.common import prepare_grid

        if self._grid:
            # Использовать переданный извне grid объект/данные
            if isinstance(self._grid, dict):
                # Словарь grid_id -> grid_name, создать Grid объекты
                self._grids = []
                for grid_id, grid_name in self._grid.items():
                    try:
                        grid = prepare_grid(grid_id)
                        self._grids.append(grid)
                    except Exception as e:
                        print(f"Failed to create grid {grid_id}: {e}")
                print(f"Started with {len(self._grids)} grids from dict")
            elif isinstance(self._grid, (list, tuple)):
                # Список/кортеж Grid объектов или (grid_id, grid_name) или просто grid_id
                self._grids = []
                for item in self._grid:
                    if hasattr(item, 'grid_id'):
                        # Это Grid объект
                        self._grids.append(item)
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        # tuple (grid_id, grid_name), создать Grid
                        try:
                            grid = prepare_grid(str(item[0]))
                            self._grids.append(grid)
                        except Exception as e:
                            print(f"Failed to create grid {item[0]}: {e}")
                    elif isinstance(item, str):
                        # Просто grid_id как строка
                        try:
                            grid = prepare_grid(str(item))
                            self._grids.append(grid)
                        except Exception as e:
                            print(f"Failed to create grid {item}: {e}")
                    else:
                        print(f"Unknown grid item format: {item}")
                print(f"Started with {len(self._grids)} external grids")
            elif isinstance(self._grid, str):
                # Передан просто grid_id как строка
                try:
                    grid = prepare_grid(self._grid)
                    self._grids = [grid]
                except Exception as e:
                    print(f"Failed to create grid {self._grid}: {e}")
                    self._grids = []
                print(f"Started with grid_id string: {self._grid}")
            else:
                # Один grid объект
                self._grids = [self._grid]
                print(f"Started with external grid: {self._grid.grid_id}")
        elif self._grid_id:
            # Создать grid с переданным ID
            grid = prepare_grid(self._grid_id)
            self._grids = [grid]
            print(f"Started with grid ID: {self._grid_id}")
        else:
            # Автоматический выбор грида (fallback)
            grid = prepare_grid()
            self._grids = [grid]
            print(f"Started with auto-selected grid: {grid.grid_id}")

        self._refresh_containers()
        print(
            "Sorter started: %d containers, %d tagged"
            % (len(self._containers), sum(1 for c in self._containers if c.tags))
        )

    def step(self):
        if not self._grids:
            raise RuntimeError("Grids are not prepared. Call start() first.")
        self.counter += 1
        if self.counter % self._refresh_every == 1:
            self._refresh_containers()
        transfers = 0
        for container in self._containers:
            items = container.items()
            if not items:
                continue
            container_tags = container.tags
            for item in items:
                desired_tags = _derive_item_tags(item)
                # Skip if container already matches desired tags
                if desired_tags & container_tags:
                    continue
                destination = self._select_destination(container, desired_tags)
                if not destination:
                    continue
                subtype = item.subtype
                if not isinstance(subtype, str) or not subtype:
                    continue
                try:
                    container.move_subtype(destination.device_id, subtype)
                    transfers += 1
                    print(f"SORT: Moved {subtype} from {container.name} ({container.device_type}) to {destination.name} ({destination.device_type})")
                except Exception as exc:  # pragma: no cover - safety net for runtime issues
                    print(
                        f"Failed to move {subtype} from {container.name}"
                        f" to {destination.name}: {exc}"
                    )
                if transfers >= self._max_transfers:
                    break
            if transfers >= self._max_transfers:
                break
        # Collect from production device outputs
        for device in self._production_devices:
            print(f"COLLECT: Checking {device.name} ({device.device_type})")
            inventories = device.inventories()
            print(f"COLLECT: {device.name} has {len(inventories)} inventories")
            for inv in inventories:
                print(f"  Inventory: {inv.name} - {len(inv.items)} items")
                for item in inv.items:
                    print(f"    {item.display_name} ({item.subtype}) x{item.amount}")
            output_inv = device.output_inventory()
            if not output_inv:
                print(f"COLLECT: No output inventory for {device.name} ({device.device_type})")
                continue
            print(f"COLLECT: Output inventory is '{output_inv.name}' with {len(output_inv.items)} items")
            items = output_inv.items
            if not items:
                print(f"COLLECT: No items in output inventory for {device.name} ({device.device_type})")
                continue
            print(f"COLLECT: Found {len(items)} items in output inventory of {device.name} ({device.device_type})")
            for item in items:
                desired_tags = _derive_item_tags(item)
                destination = self._select_destination(device, desired_tags)
                if not destination:
                    continue
                subtype = item.subtype
                if not isinstance(subtype, str) or not subtype:
                    continue
                try:
                    device.move_subtype(destination.device_id, subtype, source_inventory=output_inv)
                    transfers += 1
                    print(f"COLLECT: Moved {subtype} from {device.name} ({device.device_type}) output to {destination.name} ({destination.device_type})")
                except Exception as exc:  # pragma: no cover - safety net for runtime issues
                    print(
                        f"Failed to move {subtype} from {device.name} output"
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
        for grid in self._grids:
            try:
                close(grid)
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    # ------------------------------------------------------------------
    def _refresh_containers(self) -> None:
        if not self._grids:
            return
        all_containers: List[ContainerDevice] = []
        production_devices: List[ContainerDevice] = []
        for grid in self._grids:
            # Use find_devices_containers for all container-like devices
            containers = grid.find_devices_containers()
            all_containers.extend(containers)

            # Collect production devices: assemblers, refineries, ship grinders, reactors
            assemblers = grid.find_devices_by_type("assembler")
            refineries = grid.find_devices_by_type("refinery")
            grinders = grid.find_devices_by_type("ship_grinder")
            reactors = grid.find_devices_by_type("reactor")
            production_devices.extend(assemblers)
            production_devices.extend(refineries)
            production_devices.extend(grinders)
            production_devices.extend(reactors)

        # Exclude production devices from containers to avoid sorting from their inputs
        production_device_ids = {dev.device_id for dev in production_devices}
        cargo_containers = [dev for dev in all_containers if dev.device_id not in production_device_ids]
        print(f"All containers found:")
        for dev in all_containers:
            print(f"  Container: {dev.name} ({dev.device_type}) - {'EXCLUDED' if dev.device_id in production_device_ids else 'CARGO'}")

        # Sort containers by name and id
        cargo_containers.sort(key=lambda c: (c.name or "", str(c.device_id)))
        self._containers = cargo_containers
        self._production_devices = production_devices
        print(f"Found {len(all_containers)} total containers, {len(cargo_containers)} cargo containers, {len(production_devices)} production devices")
        for dev in production_devices:
            print(f"  Production: {dev.name} ({dev.device_type})")
        # Build tag index from container.tags (updated automatically via telemetry)
        tag_index: Dict[str, List[ContainerDevice]] = {}
        for container in cargo_containers:
            for tag in container.tags:
                tag_index.setdefault(tag, []).append(container)
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
        # Fallback for tools: also consider ore containers
        if "tool" in desired_tags:
            candidates = self._tag_index.get("ore")
            if candidates:
                for candidate in candidates:
                    if candidate.device_id == source.device_id:
                        continue
                    return candidate
        return None


if __name__ == "__main__":

    grid = prepare_grid()
    app = App(grid)

    app.start()
    try:
        while True:
            app.step()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
