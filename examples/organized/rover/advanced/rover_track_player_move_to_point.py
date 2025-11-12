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


def main() -> None:
    grid = prepare_grid()

    try:
        # Найти радар
        detectors = grid.find_devices_by_type("ore_detector")
        if not detectors:
            print("Радары не найдены на гриде.")
            return
        detector = detectors[0]
        print(f"Найден радар: {detector.name} (id={detector.device_id})")

        # Инициализировать ровера
        rover = RoverDevice(grid)
        print(f"Найдено колес: {len(rover.wheels)}")

        print("Скан запущен. Ожидание телеметрии... (Ctrl+C для выхода)")

        #толкнуть

        # Цикл для периодического сканирования и движения
        while True:
            detector.scan(include_players=True, include_grids=True, include_voxels=False, radius=500)

            contacts = detector.contacts()
            player_pos = None
            rover_pos = None
            rover_forward = None

            rover_speed = 0.0
            for contact in contacts:
                if contact.get("type") == "player" and str(contact.get("ownerId")) == grid.owner_id:
                    player_pos = contact["position"]
                elif contact.get("type") == "grid" and contact.get("name") == "Respawn Rover":
                    rover_pos = contact["position"]
                    rover_forward = contact["forward"]
                    rover_speed = contact.get("speed", 0.0)

            if player_pos and rover_pos and rover_forward:
                # Вычислить вектор от ровера к игроку
                vector_to_player = [p - r for p, r in zip(player_pos, rover_pos)]
                distance = math.sqrt(sum(v**2 for v in vector_to_player))
                print(f"Положение игрока: {player_pos}")
                print(f"Положение ровера: {rover_pos}")
                print(f"Форвард ровера: {rover_forward}")
                print(f"Вектор на игрока: {vector_to_player}")
                print(f"Расстояние: {distance}")
                print(f"Скорость ровера: {rover_speed}")

                if distance > MIN_DISTANCE:
                    # Регулировка скорости
                    if distance < 50 and rover_speed > 10:
                        rover._max_speed = 0.005
                    elif rover_speed < 2:
                        rover._max_speed = 0.05
                    else:
                        rover._max_speed = 0.04

                    if not rover._is_moving:
                        print("Движение к игроку...")
                        rover.move_to_point(player_pos, min_distance=MIN_DISTANCE)
                    rover.update_target(player_pos)

                    # Толчок, если скорость нулевая
                    if rover._is_moving and rover_speed < 0.1:
                        print("Толчок для старта...")
                        rover.drive(1, 0.0)
                        time.sleep(0.5)
                else:
                    print("Близко к игроку, остановка.")
                    rover.stop()
                    rover.park_on()
                    rover._is_moving = False
            else:
                print("Не удалось получить позиции игрока или ровера.")

            time.sleep(1)  # Интервал сканирования

    except KeyboardInterrupt:
        print("Выход...")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
