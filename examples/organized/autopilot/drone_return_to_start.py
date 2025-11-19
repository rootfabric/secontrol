"""Скрипт для возврата летящего дрона до точки старта с парковкой.

При старте запоминает позицию и ориентацию грида с радара,
затем ждет нажатия клавиши. После нажатия использует автопилот
для возврата к стартовой точке и паркует грид.
"""

import math
import time
from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.cockpit_device import CockpitDevice

MIN_DISTANCE = 0.5  # Минимальное расстояние до стартовой точки для завершения


def main() -> None:
    grid = prepare_grid("110178923215948443")

    try:
        # Найти радар
        detectors = grid.find_devices_by_type("ore_detector")
        if not detectors:
            print("Радары не найдены на гриде.")
            return
        detector = detectors[0]
        print(f"Найден радар: {detector.name} (id={detector.device_id})")

        # Найти remote control
        remotes = grid.find_devices_by_type("remote_control")
        if not remotes:
            print("Удаленное управление не найдено на гриде.")
            return
        remote = remotes[0]
        print(f"Найден remote control: {remote.name} (id={remote.device_id})")

        # Найти кабинет на гриде
        cockpits = grid.find_devices_by_type("cockpit")
        if not cockpits:
            print("Кабинеты не найдены на гриде.")
            return
        cockpit: CockpitDevice = cockpits[0]
        print(f"Найден кабинет: {cockpits[0].name} (id={cockpits[0].device_id})")

        print(cockpit.telemetry)

        # Скан радара для получения начальной позиции
        # detector.scan(include_grids=True, include_players=False, include_voxels=False, radius=1000)

        # while True:
        #     cockpit.update()
        #     time.sleep(0.1)

        start_pos = (cockpit.telemetry['position']['x'], cockpit.telemetry['position']['y'], cockpit.telemetry['position']['z'])
        start_forward = cockpit.telemetry['orientation']['forward']


        if not start_pos or not start_forward:
            print("Не удалось получить начальную позицию и ориентацию грида.")
            return

        print(f"Запомнена стартовая позиция: {start_pos}")
        print(f"Запомнена ориентация: {start_forward}")

        # Ждать нажатия клавиши
        input("Нажмите Enter для возврата к стартовой точке...")

        # Создать GPS строку для goto
        x, y, z = start_pos
        gps = f"GPS:Return:{x:.6f}:{y:.6f}:{z:.6f}:"
        print(f"Отправляем дрон на {gps}")

        remote.set_mode()
        # Включить автопилот и отправить к точке с минимальной скоростью
        remote.goto(gps, speed=1.1)

        # Отслеживать приближение к стартовой точке через телеметрию кабинета
        print("Отслеживаем подлет к стартовой точке...")

        arrived = False

        while not arrived:
            cockpit.update()
            cockpit.wait_for_telemetry()
            current_pos = (cockpit.telemetry['position']['x'], cockpit.telemetry['position']['y'], cockpit.telemetry['position']['z'])
            distance = math.sqrt(sum((c - s)**2 for c, s in zip(current_pos, start_pos)))
            print(f"Расстояние до стартовой точки: {distance:.2f}")
            if distance <= MIN_DISTANCE:
                arrived = True
                print("Подлетели к стартовой точке.")

                # Парковать грид
                # grid.park_on()

                # Отключить автопилот
                remote.disable()

                # if remote.name:
                #     remote.send_command({"targetName": remote.name})

                print("Дрон запаркован и автопилот отключен.")
                break
            time.sleep(1)  # Интервал проверки

    finally:
        close(grid)


if __name__ == "__main__":
    main()
