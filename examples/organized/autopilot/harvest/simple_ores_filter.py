#!/usr/bin/env python3
"""
Отладка OreFilter для Nanobot Drill:

- Печатаем состояние фильтра до изменений.
- Делаем:
    1) OreFilter = 'all'  (включить все слоты через плагин)
    2) OreFilter = 'none' (выключить все слоты через плагин)
    3) set_ore_filter('Ice') (включить только лёд через Python-обёртку)
- После каждого шага печатаем:
    Drill.DrillPriorityList
    Drill.ComponentClassList
    oreFilterIndices
    enabled_ores (debug_get_enabled_known_ores)
"""

import time

from secontrol.common import prepare_grid, close
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

GRID_NAME = "taburet2"


def dump_drill_state(drill: NanobotDrillSystemDevice, label: str) -> None:
    drill.update()
    drill.wait_for_telemetry(timeout=5)

    tel = drill.telemetry or {}
    props = tel.get("properties", {}) or {}

    print(f"\n===== {label} =====")
    print("Drill.DrillPriorityList:")
    print("  ", props.get("Drill.DrillPriorityList"))

    print("Drill.ComponentClassList:")
    print("  ", props.get("Drill.ComponentClassList"))

    print("oreFilterIndices (из плагина):")
    print("  ", tel.get("oreFilterIndices"))

    try:
        enabled_ores = drill.debug_get_enabled_known_ores()
    except Exception as e:
        enabled_ores = f"<error in debug_get_enabled_known_ores: {e}>"

    print("enabled ores (debug_get_enabled_known_ores):")
    print("  ", enabled_ores)

    print("Drill.ScriptControlled / drill_scriptcontrolled:")
    print("  props['Drill.ScriptControlled'] =", props.get("Drill.ScriptControlled"))
    print("  tel['drill_scriptcontrolled']   =", tel.get("drill_scriptcontrolled"))


def main() -> None:
    print("Подключение к гриду для отладки OreFilter Nanobot Drill...")
    grid = prepare_grid(GRID_NAME)

    try:
        drill:NanobotDrillSystemDevice = grid.get_first_device(NanobotDrillSystemDevice)
        if not drill:
            print("Nanobot Drill не найден!")
            return

        print(f"Найден Nanobot Drill: {drill.name}")

        # 0. Снимок до любых изменений
        dump_drill_state(drill, "СОСТОЯНИЕ ДО ИЗМЕНЕНИЙ")

        # 1. Включаем все слоты через плагин: OreFilter = 'all'
        print("\n--- OreFilter = 'all' (через set_property) ---")
        drill.set_property("OreFilter", "all")
        time.sleep(0.5)
        dump_drill_state(drill, "ПОСЛЕ OreFilter = 'all'")

        # 2. Выключаем все слоты: OreFilter = 'none'
        print("\n--- OreFilter = 'none' (через set_property) ---")
        drill.set_property("OreFilter", "none")
        time.sleep(0.5)
        dump_drill_state(drill, "ПОСЛЕ OreFilter = 'none'")

        # 3. Ставим фильтр на лёд через обёртку set_ore_filter('Ice')
        print("\n--- set_ore_filter('Ice') ---")
        drill.set_ore_filter("Ice")
        time.sleep(0.5)
        dump_drill_state(drill, "ПОСЛЕ set_ore_filter('Ice')")

        print("\nОтладка OreFilter завершена. Смотри, как меняются oreFilterIndices и enabled_ores.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
