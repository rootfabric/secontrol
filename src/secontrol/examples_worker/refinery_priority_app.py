"""Refinery priority manager application in the App(start/step) format.

The script connects to the player's grid, discovers refineries and source containers,
and manages priority ore processing by setting up refinery queues and moving
resources according to priority order.

Priority ores are processed first, ensuring critical resources like uranium and
gold are refined before common materials like iron.

Usage (after installing dependencies and configuring environment variables):

    python -m secontrol.examples_worker.refinery_priority_app

Configuration:
- PRIORITY_ORES: List of ore types in processing priority order (highest first)
- MAX_QUEUE_SIZE: Maximum items per refinery queue
- REFRESH_EVERY: How often to check and update refinery states (steps)
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from secontrol.base_device import Grid
from secontrol.common import close, resolve_owner_id, resolve_player_id
from secontrol.redis_client import RedisEventClient
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice


# Приоритетные руды для обработки (от высшего к низшему приоритету)
PRIORITY_ORES = [


    "Platinum",  # Платина - ценный ресурс
    "Uranium",  # Уран - критический ресурс
    "Gold",       # Золото - ценный ресурс
    "Silver",     # Серебро - ценный ресурс
    "Cobalt",     # Кобальт - для продвинутых компонентов
    "Nickel",     # Никель - для продвинутых компонентов
    "Magnesium",  # Магний - для продвинутых компонентов
    "Iron",       # Железо - базовый ресурс
    "Silicon",    # Кремний - базовый ресурс
    "Stone",      # Камень - самый низкий приоритет
]

# Маппинг руд на чертежи очистителя
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
    "Uranium": "UraniumOreToIngot"
}

# Максимальный размер очереди на очиститель
MAX_QUEUE_SIZE = 10

# Частота проверки состояния (каждые N шагов)
REFRESH_EVERY = 30


class App:
    """Менеджер приоритетной обработки руд в очистителях."""

    def __init__(self, *, refresh_every: int = REFRESH_EVERY, max_queue_size: int = MAX_QUEUE_SIZE):
        self.counter = 0
        self._grids: List[Grid] = []
        self._refresh_every = max(1, int(refresh_every))
        self._max_queue_size = max(1, int(max_queue_size))
        self._refineries: List[RefineryDevice] = []
        self._source_containers: List[ContainerDevice] = []
        self._priority_ores = PRIORITY_ORES.copy()

    def start(self):
        """Инициализация приложения."""
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

        # Отключение conveyor system на всех refinery для ручного управления ресурсами
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
        """Один шаг работы приложения."""
        if not self._grids:
            raise RuntimeError("Grids are not prepared. Call start() first.")

        self.counter += 1

        # Периодическое обновление списка устройств
        if self.counter % self._refresh_every == 1:
            self._refresh_devices()

        # Управление очередями очистителей
        total_actions = 0
        for refinery in self._refineries:
            actions = self._manage_refinery_queue(refinery)
            total_actions += actions

        if total_actions > 0:
            print(f"Step {self.counter}: performed {total_actions} queue management actions")
        else:
            print(f"Step {self.counter}: queues are optimized")

    def close(self):
        """Закрытие приложения."""
        for grid in self._grids:
            try:
                close(grid)
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    def _refresh_devices(self) -> None:
        """Обновление списков устройств."""
        if not self._grids:
            return

        # Поиск очистителей
        all_refineries: List[RefineryDevice] = []
        for grid in self._grids:
            finder = getattr(grid, "find_devices_by_type", None)
            if callable(finder):
                try:
                    refineries = list(finder("refinery"))
                    all_refineries.extend(refineries)
                except Exception:
                    pass
            if not all_refineries:
                all_refineries = [
                    device
                    for device in grid.devices.values()
                    if isinstance(device, RefineryDevice)
                ]

        # Поиск контейнеров-источников
        all_source_containers: List[ContainerDevice] = []
        for grid in self._grids:
            containers: List[ContainerDevice] = []
            finder = getattr(grid, "find_devices_by_type", None)
            if callable(finder):
                try:
                    containers = list(finder("container"))
                except Exception:
                    containers = []
            if not containers:
                containers = [
                    device
                    for device in grid.devices.values()
                    if isinstance(device, ContainerDevice)
                ]

            # Фильтрация контейнеров-источников по имени или custom data
            for container in containers:
                if self._is_source_container(container):
                    all_source_containers.append(container)

        self._refineries = all_refineries
        self._source_containers = all_source_containers

    def _is_source_container(self, container: ContainerDevice) -> bool:
        """Проверка, является ли контейнер источником ресурсов."""
        # Проверка по имени
        name = (container.name or "").lower()
        if "[source]" in name or "[input]" in name or "[ore]" in name:
            return True

        # Проверка по custom data
        custom_data = container.custom_data()
        if custom_data and ("source" in custom_data.lower() or
                           "input" in custom_data.lower() or
                           "ore" in custom_data.lower()):
            return True

        return False

    def _clear_refinery_inventory(self, refinery: RefineryDevice, keep_ore_types: List[str] = None) -> int:
        """Очистка входного инвентаря очистителя, перемещение ресурсов обратно в контейнеры-источники.

        keep_ore_types: список типов руды, которые не нужно убирать (если они в правильном порядке)
        """
        actions = 0

        # Получение входного инвентаря
        input_inventory = refinery.input_inventory()
        if not input_inventory:
            return actions

        items = input_inventory.items
        if not items:
            return actions

        print(f"Clearing inventory for refinery {refinery.name}")

        # Перемещение всех ресурсов обратно в контейнеры-источники, кроме тех, что нужно сохранить
        for i, item in enumerate(items):
            if item.amount > 0:
                subtype = item.subtype

                # Проверяем, нужно ли сохранить этот ресурс
                should_keep = False
                if keep_ore_types and i < len(keep_ore_types):
                    expected_ore = keep_ore_types[i]
                    if subtype == expected_ore:
                        print(f"Keeping {item.amount} {subtype} in refinery (correct position {i})")
                        should_keep = True

                if should_keep:
                    continue

                amount = item.amount

                # Ищем контейнер-источник, куда можно переместить
                moved = False
                for source_container in self._source_containers:
                    try:
                        print(f"Attempting to move {amount} {subtype} from refinery {refinery.name} (ID: {refinery.device_id}) to source container {source_container.name} (ID: {source_container.device_id})")
                        result = refinery.move_subtype(source_container.device_id, subtype, amount=amount)
                        if result > 0:
                            print(f"✅ Successfully moved {amount} {subtype} from refinery {refinery.name} input inventory to source container {source_container.name}")
                            actions += 1
                            moved = True
                            break
                        else:
                            print(f"❌ Failed to move {subtype} from refinery to {source_container.name}")
                    except Exception as e:
                        print(f"Error moving {subtype} from refinery {refinery.name} to source container {source_container.name}: {e}")
                        continue

                if not moved:
                    print(f"Could not move {amount} {subtype} from refinery {refinery.name} back to any source container")

        return actions

    def _manage_refinery_queue(self, refinery: RefineryDevice) -> int:
        """Управление очередью конкретного очистителя."""
        actions = 0

        # Временное отключение conveyor system для предотвращения автоматического забора ресурсов
        conveyor_was_enabled = refinery.use_conveyor()
        if conveyor_was_enabled:
            refinery.set_use_conveyor(False)
            actions += 1
            time.sleep(0.1)

        try:
            # Проверка, нужно ли прервать текущую обработку из-за низкого приоритета
            should_interrupt = self._should_interrupt_current_processing(refinery)
            print(f"Refinery {refinery.name}: should_interrupt={should_interrupt}")

            # Получение текущей очереди
            current_queue = refinery.queue()
            print(f"Current queue length: {len(current_queue)}")

            # Определение требуемой очереди на основе приоритетов и доступных ресурсов
            desired_queue = self._build_desired_queue(refinery)
            print(f"Desired queue length: {len(desired_queue)}")

            # Проверка, правильно ли расставлены ресурсы в input inventory
            resources_properly_arranged = self._are_resources_properly_arranged(refinery, desired_queue)
            print(f"Resources properly arranged: {resources_properly_arranged}")

            # Сравнение текущей и желаемой очередей или принудительное обновление при низком приоритете
            queues_equal = self._queues_equal(current_queue, desired_queue)
            print(f"Queues equal: {queues_equal}")

            if should_interrupt or not queues_equal or not resources_properly_arranged:
                if should_interrupt:
                    print(f"Interrupting low-priority processing in refinery {refinery.name}")
                else:
                    print(f"Updating queue for refinery {refinery.name}")

                # Очистка входного инвентаря, сохраняя правильно расположенные ресурсы
                keep_ores = [item['ore_type'] for item in desired_queue]
                actions += self._clear_refinery_inventory(refinery, keep_ore_types=keep_ores)

                # Очистка текущей очереди
                if current_queue:
                    refinery.clear_queue()
                    actions += 1
                    time.sleep(0.5)  # Небольшая задержка

                # Добавление элементов в новую очередь
                for item in desired_queue:
                    blueprint = item['blueprint']
                    amount = item['amount']
                    refinery.add_queue_item(blueprint, amount)
                    actions += 1

                # Расстановка ресурсов в правильном порядке
                self._arrange_resources_in_queue_order(refinery, desired_queue)
                actions += 1
        finally:
            # Восстановление состояния conveyor system
            if conveyor_was_enabled:
                refinery.set_use_conveyor(True)
                actions += 1

        return actions

    def _build_desired_queue(self, refinery: RefineryDevice) -> List[Dict]:
        """Построение желаемой очереди для очистителя."""
        desired_queue = []

        # Проверка доступных ресурсов в контейнерах-источниках
        available_resources = self._get_available_resources()

        # Добавление элементов в порядке приоритета
        for ore_type in self._priority_ores:
            if ore_type in available_resources and available_resources[ore_type] > 0:
                blueprint = ORE_TO_BLUEPRINT.get(ore_type)
                if blueprint:
                    # Определение количества для добавления
                    amount = min(available_resources[ore_type], 1000)  # Максимум 1000 единиц за раз
                    desired_queue.append({
                        'blueprint': blueprint,
                        'ore_type': ore_type,
                        'amount': amount
                    })

                    # Ограничение размера очереди
                    if len(desired_queue) >= self._max_queue_size:
                        break

        return desired_queue

    def _get_available_resources(self) -> Dict[str, float]:
        """Получение доступных ресурсов из всех контейнеров на гриде."""
        available = {}

        # Получить все контейнеры на всех гридах
        all_containers = []
        for grid in self._grids:
            containers = grid.find_devices_containers()
            all_containers.extend(containers)

        print(f"Scanning {len(all_containers)} containers for ore...")

        for container in all_containers:
            items = container.items()
            for item in items:
                subtype = item.subtype or ""
                # Ищем только руду, а не слитки (исключаем Ingot)
                if subtype in self._priority_ores and "Ingot" not in subtype:
                    if subtype not in available:
                        available[subtype] = 0
                    available[subtype] += item.amount
                    print(f"  Found {item.amount} {subtype} in {container.name}")

        print(f"Available resources: {available}")
        return available

    def _arrange_resources_in_queue_order(self, refinery: RefineryDevice, queue: List[Dict]) -> None:
        """Расстановка ресурсов в контейнере очистителя в порядке очереди."""
        print(f"Arranging resources in refinery {refinery.name} for {len(queue)} queue items")

        # Получить текущие ресурсы в refinery input inventory
        input_inventory = refinery.input_inventory()
        current_inventory = {}
        if input_inventory and input_inventory.items:
            for item in input_inventory.items:
                current_inventory[item.subtype] = item.amount

        # Получить все контейнеры на гриде для поиска ресурсов
        all_containers = []
        for grid in self._grids:
            containers = grid.find_devices_containers()
            all_containers.extend(containers)

        for i, item in enumerate(queue):
            ore_type = item['ore_type']
            required_amount = item['amount']

            # Проверить, сколько уже есть в refinery
            current_amount = current_inventory.get(ore_type, 0)
            amount_needed = max(0, required_amount - current_amount)

            if amount_needed > 0:
                print(f"  Need {amount_needed} more {ore_type} (already have {current_amount})")

                # Поиск ресурса во всех контейнерах на гриде
                for container in all_containers:
                    if amount_needed <= 0:
                        break

                    container_items = container.items()
                    for container_item in container_items:
                        if container_item.subtype == ore_type and container_item.amount > 0:
                            transfer_amount = min(container_item.amount, amount_needed)
                            print(f"    Found {container_item.amount} {ore_type} in container {container.name} (ID: {container.device_id}), transferring {transfer_amount} to refinery {refinery.name} (ID: {refinery.device_id}) input inventory")

                            # Перемещение в input inventory refinery
                            result = container.move_subtype(
                                refinery.input_inventory(),
                                ore_type,
                                amount=transfer_amount
                            )

                            if result > 0:
                                print(f"    ✅ Successfully moved {transfer_amount} {ore_type} from container {container.name} to refinery {refinery.name} input inventory")
                                amount_needed -= transfer_amount
                                current_inventory[ore_type] = current_inventory.get(ore_type, 0) + transfer_amount
                                if amount_needed <= 0:
                                    break
                            else:
                                print(f"    ❌ Failed to move {ore_type} from container {container.name} to refinery {refinery.name}")

            else:
                print(f"  Already have enough {ore_type}: {current_amount} >= {required_amount}")

        print("Resource arrangement completed")

        # Проверка инвентаря refinery после перемещений
        input_inventory = refinery.input_inventory()
        if input_inventory:
            items = input_inventory.items
            if items:
                print("Refinery input inventory after arrangement:")
                for item in items:
                    print(f"  {item.amount} {item.subtype}")
            else:
                print("Refinery input inventory is empty after arrangement")
        else:
            print("Could not check refinery input inventory")

    def _get_current_processing_ore(self, refinery: RefineryDevice) -> Optional[str]:
        """Определение руды, которую refinery обрабатывает сейчас."""
        # Проверяем input inventory - там должна быть руда, которая обрабатывается
        input_inventory = refinery.input_inventory()
        if input_inventory and input_inventory.items:
            # Берем первый предмет в инвентаре (предполагаем, что refinery обрабатывает первый слот)
            first_item = input_inventory.items[0]
            subtype = first_item.subtype or ""
            if subtype in self._priority_ores:
                return subtype

        # Если в input inventory пусто, проверяем очередь
        queue = refinery.queue()
        if queue:
            first_item = queue[0]
            blueprint = first_item.get('blueprintSubtype', first_item.get('blueprintId', first_item.get('blueprint', '')))
            # Обратный маппинг из blueprint в руду
            for ore, bp in ORE_TO_BLUEPRINT.items():
                if bp == blueprint:
                    return ore

        return None

    def _get_ore_priority(self, ore_type: str) -> int:
        """Получение приоритета руды (меньше число = выше приоритет)."""
        if ore_type in self._priority_ores:
            return self._priority_ores.index(ore_type)
        return len(self._priority_ores)  # Низший приоритет для неизвестных

    def _are_resources_properly_arranged(self, refinery: RefineryDevice, queue: List[Dict]) -> bool:
        """Проверка, правильно ли расставлены ресурсы в input inventory по порядку очереди."""
        input_inventory = refinery.input_inventory()
        if not input_inventory or not input_inventory.items:
            return len(queue) == 0  # Если очередь пустая и инвентарь пустой - правильно

        inventory_items = input_inventory.items

        # Создаем словарь текущих ресурсов в refinery
        current_resources = {}
        for item in inventory_items:
            current_resources[item.subtype] = item.amount

        # Проверяем порядок: для каждого ресурса в очереди, если он есть в refinery,
        # он должен быть в правильной позиции относительно других ресурсов в очереди
        for i, queue_item in enumerate(queue):
            ore_type = queue_item['ore_type']
            if ore_type in current_resources:
                # Проверяем, что все предыдущие ресурсы в очереди либо отсутствуют, либо есть в правильном порядке
                for j in range(i):
                    prev_ore = queue[j]['ore_type']
                    if prev_ore in current_resources:
                        # Если предыдущий ресурс есть, а текущий тоже есть, порядок нарушен
                        print(f"Resource order violation: {prev_ore} (pos {j}) comes before {ore_type} (pos {i}) in queue, but both present in refinery")
                        return False
                # Проверяем, что нет ресурсов из очереди, которые должны быть после этого
                for j in range(i + 1, len(queue)):
                    next_ore = queue[j]['ore_type']
                    if next_ore in current_resources:
                        print(f"Resource order violation: {next_ore} (pos {j}) comes after {ore_type} (pos {i}) in queue, but both present in refinery")
                        return False

        return True

    def _should_interrupt_current_processing(self, refinery: RefineryDevice) -> bool:
        """Проверка, нужно ли прервать текущую обработку из-за низкого приоритета."""
        current_ore = self._get_current_processing_ore(refinery)
        if not current_ore:
            return False  # Ничего не обрабатывается

        current_priority = self._get_ore_priority(current_ore)

        # Проверяем, есть ли руда с более высоким приоритетом доступная
        available_resources = self._get_available_resources()

        for ore_type in self._priority_ores:
            if ore_type in available_resources and available_resources[ore_type] > 0:
                ore_priority = self._get_ore_priority(ore_type)
                if ore_priority < current_priority:
                    print(f"Refinery {refinery.name} processing {current_ore} (priority {current_priority}), "
                          f"but {ore_type} (priority {ore_priority}) is available and has higher priority")
                    return True

        return False

    def _queues_equal(self, queue1: List[Dict], queue2: List[Dict]) -> bool:
        """Сравнение двух очередей на эквивалентность."""
        if len(queue1) != len(queue2):
            return False

        for i, (item1, item2) in enumerate(zip(queue1, queue2)):
            blueprint1 = item1.get('blueprintSubtype', item1.get('blueprintId', item1.get('blueprint', '')))
            blueprint2 = item2.get('blueprint')

            if blueprint1 != blueprint2:
                return False

        return True


if __name__ == "__main__":
    app = App()
    app.start()
    try:
        while True:
            app.step()
            time.sleep(5)  # 5 секунд между шагами
    except KeyboardInterrupt:
        print("\nStopping refinery priority manager...")
    finally:
        app.close()
