#!/usr/bin/env python3
"""
Тестовый harvest-скрипт Nanobot Drill & Fill в "обычном" режиме:
- ScriptControlled = False
- WorkMode = Drill
- OreFilter только на Ice
- Запуск через Drill_On
"""

from __future__ import annotations

import time
from typing import Dict, Any, List, Tuple, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

GRID_NAME = "taburet2"
ORE_TYPE = "Ice"

Point3D = Tuple[float, float, float]


def parse_visible_ores(telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
    props = telemetry.get("properties", {}) if telemetry else {}
    targets = props.get("Drill.PossibleDrillTargets", []) or []
    visible: List[Dict[str, Any]] = []

    for target in targets:
        if len(target) >= 5:
            ore_name = target[3]
            ore_type = str(ore_name).split("/")[-1]
            ore_mapping = {"Snow": "Ice", "IronIngot": "Iron"}
            ore_display = ore_mapping.get(ore_type, ore_type)
            visible.append(
                {
                    "type": ore_display,
                    "volume": float(target[4]),
                    "distance": float(target[2]),
                }
            )
    return visible


def print_targets_info(telemetry: Dict[str, Any]) -> None:
    props = telemetry.get("properties", {}) if telemetry else {}
    drill_targets = props.get("Drill.PossibleDrillTargets", []) or []
    collect_targets = props.get("Drill.PossibleCollectTargets", []) or []
    print(
        f"  Drill.PossibleDrillTargets: {len(drill_targets)} шт., "
        f"PossibleCollectTargets: {len(collect_targets)} шт."
    )


def stop_nanobot(drill):
    """
    Корректная остановка Nanobot Drill & Fill System:
    - выключение режима Drill/Collect
    - сброс ScriptControlled
    - деактивация блока (OnOff = Off)
    """
    drill.update()
    drill.wait_for_telemetry(timeout=5)

    print("=== ОСТАНОВКА NANOBOT DRILL ===")

    # 1. Останавливаем работу (есть action Drill_On / Collect_On / Fill_On)
    #    Чтобы остановить — подаём Off.
    if drill.has_action("Drill_On"):
        drill.run_action("Drill_Off")
    if drill.has_action("Collect_On"):
        drill.run_action("Collect_Off")
    if drill.has_action("Fill_On"):
        drill.run_action("Fill_Off")

    time.sleep(0.2)

    # 2. Выключаем блок (OnOff_Off)
    if drill.has_action("OnOff_Off"):
        drill.run_action("OnOff_Off")

    time.sleep(0.2)

    # 3. Сбрасываем ScriptControlled = False
    drill.set_property("ScriptControlled", False)
    time.sleep(0.2)

    # 4. Обновляем телеметрию для контроля
    drill.update()
    drill.wait_for_telemetry(timeout=5)

    tel = drill.telemetry or {}
    props = tel.get("properties", {})

    print("Nanobot остановлен:")
    print(f"  WorkMode={tel.get('drill_workmode')} / {props.get('Drill.WorkMode')}")
    print(f"  ScriptControlled={props.get('Drill.ScriptControlled')}")
    print(f"  content={tel.get('content')}")

def configure_drill_for_ice_drill(drill: NanobotDrillSystemDevice) -> None:
    drill.update()
    drill.wait_for_telemetry(timeout=10)

    tel = drill.telemetry or {}
    props = tel.get("properties", {})

    print("=== НАСТРОЙКА NANOBOT DRILL (Drill) ===")
    print(f"Начальный WorkMode (raw): {tel.get('drill_workmode')} / {props.get('Drill.WorkMode')}")
    print(f"Начальные DrillPriorityList: {props.get('Drill.DrillPriorityList')}")
    print_targets_info(tel)

    # 1. Выключаем ScriptControlled (чтобы мод работал как обычный блок)
    #    Важно: мы задаём именно Drill.ScriptControlled
    drill.set_property("ScriptControlled", True)
    time.sleep(0.2)

    # 2. Включаем блок
    drill.turn_on()
    time.sleep(0.2)

    # 3. Конвейер
    drill.set_use_conveyor(True)
    time.sleep(0.1)

    # 4. Режим работы = Drill
    drill.set_work_mode("drill")
    time.sleep(0.3)

    # 5. Фильтр по руде через OreFilter
    print(f"Выставляем OreFilter на руду: {ORE_TYPE}")
    drill.set_ore_filter(ORE_TYPE)
    time.sleep(0.5)

    # 6. Обновляем телеметрию
    drill.update()
    drill.wait_for_telemetry(timeout=5)
    tel = drill.telemetry or {}
    props = tel.get("properties", {})

    print("После настройки:")
    print(f"  WorkMode (raw): {tel.get('drill_workmode')} / {props.get('Drill.WorkMode')}")
    print(f"  ScriptControlled: {props.get('Drill.ScriptControlled')} / {tel.get('drill_scriptcontrolled')}")
    print(f"  oreFilterIndices: {tel.get('oreFilterIndices')}")
    print(f"  enabled ores: {drill.debug_get_enabled_known_ores()}")
    print_targets_info(tel)

    visible = parse_visible_ores(tel)
    if visible:
        print("  Видимые руды:")
        for ore in visible:
            print(
                f"    - {ore['type']}: объём {ore['volume']:.1f}, "
                f"расстояние {ore['distance']:.2f} м"
            )
    else:
        print("  Видимые руды отсутствуют.")


def main() -> None:
    print("Запуск harvest-дрона с Nanobot Drill (режим Drill)...")
    grid = prepare_grid(GRID_NAME)

    try:
        drill:NanobotDrillSystemDevice = grid.get_first_device(NanobotDrillSystemDevice)
        if not drill:
            print("Nanobot Drill не найден!")
            return

        print("Доступные действия Nanobot Drill:")
        print("  " + ", ".join(drill.available_action_ids()))

        drill.set_script_controlled(True)

        configure_drill_for_ice_drill(drill)

        # Старт бурения
        print("Запускаем Drill_On")
        drill.start_drilling()
        time.sleep(1.0)

        print("=== БУРЕНИЕ ЛЬДА ===")
        for i in range(3):
            time.sleep(10)
            drill.update()
            drill.wait_for_telemetry(timeout=5)

            tel = drill.telemetry or {}
            props = tel.get("properties", {})

            workmode = tel.get("drill_workmode")
            workmode_prop = props.get("Drill.WorkMode")
            ore_filter_indices = tel.get("oreFilterIndices")
            content = tel.get("content")
            current_target = props.get("Drill.CurrentDrillTarget") or tel.get("drill_currentdrilltarget")

            print(
                f"Прогресс {i + 1}/3: "
                f"WorkMode={workmode}/{workmode_prop}, "
                f"ScriptControlled={props.get('Drill.ScriptControlled')}, "
                f"oreFilterIndices={ore_filter_indices}, "
                f"content={content}, "
                f"hasCurrentTarget={bool(current_target)}"
            )
            print_targets_info(tel)

        print("Бурение завершено. Проверь контейнер Nanobot Drill и конвейерные контейнеры.")

        stop_nanobot(drill)


    finally:
        close(grid)


if __name__ == "__main__":
    main()
