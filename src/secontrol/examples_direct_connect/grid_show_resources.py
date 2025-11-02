"""Пример отображения всех ресурсов в контейнерах грида.

Этот пример демонстрирует универсальный метод get_device_resources(),
который можно применять к любому устройству грида для получения списка ресурсов.
"""

from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice


def get_device_resources(device) -> list[dict] | None:
    """
    Универсальный метод для получения ресурсов из устройства.

    Этот метод можно применять к любому устройству грида.
    Он проверяет, является ли устройство контейнером, и возвращает его содержимое.

    Args:
        device: Любое устройство грида (BaseDevice или его наследник)

    Returns:
        list[dict]: Список ресурсов в формате:
            [{'type': str, 'subtype': str, 'amount': float, 'displayName': str}, ...]
        None: Если устройство не является контейнером или не имеет метода items()

    Примеры использования:
        # Для любого устройства на гриде
        resources = get_device_resources(some_device)
        if resources is None:
            print("Это устройство не является контейнером")
        elif not resources:
            print("Контейнер пустой")
        else:
            for resource in resources:
                print(f"{resource['amount']} x {resource['displayName']}")

        # Для конкретного устройства по ID
        device = grid.get_device("device_id")
        if device:
            resources = get_device_resources(device)
            # ... обработка результатов
    """
    if not isinstance(device, ContainerDevice):
        return None

    try:
        resources = []
        for item in device.items():
            resources.append({
                'type': item.type,
                'subtype': item.subtype,
                'amount': item.amount,
                'displayName': item.display_name or item.subtype
            })
        return resources
    except Exception:
        # Если что-то пошло не так с получением items()
        return None


def show_device_resources(device):
    """
    Пример использования get_device_resources() на конкретном устройстве.

    Args:
        device: Устройство для проверки
    """
    print(f"Проверка устройства: {device.name} ({device.device_type})")

    resources = get_device_resources(device)

    if resources is None:
        print("❌ Это устройство не является контейнером")
        return

    if not resources:
        print("📦 Контейнер пустой")
        return

    print("📦 Содержимое контейнера:")
    for resource in resources:
        amount = int(resource['amount']) if isinstance(resource['amount'], float) and resource['amount'].is_integer() else resource['amount']
        print(f"  • {amount} x {resource['displayName']}")


def show_grid_resources():
    """Показать все ресурсы во всех контейнерах грида."""
    grid = prepare_grid()
    try:
        print(f"Ресурсы на гриде: {grid.name}")
        print("=" * 50)

        total_containers = 0
        total_items = 0

        # Проходим по всем устройствам грида
        for device in grid.devices.values():
            resources = get_device_resources(device)

            if resources is None:
                # Устройство не является контейнером
                continue

            total_containers += 1

            if not resources:
                # Контейнер пустой
                print(f"📦 {device.name} ({device.device_type}): пустой")
                continue

            print(f"📦 {device.name} ({device.device_type}):")
            for resource in resources:
                amount = int(resource['amount']) if isinstance(resource['amount'], float) and resource['amount'].is_integer() else resource['amount']
                print(f"  • {amount} x {resource['displayName']}")
                total_items += resource['amount']

        print("=" * 50)
        print(f"Всего контейнеров: {total_containers}")
        print(f"Всего предметов: {int(total_items) if total_items.is_integer() else total_items}")

        if total_containers == 0:
            print("На гриде нет контейнеров.")

    finally:
        close(grid)


def demo_individual_device():
    """Демонстрация использования метода на отдельных устройствах."""
    grid = prepare_grid()
    try:
        print("Демонстрация get_device_resources() на отдельных устройствах")
        print("=" * 60)

        # Найдем несколько устройств разных типов для демонстрации
        devices_to_check = []

        # Попробуем найти контейнер
        containers = grid.find_devices_by_type("container")
        if containers:
            devices_to_check.append(("Контейнер", containers[0]))

        # Попробуем найти ассемблер
        assemblers = grid.find_devices_by_type("assembler")
        if assemblers:
            devices_to_check.append(("Ассемблер", assemblers[0]))

        # Возьмем первое попавшееся устройство (не контейнер)
        for device in grid.devices.values():
            if not isinstance(device, ContainerDevice):
                devices_to_check.append(("Не-контейнер", device))
                break

        if not devices_to_check:
            print("Не найдено устройств для демонстрации")
            return

        for device_type_name, device in devices_to_check:
            print(f"\n--- {device_type_name}: {device.name} ---")
            show_device_resources(device)

    finally:
        close(grid)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo_individual_device()
    else:
        show_grid_resources()
