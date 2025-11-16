#!/usr/bin/env python3
"""Скрипт для экспорта blueprint грида в формате XML для проектора.

Используется для извлечения представления грида в формате ShipBlueprintDefinition XML,
который можно загрузить в проектор Space Engineers через load_blueprint_xml().
"""

import argparse
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


def export_blueprint(projector, output_file: str) -> None:
    """Экспортировать blueprint грида и сохранить в файл."""
    print(f"Начинаем экспорт blueprint грида '{projector.name}'...")

    # Запросить экспорт blueprint
    projector.request_grid_blueprint(include_connected=True)
    print("Команда экспорта отправлена")

    # Ожидать завершения (зависит от размера грида)
    print("Ожидание завершения экспорта...")
    time.sleep(10)  # Подождать немного

    # Получить результат
    xml = projector.blueprint_xml()
    if xml:
        # Сохранить в файл
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(xml)

        print(f"Blueprint экспортирован в файл: {output_file}")
        print(f"Размер файла: {len(xml)} символов")

        # Покээать первые несколько строк для примера
        lines = xml.split('\n')[:20]
        print("\nПервые строки XML:")
        print("-" * 50)
        for line in lines:
            print(line.strip())
        print("-" * 50)
    else:
        print("Не удалось получить blueprint XML. Проверьте соединение и размер грида.")


def show_format_info():
    """Показать информацию о формате."""
    print("Формат XML blueprint для проектора:")
    print("=" * 50)
    print("""
<SomeOtherXmlRoot>
  <!-- Заголовок blueprint -->
  <MyObjectBuilder_ShipBlueprintDefinition>
    <Id> <!-- ID blueprint --></Id>
    <DisplayName>Blueprint Name</DisplayName>

    <CubeGrids>
      <!-- Массив гридов -->
      <CubeGrid>
        <GridSizeEnum>LARGE</GridSizeEnum>  <!-- LARGE или SMALL -->
        <DisplayName>Generated</DisplayName>  <!-- Имя грида -->

        <!-- Блоки в гриде -->
        <CubeBlocks>
          <MyObjectBuilder_CubeBlock>
            <SubtypeName>LargeBlockArmorBlock</SubtypeName>
            <Min x="0" y="0" z="0" />  <!-- Позиция -->
            <BlockOrientation Forward="Forward" Up="Up" />  <!-- Ориентация -->
            <!-- Другие свойства блока -->
          </MyObjectBuilder_CubeBlock>
          <!-- Больше блоков... -->
        </CubeBlocks>
      </CubeGrid>
    </CubeGrids>

    <Conveyors>  <!-- Конвейер система -->
      <!-- Связь конвейера -->
    </Conveyors>
  </MyObjectBuilder_ShipBlueprintDefinition>
</SomeOtherXmlRoot>
""")

    print("\nДругие примеры префабов для load_prefab():")
    print("- LargeGrid/StarterMiner")
    print("- SmallGrid/PassengerSeatJunior")
    print("- LargeGrid/LargeRailStraight (рельсы)")
    print("- И т.д. (зависит от VRage глиба)")


def main():


    grid = prepare_grid("95416675777277504")

    try:
        # Refresh devices to ensure correct classes
        grid.refresh_devices()

        # Найти проектор
        projector = find_projector(grid)
        if not projector:
            return

        # Экспортировать
        export_blueprint(projector, "grid_blueprint.xml")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
