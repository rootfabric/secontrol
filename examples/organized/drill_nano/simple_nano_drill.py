from __future__ import annotations

import time

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice


GRID_NAME = "taburet2"


def main() -> None:
    grid = Grid.from_name(GRID_NAME)
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)

    if not drills:
        raise RuntimeError("Nanobot Drill System devices were not found")

    for index, item in enumerate(drills):
        print(
            f"{index}: "
            f"name={item.name!r}, "
            f"device_id={item.device_id}, "
            f"telemetry_key={item.telemetry_key}"
        )

    drill = drills[0]

    print()
    print("Selected drill:")
    print("name:", drill.name)
    print("device_id:", drill.device_id)

    sent = 0

    try:
        sent += drill.turn_off()
        time.sleep(0.3)
    except Exception as exc:
        print("turn_off failed:", exc)

    # Включаем script control только на время применения delegate-фильтров.
    sent += drill.set_script_controlled(True)
    time.sleep(0.2)

    # ВАЖНО:
    # Не all. all разрешает подбирать плавающий камень.
    # Ice в SE является Ore/Ice, поэтому оставляем только Ore-класс.
    sent += drill.set_collect_filter(["Ore"])

    # Только материал Ice, режим Collect.
    sent += drill.set_ore_filters(["Ice"], work_mode="Collect")

    # Дублируем режим, чтобы точно не остался Drill.
    sent += drill.set_work_mode("Collect")

    time.sleep(0.2)

    # Отключаем script control, чтобы мод сам выбирал цель.
    sent += drill.set_script_controlled(False)

    try:
        sent += drill.set_script_controlled_action(False)
    except Exception as exc:
        print("ScriptControlled_Off action failed:", exc)

    time.sleep(0.2)

    sent += drill.set_work_mode("Collect")
    sent += drill.turn_on()

    print()
    print("sent:", sent)

    time.sleep(1.0)

    print()
    print("After:")
    print("work mode:", drill.get_work_mode())
    print("priority:", drill.debug_get_priority_list_raw())
    print("known ores:", drill.debug_get_enabled_known_ores())
    print("status:", drill.debug_status())


if __name__ == "__main__":
    main()