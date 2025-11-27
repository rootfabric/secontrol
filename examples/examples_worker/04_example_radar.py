"""Код для отслеживания игрока радаром и управления ровером с использованием move_to_point.

Запускает скан радара, получает телеметрию, извлекает положение игрока и ровера,
вычисляет расстояние, и если > MIN_DISTANCE, использует move_to_point для движения к игроку.
Если <= MIN_DISTANCE, останавливается.
"""

import math
import time
from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.rover_device import RoverDevice

# Настройки поведения ровера
MIN_DISTANCE = 20.0  # Минимальное расстояние до игрока для начала движения


class App:
    def __init__(self, grid):
        self.grid = grid
        self.grid = prepare_grid(grid.name)
        import os

        url = os.getenv("REDIS_URL")
        print("REDIS_URL =", url)
        print("REDIS_USERNAME =", os.getenv("REDIS_USERNAME"))
        print("REDIS_PASSWORD set =", bool(os.getenv("REDIS_PASSWORD")))


        # Найти радар
        detectors = grid.find_devices_by_type("ore_detector")
        if not detectors:
            print("Радары не найдены на гриде.")
            return
        self.detector = detectors[0]
        print(f"Найден радар: {self.detector.name} (id={self.detector.device_id})")

        # Инициализировать ровера
        self.rover = RoverDevice(grid)
        print(f"Найдено колес: {len(self.rover.wheels)}")

        print("Скан запущен. Ожидание телеметрии... (Ctrl+C для выхода)")

    def _on_radar_telemetry(self, device, telemetry, source_event):
        """Callback для обработки новой телеметрии от радара."""
        print(f"Новое событие телеметрии от радара {device.name}:")
        print(f"Источник события: {source_event}")
        print(f"Телеметрия: {telemetry}")
        print("---")

    def start(self):
        print("Started!")
        # Подписываемся на события телеметрии радара
        self.detector.on("telemetry", self._on_radar_telemetry)

    def step(self):
        self.detector.scan(include_players=True, include_grids=True, include_voxels=False, radius=500)

        print("-------------------------")
        # print(self.detector.telemetry)

        contacts = self.detector.contacts()
        # print(contacts)
        # for contact in contacts:
        #     # print(contact)
        #     print(contact['name'])
        # return



def main() -> None:
    grid = prepare_grid("Respawn Rover")

    try:
        app = App(grid)
        app.start()
        while True:
            app.step()
            time.sleep(1)  # Интервал сканирования

    except KeyboardInterrupt:
        print("Выход...")
    finally:
        # Отписываемся от телеметрии радара
        try:
            app.detector.off("telemetry", app._on_radar_telemetry)
        except Exception:
            pass
        close(grid)


if __name__ == "__main__":
    main()
