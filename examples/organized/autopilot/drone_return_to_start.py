"""Скрипт для возврата летящего дрона до точки старта с парковкой.

При старте запоминает позицию и ориентацию грида с радара,
затем ждет нажатия клавиши. После нажатия использует автопилот
для возврата к стартовой точке и паркует грид.
"""

import time
from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


def main() -> None:
    grid = prepare_grid("108695511253435437")

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

        # Скан радара для получения начальной позиции
        detector.scan(include_grids=True, include_players=False, include_voxels=False, radius=1000)

        start_pos = None
        start_forward = None

        contacts = detector.contacts()
        for contact in contacts:
            if contact.get("type") == "grid" and contact.get("id") == int(grid.grid_id):
                start_pos = contact["position"]
                start_forward = contact["forward"]
                break

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

        # Включить автопилот и отправить к точке с минимальной скоростью
        remote.goto(gps, speed=0.1)

        # Ждать завершения полета (примерно, т.к. точное время неизвестно)
        print("Ждем прибытия...")
        time.sleep(10)  # Настроить в зависимости от расстояния и скорости

        # Парковать грид
        grid.park_on()

        # Отключить автопилот
        remote.send_command({
            "cmd": "remote_control",
            "state": "autopilot_disabled",
            "targetId": int(remote.device_id),
        })
        if remote.name:
            remote.send_command({"targetName": remote.name})

        print("Дрон запаркован и автопилот отключен.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
