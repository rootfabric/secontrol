#!/usr/bin/env python3
"""
Простой пример harvest-дрона с нано буром.

Бур бурит на месте и добывает ресурсы.
"""

from __future__ import annotations

import time
from typing import Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

# Настройки
GRID_NAME = "taburet2"  # Имя грида дрона
DRILL_DURATION_SECONDS = 5.0  # Время бурения в секундах
ORE_TYPE = "Uranium"  # Тип добываемой руды


def find_devices(grid) -> tuple[Optional[NanobotDrillSystemDevice], Optional[ContainerDevice]]:
    """Найти необходимые устройства на гриде."""
    drill = None
    container = None

    print(f"Поиск устройств на гриде {grid.name} (ID: {grid.grid_id})")
    print(f"Найдено устройств: {len(grid.devices)}")

    for device in grid.devices.values():
        if device.device_type == "ship_drill":
            drill = device
        elif isinstance(device, ContainerDevice):
            # Берем первый найденный контейнер
            if container is None:
                container = device

    return drill, container


def main() -> None:
    print("Запуск harvest-дрона (бурение на месте)...")

    # Подготовка грида
    grid = prepare_grid(GRID_NAME)
    try:
        # Поиск устройств
        drill: NanobotDrillSystemDevice= grid.get_first_device(NanobotDrillSystemDevice)
        container = grid.get_first_device(ContainerDevice)

        if not drill:
            print("Ошибка: Nanobot Drill System не найден на гриде!")
            return
        if not container:
            print("Ошибка: Контейнер дрона не найден на гриде!")
            return

        drill.set_script_controlled(True)
        time.sleep(0.7)

        drill.run_action("OnOff_On")
        time.sleep(0.3)

        drill.run_action("Collect_On")
        time.sleep(0.7)

        drill.set_property("CollectIfIdle", True)
        drill.set_property("UseConveyor", True)

        # Увеличиваем зону
        for _ in range(10):
            drill.run_action("AreaWidth_Increase")
            drill.run_action("AreaHeight_Increase")
            drill.run_action("AreaDepth_Increase")

        drill.set_show_area(True)

        # ←←← ВОТ ЭТО ГЛАВНОЕ! ←←←
        print("Устанавливаем ПРАВИЛЬНЫЙ Collect-фильтр...")
        drill.set_collect_filter(["Ice"])  # ← Только лёд!

        drill.run_action("PickFirstDrillTarget")
        time.sleep(1.0)

        drill.run_action("Work_On")

        print("ЛЁД ДОБЫВАЕТСЯ И СОБИРАЕТСЯ В КОНТЕЙНЕР!")


        drill.update()
        drill.wait_for_telemetry(timeout=5)

        print(drill.telemetry.get("properties"))

        print("ГОТОВО! Состояние:")
        print("  ScriptControlled:", drill.telemetry.get("scriptControlled"))
        print("  oreFilterIndices:", drill.telemetry.get("oreFilterIndices"))
        print("  enabled ores:", drill.debug_get_enabled_known_ores())

        print("Бур включён в режиме Collect — добывает только Silicon и Uranium!")
        print("Stone и остальные руды игнорируются.")

        print("=== ПРОВЕРКА СОСТОЯНИЯ ПО ПЛАГИНУ ===")
        print("ScriptControlled:", drill.telemetry.get("scriptControlled"))
        print("WorkMode (если есть):", drill.telemetry.get("properties", {}).get("WorkMode"))
        print("oreFilterIndices (истина в последней инстанции):", drill.telemetry.get("oreFilterIndices"))
        print("enabled ores (по плагину):", drill.debug_get_enabled_known_ores())



        # Проверяем статус бура
        status = drill.status_summary()
        if status:
            print(f"Статус бура: {status}")


    finally:
        close(grid)


if __name__ == "__main__":
    main()
