#!/usr/bin/env python3
"""Скрипт для загрузки blueprint грида из XML файла в проектор.

Используется для загрузки ранее экспортированного чертежа в проектор Space Engineers.
"""

import time
from pathlib import Path
from typing import Optional

from secontrol.common import close, prepare_grid


def find_projector(grid) -> Optional[any]:
    """Найти проектор на гриде."""
    print("Поиск проектор устройств:")
    for device in grid.devices.values():
        print(f"  {device.device_type}: {device.name}")
    for device in grid.find_devices_by_type("projector"):
        print(f"Найден projector: {device}, type: {type(device)}, device_type: {device.device_type}")
        return device
    print("Проектор не найден на гриде.")
    return None


def load_blueprint(projector, input_file: str) -> bool:
    """Загрузить blueprint из файла в проектор."""
    print(f"Начинаем загрузку blueprint в проектор '{projector.name}' из файла '{input_file}'...")

    # Проверить существование файла
    file_path = Path(input_file)
    if not file_path.exists():
        print(f"Файл '{input_file}' не найден.")
        return False

    # Прочитать XML из файла
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            xml = f.read().strip()
    except Exception as e:
        print(f"Ошибка чтения файла '{input_file}': {e}")
        return False

    if not xml:
        print("Файл пуст.")
        return False

    # Проверить, что это XML
    if "<MyObjectBuilder_ShipBlueprintDefinition" not in xml:
        print("Файл не содержит валидный ShipBlueprintDefinition XML.")
        return False

    print(f"XML прочитан, размер: {len(xml)} символов")

    # Загрузить в проектор (keep=False: не сохранять текущую проекцию)
    try:
        seq_id = projector.load_blueprint_xml(xml, keep=False)
        print(f"Команда загрузки отправлена (seq_id: {seq_id})")
    except Exception as e:
        print(f"Ошибка загрузки blueprint: {e}")
        return False

    # Можно подождать немного, но не обязательно, т.к. команда асинхронная
    time.sleep(2)

    print("Blueprint успешно загружен в проектор.")
    return True


def main():
    grid = prepare_grid("95416675777277504")

    try:
        # Refresh devices to ensure correct classes
        grid.refresh_devices()

        # Найти проектор
        projector = find_projector(grid)
        if not projector:
            return

        # Загрузить blueprint
        success = load_blueprint(projector, "grid_blueprint.xml")
        if success:
            print("Операция завершена успешно.")
        else:
            print("Операция завершена с ошибкой.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
