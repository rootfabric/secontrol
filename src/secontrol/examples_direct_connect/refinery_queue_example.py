"""Пример управления очередью очистителя (refinery) для обработки руды.

Использование:
  python refinery_queue_example.py                           # Просмотр очереди
  python refinery_queue_example.py clear                    # Очистка очереди
  python refinery_queue_example.py reset                    # Создать новую очередь (железо первым)
  python refinery_queue_example.py IronOreToIngot 500      # Добавить 500 железной руды в очередь
  python refinery_queue_example.py StoneOreToIngot 1000    # Добавить 1000 камня в очередь
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List

from secontrol.common import close, prepare_grid
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.container_device import ContainerDevice


# Поддерживаемые чертежи для очистителя
REFINERY_BLUEPRINTS = {
    "StoneOreToIngot": "Камень → гравий + железо + никель + кремний",
    "IronOreToIngot": "Железная руда → железные слитки",
    "NickelOreToIngot": "Никелевая руда → никелевые слитки",
    "CobaltOreToIngot": "Кобальтовая руда → кобальтовые слитки",
    "MagnesiumOreToIngot": "Магниевая руда → магниевые слитки",
    "SiliconOreToIngot": "Кремниевая руда → кремниевые wafers",
    "SilverOreToIngot": "Серебряная руда → серебряные слитки",
    "GoldOreToIngot": "Золотая руда → золотые слитки",
    "PlatinumOreToIngot": "Платиновая руда → платиновые слитки",
    "UraniumOreToIngot": "Урановая руда → урановые слитки"
}

# Маппинг чертежей на соответствующие ресурсы для входного инвентаря
BLUEPRINT_TO_INPUT_RESOURCE = {
    "StoneOreToIngot": "Stone",
    "IronOreToIngot": "Iron",
    "NickelOreToIngot": "Nickel",
    "CobaltOreToIngot": "Cobalt",
    "MagnesiumOreToIngot": "Magnesium",
    "SiliconOreToIngot": "Silicon",
    "SilverOreToIngot": "Silver",
    "GoldOreToIngot": "Gold",
    "PlatinumOreToIngot": "Platinum",
    "UraniumOreToIngot": "Uranium"
}


def find_refinery(grid) -> RefineryDevice | None:
    """Найти первый доступный очиститель на гриде."""
    for device in grid.devices.values():
        if isinstance(device, RefineryDevice):
            return device
    return None


def find_source_containers(grid) -> List[ContainerDevice]:
    """Найти контейнеры-источники ресурсов (с тегом [source] в имени или custom data)."""
    source_containers = []
    for device in grid.devices.values():
        if isinstance(device, ContainerDevice):
            # Проверяем тег [source] в имени
            if "[source]" in device.name.lower():
                source_containers.append(device)
                continue
            # Проверяем custom data
            custom_data = device.custom_data()
            if custom_data and "source" in custom_data.lower():
                source_containers.append(device)
    return source_containers


def arrange_resources_in_order(refinery: RefineryDevice, source_containers: List[ContainerDevice]) -> bool:
    """
    Расставить ресурсы в контейнере очистителя в порядке, соответствующем очереди.

    Перемещает ресурсы из контейнеров-источников в входной инвентарь очистителя
    в том порядке, как они указаны в очереди команд.
    """

    time.sleep(1)
    queue = refinery.queue()
    if not queue:
        print("Очередь пуста, нечего расставлять")
        return True

    print(f"Расстановка ресурсов для {len(queue)} элементов очереди...")

    for i, item in enumerate(queue):
        blueprint_id = item.get('blueprintSubtype', item.get('blueprintId', item.get('blueprint', '')))
        amount = item.get('amount', 0.0)

        if not blueprint_id:
            print(f"Пропуск элемента {i}: нет blueprint_id")
            continue

        # Определяем требуемый ресурс
        required_resource = BLUEPRINT_TO_INPUT_RESOURCE.get(blueprint_id)
        if not required_resource:
            print(f"Пропуск элемента {i}: неизвестный ресурс для чертежа {blueprint_id}")
            continue

        print(f"Элемент {i}: {blueprint_id} -> {required_resource}, количество: {amount}")

        # Ищем ресурс в контейнерах-источниках
        resource_found = False
        for source_container in source_containers:
            source_items = source_container.items()
            for source_item in source_items:
                if source_item.subtype == required_resource:
                    # Нашли ресурс, перемещаем в очиститель в соответствующий слот
                    transfer_amount = min(source_item.amount, amount)
                    print(f"  Перемещение {transfer_amount} {required_resource} из {source_container.name} в слот {i}")

                    result = source_container.move_subtype(refinery.device_id, required_resource, amount=transfer_amount, target_slot_id=i)
                    if result > 0:
                        print(f"  ✅ Перемещено {transfer_amount} {required_resource} в слот {i}")
                        resource_found = True
                        amount -= transfer_amount
                        if amount <= 0:
                            break
                    else:
                        print(f"  ❌ Ошибка перемещения {required_resource}")

            if resource_found and amount <= 0:
                break

        if not resource_found:
            print(f"  ⚠️ Ресурс {required_resource} не найден в контейнерах-источниках")

    print("Расстановка ресурсов завершена")
    return True


def display_queue(refinery: RefineryDevice) -> None:
    """Отобразить очередь команд очистителя."""
    queue = refinery.queue()

    if not queue:
        print("Очередь команд пуста")
        return

    print(f"Очередь команд очистителя '{refinery.name}' (ID: {refinery.device_id}):")
    print("=" * 60)

    # Отображаем очередь в обратном порядке (железо первым)
    for i, item in enumerate(reversed(queue)):
        blueprint_id = item.get('blueprintSubtype', item.get('blueprintId', item.get('blueprint', 'N/A')))
        blueprint_name = REFINERY_BLUEPRINTS.get(blueprint_id, blueprint_id)
        print(f"Позиция {i}:")
        print(f"  Blueprint: {blueprint_name}")
        print(f"  Amount: {item.get('amount', 'N/A')}")
        print("-" * 40)

    print(f"Всего элементов в очереди: {len(queue)}")


def display_available_blueprints() -> None:
    """Показать доступные чертежи для очистителя."""
    print("Доступные чертежи для очистителя:")
    print("=" * 50)
    for blueprint_id, description in REFINERY_BLUEPRINTS.items():
        print(f"  {blueprint_id:<20} - {description}")
    print()


def queue_resource(refinery: RefineryDevice, blueprint: str, amount: float) -> bool:
    """Добавить ресурс в очередь очистителя."""
    if blueprint not in REFINERY_BLUEPRINTS:
        print(f"Ошибка: неизвестный чертеж '{blueprint}'")
        print("Используйте один из поддерживаемых чертежей:")
        display_available_blueprints()
        return False

    print(f"Добавление в очередь: {REFINERY_BLUEPRINTS[blueprint]}")
    print(f"Количество: {amount}")

    try:
        result = refinery.add_queue_item(blueprint, amount)
        if result > 0:
            print("✅ Ресурс успешно добавлен в очередь")
            return True
        else:
            print("❌ Не удалось добавить ресурс в очередь")
            return False
    except Exception as e:
        print(f"❌ Ошибка при добавлении в очередь: {e}")
        return False


def queue_resource_with_arrangement(refinery: RefineryDevice, blueprint: str, amount: float, source_containers: List[ContainerDevice]) -> bool:
    """
    Добавить ресурс в очередь очистителя и расставить ресурсы в требуемом порядке.

    Сначала добавляет элемент в очередь, затем перемещает соответствующие ресурсы
    из контейнеров-источников в входной инвентарь очистителя.
    """
    # Сначала добавляем в очередь
    if not queue_resource(refinery, blueprint, amount):
        return False

    # Затем расставляем ресурсы
    print("\nРасстановка ресурсов в контейнере очистителя...")
    return arrange_resources_in_order(refinery, source_containers)


def clear_queue(refinery: RefineryDevice) -> bool:
    """Очистить очередь очистителя."""
    try:
        result = refinery.clear_queue()
        if result > 0:
            print("✅ Очередь успешно очищена")
            return True
        else:
            print("❌ Не удалось очистить очередь")
            return False
    except Exception as e:
        print(f"❌ Ошибка при очистке очереди: {e}")
        return False


def reset_queue_mode() -> None:
    """Режим создания новой очереди (железо первым)."""
    grid = prepare_grid()
    try:
        refinery = find_refinery(grid)
        if not refinery:
            print("Очиститель не найден на гриде")
            return

        print(f"Найден очиститель: {refinery.name} (ID: {refinery.device_id})")

        # Показать текущую очередь перед сбросом
        print("Текущая очередь перед сбросом:")
        display_queue(refinery)

        # Очистить очередь
        print("\nОчистка очереди...")
        if clear_queue(refinery):
            print("✅ Очередь очищена")

            # Добавить железную руду в начало очереди
            print("\nСоздание новой очереди с приоритетом на железо...")
            # if queue_resource(refinery, "GoldOreToIngot", 1000.0):
            if queue_resource(refinery, "UraniumOreToIngot", 1000.0):
                print("\n✅ Новая очередь создана (железо первым)")
                print("Обновленная очередь:")
                display_queue(refinery)
            else:
                print("❌ Не удалось добавить железную руду в очередь")
        else:
            print("❌ Не удалось очистить очередь")

    finally:
        close(grid)


def main() -> None:
    """Основная функция."""
    # Проверить аргументы командной строки

    view_queue_mode()

    # Режим очистки очереди
    clear_queue_mode()

    # Режим создания новой очереди (железо первым)
    # reset_queue_mode()

    # Режим добавления в очередь: blueprint amount
    blueprint ="GoldOreToIngot"
    amount = 10
    queue_resource_mode(blueprint, amount)


def view_queue_mode() -> None:
    """Режим просмотра очереди."""
    grid = prepare_grid()
    try:
        refinery = find_refinery(grid)
        if not refinery:
            print("Очиститель не найден на гриде")
            return

        print(f"Найден очиститель: {refinery.name} (ID: {refinery.device_id})")
        print()

        # Показать доступные чертежи
        # display_available_blueprints()

        # Показать очередь
        display_queue(refinery)

    finally:
        close(grid)


def clear_queue_mode() -> None:
    """Режим очистки очереди."""
    grid = prepare_grid()
    try:
        refinery = find_refinery(grid)
        if not refinery:
            print("Очиститель не найден на гриде")
            return

        print(f"Найден очиститель: {refinery.name} (ID: {refinery.device_id})")

        # Показать текущую очередь перед очисткой
        print("Текущая очередь перед очисткой:")
        display_queue(refinery)

        # Очистить очередь
        print("\nОчистка очереди...")
        if clear_queue(refinery):
            print("Очередь должна быть очищена")

    finally:
        close(grid)


def queue_resource_mode(blueprint: str, amount: float) -> None:
    """Режим добавления ресурса в очередь."""
    grid = prepare_grid()
    try:
        refinery = find_refinery(grid)
        if not refinery:
            print("Очиститель не найден на гриде")
            return

        print(f"Найден очиститель: {refinery.name} (ID: {refinery.device_id})")
        print()

        # Найти контейнеры-источники
        source_containers = find_source_containers(grid)
        if not source_containers:
            print("⚠️ Контейнеры-источники ([source]) не найдены. Ресурсы не будут перемещены.")
        else:
            print(f"Найдено контейнеров-источников: {len(source_containers)}")
            for container in source_containers:
                print(f"  - {container.name} (ID: {container.device_id})")

        # Показать текущую очередь
        print("Текущая очередь:")
        display_queue(refinery)
        print()

        # Добавить ресурс в очередь с расстановкой ресурсов
        if queue_resource_with_arrangement(refinery, blueprint, amount, source_containers):
            print("\nОбновленная очередь:")
            display_queue(refinery)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
