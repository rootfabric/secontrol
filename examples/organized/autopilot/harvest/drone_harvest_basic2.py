#!/usr/bin/env python3
"""
Автономный harvest-дрон с Nanobot Drill & Fill System.
Добывает Ice (или Uranium), читает видимые руды из телеметрии.
Работает в режиме Drill + OreFilter.
"""

from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple, Optional

from secontrol.common import close, prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

GRID_NAME = "taburet2"
ORE_TYPE = "Ice"  # Можно поменять на "Uranium"

Point3D = Tuple[float, float, float]


def parse_visible_ores(telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Парсит Drill.PossibleDrillTargets из телеметрии — список видимых руд."""
    targets = telemetry.get("properties", {}).get("Drill.PossibleDrillTargets", [])
    visible_ores: List[Dict[str, Any]] = []

    for target in targets:
        if len(target) >= 5:
            # target[3] = "MyObjectBuilder_VoxelMaterialDefinition/Snow"
            ore_name = target[3]
            ore_type = ore_name.split("/")[-1]  # Snow
            ore_mapping = {
                "Snow": "Ice",
                "IronIngot": "Iron",
            }
            ore_display = ore_mapping.get(ore_type, ore_type)
            visible_ores.append(
                {
                    "type": ore_display,
                    "volume": target[4],
                    "distance": target[2],
                }
            )

    return visible_ores


def pick_first_target(drill: NanobotDrillSystemDevice) -> None:
    """
    Пикает первую цель из PossibleDrillTargets, если есть действие PickDrillTarget_1.
    Если такого действия нет — просто пишет предупреждение.
    """
    props = drill.telemetry.get("properties", {}) if drill.telemetry else {}
    targets = props.get("Drill.PossibleDrillTargets", []) or []

    if not targets:
        print("Целей в Drill.PossibleDrillTargets нет, пропускаю пикинг.")
        return

    first_target = targets[0]
    ore_name = first_target[3] if len(first_target) > 3 else "<unknown>"
    volume = first_target[4] if len(first_target) > 4 else 0.0

    # if drill.has_action("PickDrillTarget_1"):
    #     drill.run_action("PickDrillTarget_1")
    #     print(f"Пикаем первую цель: {ore_name} (объём: {volume})")
    # else:
    #     print(
    #         "Действие 'PickDrillTarget_1' не найдено у Nanobot Drill. "
    #         "Возможно, мод использует другой идентификатор — пропускаю пикинг."
    #     )


def configure_drill(drill: NanobotDrillSystemDevice) -> None:
    """
    Базовая настройка блока:
    - ScriptControlled = True
    - Включаем блок
    - WorkMode = Drill
    - Включаем конвейеры и CollectIfIdle
    - Выставляем OreFilter на нужную руду
    - Расширяем зону работы и включаем отображение
    """

    drill.update()
    drill.wait_for_telemetry(timeout=10)

    tel = drill.telemetry or {}
    props = tel.get("properties", {})

    print("=== НАСТРОЙКА NANOBOT DRILL ===")
    print(f"Начальный WorkMode: {tel.get('drill_workmode')} / {props.get('Drill.WorkMode')}")
    print(f"Начальные DrillPriorityList: {props.get('Drill.DrillPriorityList')}")

    # Разрешаем управление из скрипта
    drill.set_script_controlled(True)
    time.sleep(0.3)

    # Включаем блок
    drill.turn_on()
    time.sleep(0.3)

    # Включаем конвейер и CollectIfIdle (через action)
    drill.set_use_conveyor(True)
    drill.set_collect_on_idle(True)
    time.sleep(0.3)

    # Жёстко ставим WorkMode = Drill (0)
    drill.set_work_mode("drill")
    time.sleep(0.3)

    # Настраиваем OreFilter через рабочий бридж (OreFilter -> SetDrillEnabled)
    print(f"Выставляем OreFilter на руду: {ORE_TYPE}")
    drill.set_ore_filter(ORE_TYPE)
    time.sleep(0.5)

    # Обновляем телеметрию, смотрим, что получилось
    drill.update()
    drill.wait_for_telemetry(timeout=5)
    tel = drill.telemetry or {}
    props = tel.get("properties", {})

    print("После применения фильтра:")
    print(f"  WorkMode: {tel.get('drill_workmode')} / {props.get('Drill.WorkMode')}")
    print(f"  DrillPriorityList(raw): {props.get('Drill.DrillPriorityList')}")
    print(f"  oreFilterIndices: {tel.get('oreFilterIndices')}")
    print(f"  enabled ores (по debug_get_enabled_known_ores): {drill.debug_get_enabled_known_ores()}")

    # Увеличиваем зону
    for _ in range(10):
        drill.increase_area_width()
        drill.increase_area_height()
        drill.increase_area_depth()
    drill.set_show_area(True)
    time.sleep(0.3)

    # Пробуем пикнуть первую цель (если есть соответствующее действие)
    pick_first_target(drill)

    # Запускаем бурение (Drill_On)
    drill.start_drilling()
    time.sleep(1.0)


def main() -> None:
    print("Запуск harvest-дрона с Nanobot Drill (режим Drill)...")
    grid = prepare_grid(GRID_NAME)

    try:
        drill = grid.get_first_device(NanobotDrillSystemDevice)
        if not drill:
            print("Nanobot Drill не найден!")
            return

        # Базовая настройка блока и фильтров
        configure_drill(drill)

        # Первый снимок видимых руд
        drill.update()
        drill.wait_for_telemetry(timeout=5)


        exit(0)
        visible = parse_visible_ores(drill.telemetry or {})
        print("=== ВИДИМЫЕ РУДЫ (по PossibleDrillTargets) ===")
        for ore in visible:
            print(
                f"- {ore['type']}: объём {ore['volume']:.3f}, "
                f"расстояние {ore['distance']:.3f} м"
            )

        # ... (your script)
        print("=== НАСТРОЙКА ===")
        drill.set_script_controlled(True)
        time.sleep(0.7)

        drill.run_action("OnOff_On")
        time.sleep(0.3)

        drill.set_property("Drill.WorkMode", 2)  # Force Collect (1)
        time.sleep(0.7)

        drill.set_property("CollectIfIdle", True)
        drill.set_property("UseConveyor", True)
        time.sleep(0.5)

        # Правильный фильтр for Collect
        drill.set_collect_filter([ORE_TYPE])
        time.sleep(0.8)

        # Enable Stone for Snow mining (if needed for Ice)
        drill.send_command({
            "cmd": "set",
            "payload": {"property": "Drill.SetCollectEnabled", "value": [0, True]}  # Stone = 0
        })

        # Увеличиваем зону
        for _ in range(10):
            drill.run_action("AreaWidth_Increase")
            drill.run_action("AreaHeight_Increase")
            drill.run_action("AreaDepth_Increase")
        drill.set_show_area(True)
        time.sleep(0.5)

        # Пик цели — use PickDrillTarget_1 for first
        drill.run_action("PickDrillTarget_1")
        time.sleep(1.0)

        drill.run_action("Work_On")

        # Читаем руды
        visible = parse_visible_ores(drill.telemetry)
        print("=== ВИДИМЫЕ РУДЫ ===")
        for ore in visible:
            print(f"- {ore['type']}: объём {ore['volume']}, расстояние {ore['distance']}м")

        # Цикл
        for i in range(3):
            time.sleep(10)
            drill.update()
            drill.wait_for_telemetry(timeout=5)
            drill.run_action("Work_On")
            print(f"Прогресс {i + 1}/3")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
