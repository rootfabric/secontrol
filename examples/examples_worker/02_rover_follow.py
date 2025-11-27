"""Пример: скан радара, вывод телеметрии и движение ровера к игроку."""

import math
import time


from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice  # noqa: F401 (на будущее)
from secontrol.devices.rover_device import RoverDevice

# Настройки поведения ровера
MIN_DISTANCE = 20.0  # Минимальное расстояние до игрока для начала движения


class App:
    def __init__(self, grid):
        # Если нам передали уже подготовленный grid-объект — используем его как есть.
        # Если строку (имя/ID грида) — резолвим через prepare_grid.

        self.grid = prepare_grid(grid)


        # Найти радар
        detectors = self.grid.find_devices_by_type("ore_detector")
        if not detectors:
            raise RuntimeError("Радары не найдены на гриде.")
        self.detector = detectors[0]
        print(f"Найден радар: {self.detector.name} (id={self.detector.device_id})")

        # Инициализировать ровера
        self.rover = RoverDevice(self.grid)
        print(f"Найдено колес: {len(self.rover.wheels)}")

        print("Скан запущен. Ожидание телеметрии... (Ctrl+C для выхода)")

        self._last_ts = None

    def start(self):
        print("Started!")

    def step(self):
        # Запустить скан радара
        self.detector.scan(
            include_players=True,
            include_grids=True,
            include_voxels=False,
            radius=500,
        )

        telemetry = self.detector.telemetry or {}
        radar = telemetry.get("radar") or {}

        # Пытаемся взять контакты из телеметрии; если вдруг их нет — fallback на detector.contacts()
        contacts = radar.get("contacts")
        if not contacts:
            contacts = self.detector.contacts() or []

        # ---- Логика движения к игроку на основе contacts ----
        player_pos = None
        rover_pos = None
        rover_forward = None
        rover_speed = 0.0

        owner_str = str(getattr(self.grid, "owner_id", ""))

        for contact in contacts:
            c_type = contact.get("type")
            if c_type == "player" and str(contact.get("ownerId")) == owner_str:
                player_pos = contact.get("position")

            if c_type == "player" and str(contact.get("ownerId")) == "144115188075855924":
                player_pos = contact.get("position")

            elif c_type == "grid" and contact.get("name") == self.grid.name:
                rover_pos = contact.get("position")
                rover_forward = contact.get("forward")
                rover_speed = contact.get("speed", 0.0)

        if player_pos and rover_pos and rover_forward:
            # Вычислить вектор от ровера к игроку
            vector_to_player = [p - r for p, r in zip(player_pos, rover_pos)]
            distance = math.sqrt(sum(v ** 2 for v in vector_to_player))

            # print(f"Положение игрока: {player_pos}")
            # print(f"Положение ровера: {rover_pos}")
            # print(f"Форвард ровера: {rover_forward}")
            # print(f"Вектор на игрока: {vector_to_player}")
            print(f"Расстояние: {distance:.2f} м")
            print(f"Скорость ровера: {rover_speed:.3f} м/с")

            if distance > MIN_DISTANCE:
                # Регулировка скорости в зависимости от расстояния и текущей скорости
                if distance < 50 and rover_speed > 10:
                    self.rover._max_speed = 0.005
                elif rover_speed < 2:
                    self.rover._max_speed = 0.05
                else:
                    self.rover._max_speed = 0.04

                if not getattr(self.rover, "_is_moving", False):
                    print("Движение к игроку...")
                    self.rover.move_to_point(player_pos, min_distance=MIN_DISTANCE)

                # Обновляем цель, если игрок смещается
                self.rover.update_target(player_pos)

                # Толчок, если скорость почти нулевая
                if getattr(self.rover, "_is_moving", False) and rover_speed < 0.1:
                    print("Толчок для старта...")
                    self.rover.drive(1.0, 0.0)
                    time.sleep(0.5)
            else:
                print("Близко к игроку, остановка.")
                self.rover.stop()
                self.rover.park_on()
                self.rover._is_moving = False
        else:
            print("Не удалось получить позиции игрока или ровера.")

    def close(self):
        close(self.grid)


def main() -> None:
    # Локальный запуск по имени грида
    grid = prepare_grid("Respawn Rover")

    app = App(grid)
    try:
        app.start()
        while True:
            app.step()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Выход...")
    finally:
        app.close()


if __name__ == "__main__":
    main()
