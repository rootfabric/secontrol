"""
Refinery priority manager.

Задача:
- смотреть все контейнеры на гриде;
- выбрать ТОЛЬКО реальные руды (как в твоём тестовом скрипте);
- взять максимум 3 по приоритету;
- если во входящем refinery их нет или порядок сбился — подложить;
- НИЧЕГО не делать с конвейерами, пусть игра сама тянет/гонит.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from secontrol.base_device import Grid
from secontrol.common import close, resolve_owner_id, resolve_player_id
from secontrol.redis_client import RedisEventClient
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice

# приоритеты (как у тебя)
PRIORITY_ORES = [
    "Platinum",
    "Uranium",
    "Gold",
    "Silver",
    "Cobalt",
    "Nickel",
    "Magnesium",
    "Iron",
    "Silicon",
    "Stone",
]

ORE_TO_BLUEPRINT = {
    "Stone": "StoneOreToIngot",
    "Iron": "IronOreToIngot",
    "Nickel": "NickelOreToIngot",
    "Cobalt": "CobaltOreToIngot",
    "Magnesium": "MagnesiumOreToIngot",
    "Silicon": "SiliconOreToIngot",
    "Silver": "SilverOreToIngot",
    "Gold": "GoldOreToIngot",
    "Platinum": "PlatinumOreToIngot",
    "Uranium": "UraniumOreToIngot",
}

MAX_INPUT_ORES = 3
MAX_QUEUE_SIZE = 10
REFRESH_EVERY = 30


class App:
    def __init__(self, grid=None, grid_id=None, *, refresh_every: int = REFRESH_EVERY, max_queue_size: int = MAX_QUEUE_SIZE):
        self.counter = 0
        self._grids: List[Grid] = []
        self._grid = grid  # переданный извне grid объект
        self._grid_id = grid_id  # переданный извне grid_id
        self._refresh_every = max(1, int(refresh_every))
        self._max_queue_size = max(1, int(max_queue_size))
        self._refineries: List[RefineryDevice] = []
        self._source_containers: List[ContainerDevice] = []
        self._priority_ores = PRIORITY_ORES.copy()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
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

        self._refresh_devices()

        # ВАЖНО: конвейеры не трогаем
        print(
            f"Refinery Priority Manager started: {len(self._refineries)} refineries, "
            f"{len(self._source_containers)} source containers"
        )
        print(f"Priority order: {', '.join(self._priority_ores)}")

    def step(self):
        if not self._grids:
            raise RuntimeError("Grids are not prepared. Call start() first.")

        self.counter += 1

        if self.counter % self._refresh_every == 1:
            self._refresh_devices()

        total_actions = 0
        for r in self._refineries:
            total_actions += self._manage_refinery_queue(r)

        if total_actions > 0:
            print(f"Step {self.counter}: performed {total_actions} actions")
        else:
            print(f"Step {self.counter}: queues are optimized")

    def close(self):
        for g in self._grids:
            try:
                close(g)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    def _refresh_devices(self) -> None:
        if not self._grids:
            return

        all_ref: List[RefineryDevice] = []
        all_src: List[ContainerDevice] = []

        for grid in self._grids:
            finder = getattr(grid, "find_devices_by_type", None)

            # refinery
            ref_list: List[RefineryDevice] = []
            if callable(finder):
                try:
                    ref_list = list(finder("refinery"))
                except Exception:
                    ref_list = []
            if not ref_list:
                ref_list = [d for d in grid.devices.values() if isinstance(d, RefineryDevice)]
            all_ref.extend(ref_list)

            # containers
            cont_list: List[ContainerDevice] = []
            if callable(finder):
                try:
                    cont_list = list(finder("container"))
                except Exception:
                    cont_list = []
            if not cont_list:
                cont_list = [d for d in grid.devices.values() if isinstance(d, ContainerDevice)]

            for c in cont_list:
                if self._is_source_container(c):
                    all_src.append(c)

        self._refineries = all_ref
        self._source_containers = all_src

    def _is_source_container(self, container: ContainerDevice) -> bool:
        name = (container.name or "").lower()
        if "[source]" in name or "[input]" in name or "[ore]" in name:
            return True
        cd = container.custom_data()
        if cd:
            cd = cd.lower()
            if "source" in cd or "input" in cd or "ore" in cd:
                return True
        return False

    # ------------------------------------------------------------------
    # core
    # ------------------------------------------------------------------
    def _manage_refinery_queue(self, refinery: RefineryDevice) -> int:
        actions = 0

        desired_queue = self._build_desired_queue()
        # Т.к. мы хотим «пусть 3 вида лежат и всё», прерывание особо не нужно
        should_interrupt = self._should_interrupt_current_processing(refinery, desired_queue)
        current_queue = refinery.queue()

        print(
            f"Refinery {refinery.name}: interrupt={should_interrupt}, "
            f"current_len={len(current_queue)}, desired_len={len(desired_queue)}"
        )

        arranged = self._are_resources_properly_arranged(refinery, desired_queue)
        print(f"Refinery {refinery.name}: resources arranged={arranged}")

        queues_equal = self._queues_equal(current_queue, desired_queue)
        print(f"Refinery {refinery.name}: queues_equal={queues_equal}")

        if should_interrupt or not queues_equal or not arranged:
            keep_ores = [x["ore_type"] for x in desired_queue]

            # мягкая чистка — убираем только лишнее, не выносим уран/платину/золото
            actions += self._clear_refinery_inventory_soft(refinery, keep_ores, max_keep=MAX_INPUT_ORES)

            # если очередь не совпала — перезапишем
            if not queues_equal or should_interrupt:
                if current_queue:
                    refinery.clear_queue()
                    actions += 1
                    time.sleep(0.05)
                for item in desired_queue:
                    refinery.add_queue_item(item["blueprint"], item["amount"])
                    actions += 1

            # и теперь просто ПОДЛОЖИМ в refinery — как в твоём простом скрипте
            self._arrange_resources_in_queue_order(refinery, desired_queue)
            actions += 1

        return actions

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _normalize_ore_name(self, subtype: str) -> str:
        if not subtype:
            return ""
        s = subtype.strip()
        if s.endswith(" Ore"):
            s = s[:-4]
        if s.endswith("Ore"):
            s = s[:-3]
        return s

    def _is_real_ore(self, item) -> bool:
        """
        Как в твоём тестовом скрипте: двигаем только РУДУ.
        """
        subtype = (item.subtype or "").strip()
        disp = (item.display_name or "").lower()

        # если в названии явно написано "ore" или "руда" — это то, что надо
        if "ore" in disp or "руда" in disp:
            return True

        # иногда имя пустое — тогда смотрим subtype
        # и отсекаем ingot'ы
        if subtype in self._priority_ores and "ingot" not in subtype.lower() and "слит" not in disp:
            return True

        return False

    def _get_available_resources(self) -> Dict[str, float]:
        """
        Берём только из контейнеров и только те айтемы, которые точно руда.
        """
        available: Dict[str, float] = {}

        for grid in self._grids:
            for dev in grid.devices.values():
                if not isinstance(dev, ContainerDevice):
                    continue
                try:
                    items = dev.items()
                except Exception:
                    continue

                for it in items:
                    if not self._is_real_ore(it):
                        continue
                    norm = self._normalize_ore_name(it.subtype or "")
                    if norm in self._priority_ores:
                        available.setdefault(norm, 0.0)
                        available[norm] += float(it.amount)
                        print(f"  {dev.name}: +{it.amount} {norm} (ORE)")

        print(f"Available resources: {available}")
        return available

    def _build_desired_queue(self) -> List[Dict]:
        available = self._get_available_resources()
        desired: List[Dict] = []

        for ore_type in self._priority_ores:
            if ore_type in available and available[ore_type] > 0:
                bp = ORE_TO_BLUEPRINT.get(ore_type)
                if not bp:
                    continue
                amount = min(available[ore_type], 1000)
                desired.append(
                    {"blueprint": bp, "ore_type": ore_type, "amount": amount}
                )
                if len(desired) >= MAX_INPUT_ORES:
                    break

        if len(desired) > self._max_queue_size:
            desired = desired[: self._max_queue_size]

        return desired

    def _clear_refinery_inventory_soft(
        self,
        refinery: RefineryDevice,
        keep_ore_types: List[str],
        max_keep: int = 3,
    ) -> int:
        actions = 0
        inv = refinery.input_inventory()
        if not inv or not inv.items:
            return actions

        items = inv.items
        allowed = set(keep_ore_types or [])
        seen: List[str] = []

        print(f"Clearing refinery {refinery.name} input (soft), items={len(items)}")

        for item in items:
            ore = self._normalize_ore_name(item.subtype)
            amount = item.amount

            if ore in allowed:
                if ore not in seen:
                    seen.append(ore)
                if len(seen) <= max_keep:
                    # оставляем
                    continue

            # иначе убираем в любой source
            moved = False
            for src in self._source_containers:
                try:
                    res = refinery.move_subtype(src.device_id, item.subtype, amount=amount)
                    if res > 0:
                        print(f"  moved {amount} {item.subtype} -> {src.name}")
                        actions += 1
                        moved = True
                        break
                except Exception as e:
                    print(f"  move error: {e}")
            if not moved:
                print(f"  could not move {item.subtype} from refinery {refinery.name}")

        return actions

    def _arrange_resources_in_queue_order(self, refinery: RefineryDevice, queue: List[Dict]) -> None:
        """
        Главное место: берём ТОЛЬКО руду и двигаем её в refinery.device_id — как в твоём рабочем скрипте.
        """
        print(f"Arranging resources in {refinery.name} for {len(queue)} items")

        # собираем контейнеры
        all_containers: List[ContainerDevice] = []
        for grid in self._grids:
            for dev in grid.devices.values():
                if not isinstance(dev, ContainerDevice):
                    continue
                if dev.device_id == refinery.device_id:
                    continue
                all_containers.append(dev)

        for item in queue:
            ore_type = item["ore_type"]
            need = item["amount"]

            for cont in all_containers:
                if need <= 0:
                    break

                try:
                    cont_items = cont.items()
                except Exception:
                    continue

                for ci in cont_items:
                    # двигаем только реальную руду
                    if not self._is_real_ore(ci):
                        continue
                    norm = self._normalize_ore_name(ci.subtype)
                    if norm != ore_type:
                        continue

                    to_move = min(ci.amount, need)
                    moved = cont.move_subtype(refinery.device_id, ci.subtype, amount=to_move)
                    if moved > 0:
                        print(f"  {cont.name} -> {refinery.name}: {to_move} {ci.subtype}")
                        need -= to_move
                        if need <= 0:
                            break

    def _are_resources_properly_arranged(self, refinery: RefineryDevice, queue: List[Dict]) -> bool:
        inv = refinery.input_inventory()
        items = inv.items if inv else []

        if not queue:
            return not items

        desired = [x["ore_type"] for x in queue]

        actual: List[str] = []
        for it in items:
            ore = self._normalize_ore_name(it.subtype)
            if not actual or actual[-1] != ore:
                actual.append(ore)

        if desired and not actual:
            return False

        # actual должен быть префиксом desired
        for i, ore in enumerate(actual):
            if i >= len(desired):
                return False
            if ore != desired[i]:
                return False

        return True

    def _get_current_processing_ore(self, refinery: RefineryDevice) -> Optional[str]:
        inv = refinery.input_inventory()
        if inv and inv.items:
            first = inv.items[0]
            norm = self._normalize_ore_name(first.subtype)
            if norm in self._priority_ores:
                return norm

        queue = refinery.queue()
        for item in queue:
            bp = item.get("blueprintSubtype", item.get("blueprintId", item.get("blueprint", "")))
            for ore, mapped in ORE_TO_BLUEPRINT.items():
                if mapped == bp:
                    return ore
        return None

    def _get_ore_priority(self, ore_type: str) -> int:
        if ore_type in self._priority_ores:
            return self._priority_ores.index(ore_type)
        return len(self._priority_ores)

    def _should_interrupt_current_processing(self, refinery: RefineryDevice, desired_queue: List[dict]) -> bool:
        # по твоему описанию — почти никогда не надо прерывать
        current_ore = self._get_current_processing_ore(refinery)
        if not current_ore:
            return False

        desired_ores = [x["ore_type"] for x in desired_queue]
        if current_ore in desired_ores:
            return False

        # можно вообще вернуть False, но оставим "умно"
        available = self._get_available_resources()
        current_prio = self._get_ore_priority(current_ore)

        for ore in self._priority_ores:
            if ore in available and available[ore] > 0:
                ore_prio = self._get_ore_priority(ore)
                if ore_prio < current_prio:
                    print(
                        f"{refinery.name}: interrupt {current_ore} ({current_prio}) "
                        f"because {ore} ({ore_prio}) is available and not in desired top"
                    )
                    return True

        return False

    def _queues_equal(self, queue1: List[Dict], queue2: List[Dict]) -> bool:
        if len(queue1) != len(queue2):
            return False
        for a, b in zip(queue1, queue2):
            bp1 = a.get("blueprintSubtype", a.get("blueprintId", a.get("blueprint", "")))
            bp2 = b.get("blueprint")
            if bp1 != bp2:
                return False
        return True


if __name__ == "__main__":
    app = App()
    app.start()
    try:
        while True:
            app.step()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nStopping refinery priority manager...")
    finally:
        app.close()
