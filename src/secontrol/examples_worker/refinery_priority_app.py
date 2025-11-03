"""Refinery priority manager application in the App(start/step) format.

Скрипт:
- подключается к гриду игрока,
- находит очистители и контейнеры-источники,
- следит за всеми рудами на гриде,
- во вход очистителя укладывает максимум ТРИ ресурса подряд по приоритету
  (только те, что реально есть на гриде),
- если во входе лежит не то и/или не в том порядке — возвращает в контейнеры.

"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from secontrol.base_device import Grid
from secontrol.common import close, resolve_owner_id, resolve_player_id
from secontrol.redis_client import RedisEventClient
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice


# Приоритетные руды (от высшего к низшему)
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

# Маппинг руды -> чертёж очистителя
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

# Сколько именно ресурсов мы хотим одновременно держать во входе очистителя
MAX_INPUT_ORES = 3

# Максимальный размер очереди в самой refinery (на всякий случай)
MAX_QUEUE_SIZE = 10

# Как часто обновлять список устройств
REFRESH_EVERY = 30


class App:
    def __init__(self, *, refresh_every: int = REFRESH_EVERY, max_queue_size: int = MAX_QUEUE_SIZE):
        self.counter = 0
        self._grids: List[Grid] = []
        self._refresh_every = max(1, int(refresh_every))
        self._max_queue_size = max(1, int(max_queue_size))
        self._refineries: List[RefineryDevice] = []
        self._source_containers: List[ContainerDevice] = []
        self._priority_ores = PRIORITY_ORES.copy()

    # ---------- lifecycle ----------

    def start(self):
        client = RedisEventClient()
        owner_id = resolve_owner_id()
        player_id = resolve_player_id(owner_id)

        grids_info = client.list_grids(owner_id)
        for grid_info in grids_info:
            grid_id = str(grid_info.get("id"))
            grid_name = grid_info.get("name", f"Grid_{grid_id}")
            grid = Grid(client, owner_id, grid_id, player_id, grid_name)
            self._grids.append(grid)

        self._refresh_devices()

        # Отключаем conveyor у refinery — берём управление на себя
        for refinery in self._refineries:
            if refinery.use_conveyor():
                refinery.set_use_conveyor(False)
                print(f"Disabled conveyor system on refinery {refinery.name}")

        print(
            f"Refinery Priority Manager started: {len(self._refineries)} refineries, "
            f"{len(self._source_containers)} source containers"
        )
        print(f"Priority order: {', '.join(self._priority_ores)}")

    def step(self):
        if not self._grids:
            raise RuntimeError("Grids are not prepared. Call start() first.")

        self.counter += 1

        # Периодически обновляем список устройств
        if self.counter % self._refresh_every == 1:
            self._refresh_devices()

        total_actions = 0
        for refinery in self._refineries:
            total_actions += self._manage_refinery_queue(refinery)

        if total_actions > 0:
            print(f"Step {self.counter}: performed {total_actions} actions")
        else:
            print(f"Step {self.counter}: queues are optimized")

    def close(self):
        for grid in self._grids:
            try:
                close(grid)
            except Exception:
                pass

    # ---------- discovery ----------

    def _refresh_devices(self) -> None:
        if not self._grids:
            return

        all_refineries: List[RefineryDevice] = []
        all_source_containers: List[ContainerDevice] = []

        for grid in self._grids:
            # refinery
            refineries: List[RefineryDevice] = []
            finder = getattr(grid, "find_devices_by_type", None)
            if callable(finder):
                try:
                    refineries = list(finder("refinery"))
                except Exception:
                    refineries = []
            if not refineries:
                refineries = [
                    d for d in grid.devices.values()
                    if isinstance(d, RefineryDevice)
                ]
            all_refineries.extend(refineries)

            # containers
            containers: List[ContainerDevice] = []
            if callable(finder):
                try:
                    containers = list(finder("container"))
                except Exception:
                    containers = []
            if not containers:
                containers = [
                    d for d in grid.devices.values()
                    if isinstance(d, ContainerDevice)
                ]
            for c in containers:
                if self._is_source_container(c):
                    all_source_containers.append(c)

        self._refineries = all_refineries
        self._source_containers = all_source_containers

    def _is_source_container(self, container: ContainerDevice) -> bool:
        name = (container.name or "").lower()
        if "[source]" in name or "[input]" in name or "[ore]" in name:
            return True
        custom_data = container.custom_data()
        if custom_data:
            cd = custom_data.lower()
            if "source" in cd or "input" in cd or "ore" in cd:
                return True
        return False

    # ---------- core logic ----------

    def _manage_refinery_queue(self, refinery: RefineryDevice) -> int:
        actions = 0

        conveyor_was_enabled = refinery.use_conveyor()
        if conveyor_was_enabled:
            refinery.set_use_conveyor(False)
            actions += 1

        try:
            desired_queue = self._build_desired_queue()
            should_interrupt = self._should_interrupt_current_processing(refinery, desired_queue)
            current_queue = refinery.queue()

            desired_queue = self._build_desired_queue()
            print(
                f"Refinery {refinery.name}: interrupt={should_interrupt}, "
                f"current_len={len(current_queue)}, desired_len={len(desired_queue)}"
            )

            # Проверяем входной инвентарь: там должны лежать максимум 3 нужных руды в нужном порядке
            arranged = self._are_resources_properly_arranged(refinery, desired_queue)
            print(f"Refinery {refinery.name}: resources arranged={arranged}")

            queues_equal = self._queues_equal(current_queue, desired_queue)
            print(f"Refinery {refinery.name}: queues_equal={queues_equal}")

            if should_interrupt or not queues_equal or not arranged:
                # чистим вход, оставляя только первые N руд в правильном порядке
                keep_ores = [item["ore_type"] for item in desired_queue]
                actions += self._clear_refinery_inventory(refinery, keep_ore_types=keep_ores)

                # чистим очередь и ставим заново
                if current_queue:
                    refinery.clear_queue()
                    actions += 1
                    time.sleep(0.1)

                for item in desired_queue:
                    refinery.add_queue_item(item["blueprint"], item["amount"])
                    actions += 1

                # теперь физически докладываем руду в входной инвентарь
                self._arrange_resources_in_queue_order(refinery, desired_queue)
                actions += 1

        finally:
            if conveyor_was_enabled:
                refinery.set_use_conveyor(True)
                actions += 1

        return actions

    # ---------- helpers ----------

    def _normalize_ore_name(self, subtype: str) -> str:
        if not subtype:
            return ""
        # иногда в играх бывает "Iron Ore" или "IronOre"
        s = subtype.strip()
        if s.endswith(" Ore"):
            s = s[:-4]
        if s.endswith("Ore"):
            s = s[:-3]
        return s

    from secontrol.devices.container_device import ContainerDevice

    def _get_available_resources(self) -> Dict[str, float]:
        available: Dict[str, float] = {}

        for grid in self._grids:
            # тут раньше было: containers = grid.find_devices_containers()
            # но оно возвращает и refinery, и reactor, и ещё всякое
            for dev in grid.devices.values():
                # берем ТОЛЬКО реальные контейнеры
                if not isinstance(dev, ContainerDevice):
                    continue

                try:
                    items = dev.items()
                except Exception:
                    continue

                for item in items:
                    raw_subtype = item.subtype or ""
                    norm = self._normalize_ore_name(raw_subtype)
                    if norm in self._priority_ores:
                        available.setdefault(norm, 0.0)
                        available[norm] += float(item.amount)
                        print(f"  {dev.name}: +{item.amount} {norm}")

        print(f"Available resources: {available}")
        return available

    def _build_desired_queue(self) -> List[Dict]:
        """Строим список из максимум 3 руд, которые прямо сейчас есть на гриде, в порядке приоритета."""
        available = self._get_available_resources()
        desired: List[Dict] = []

        for ore_type in self._priority_ores:
            if ore_type in available and available[ore_type] > 0:
                blueprint = ORE_TO_BLUEPRINT.get(ore_type)
                if not blueprint:
                    continue
                amount = min(available[ore_type], 1000)
                desired.append(
                    {
                        "blueprint": blueprint,
                        "ore_type": ore_type,
                        "amount": amount,
                    }
                )
                if len(desired) >= MAX_INPUT_ORES:
                    break

        # если нужно — можно ограничить очередью refinery
        if len(desired) > self._max_queue_size:
            desired = desired[: self._max_queue_size]

        return desired

    def _clear_refinery_inventory(self, refinery: RefineryDevice, keep_ore_types: List[str] = None) -> int:
        """Оставляем во входе только то, что нам нужно и только в правильных слотах."""
        actions = 0
        inv = refinery.input_inventory()
        if not inv or not inv.items:
            return actions

        items = inv.items
        print(f"Clearing refinery {refinery.name} input, items={len(items)}")

        for i, item in enumerate(items):
            subtype = self._normalize_ore_name(item.subtype)
            keep_this = False
            if keep_ore_types and i < len(keep_ore_types):
                if subtype == keep_ore_types[i]:
                    keep_this = True

            if keep_this:
                continue

            amount = item.amount
            moved = False
            for src in self._source_containers:
                try:
                    # двигаем из очистителя в контейнер
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
        print(f"Arranging resources in {refinery.name} for {len(queue)} items")

        # ... получаем текущий инвентарь ...

        # собираем нормальные контейнеры
        all_containers: List[ContainerDevice] = []
        for grid in self._grids:
            for dev in grid.devices.values():
                if not isinstance(dev, ContainerDevice):
                    continue
                # не брать сам refinery
                if dev.device_id == refinery.device_id:
                    continue
                all_containers.append(dev)

        for idx, item in enumerate(queue):
            ore_type = item["ore_type"]
            need = item["amount"]

            # ... проверка, сколько уже есть ...

            for cont in all_containers:
                if need <= 0:
                    break

                try:
                    cont_items = cont.items()
                except Exception:
                    continue

                for ci in cont_items:
                    norm = self._normalize_ore_name(ci.subtype)
                    if norm != ore_type:
                        continue

                    to_move = min(ci.amount, need)

                    # ВАЖНО: двигаем в УСТРОЙСТВО, а не в инвентарь
                    moved = cont.move_subtype(refinery.device_id, ci.subtype, amount=to_move)
                    if moved > 0:
                        print(f"  {cont.name} -> {refinery.name}: {to_move} {ci.subtype}")
                        need -= to_move
                        if need <= 0:
                            break

    def _are_resources_properly_arranged(self, refinery: RefineryDevice, queue: List[Dict]) -> bool:
        inv = refinery.input_inventory()
        items = inv.items if inv else []

        # если мы ХОТИМ что-то положить, но во входе пусто — это НЕ ок
        if queue and not items:
            return False

        for i, qitem in enumerate(queue):
            if i >= len(items):
                # мы ожидали слот, а его нет
                return False
            expected = qitem["ore_type"]
            actual = self._normalize_ore_name(items[i].subtype)
            if actual != expected:
                return False

        # если после нужных слотов лежит мусор — тоже не ок
        if len(items) > len(queue):
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
        """Прерывать только если реально обрабатывается что-то ВНЕ нужной тройки."""
        current_ore = self._get_current_processing_ore(refinery)
        if not current_ore:
            return False  # нечего прерывать

        # какие руды мы хотим держать прямо сейчас
        desired_ores = [x["ore_type"] for x in desired_queue]

        # если текущая руда уже входит в нужные 3 — НЕ прерываем
        if current_ore in desired_ores:
            return False

        # дальше — старая логика "есть ли что-то важнее"
        available_resources = self._get_available_resources()
        current_priority = self._get_ore_priority(current_ore)

        for ore_type in self._priority_ores:
            if ore_type in available_resources and available_resources[ore_type] > 0:
                ore_priority = self._get_ore_priority(ore_type)
                if ore_priority < current_priority:
                    print(
                        f"{refinery.name}: interrupt {current_ore} ({current_priority}) "
                        f"because {ore_type} ({ore_priority}) is available and not in desired top"
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
