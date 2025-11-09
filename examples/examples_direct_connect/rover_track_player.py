"""Код для отслеживания игрока радаром и управления ровером.

Запускает скан радара, получает телеметрию, извлекает положение игрока и ровера,
вычисляет вектор к игроку, принтует его и управляет движением ровера:
- Если расстояние > 20м, поворачивает к игроку и движется вперед.
- Если <= 20м, останавливается.
"""

import math
import time
from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.rover_device import RoverDevice

# Настройки поведения ровера
MIN_DISTANCE = 20.0  # Минимальное расстояние до игрока
BASE_SPEED = 0.005     # Базовая скорость
SPEED_FACTOR = 0.05  # Коэффициент увеличения скорости с расстоянием
MAX_SPEED = .015      # Максимальная скорость
STEERING_GAIN = 2.5  # Коэффициент усиления руления


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

        # Функция обработки телеметрии
        def on_telemetry(dev: OreDetectorDevice, telemetry: dict, event: str) -> None:
            radar = telemetry.get("radar")
            if not radar:
                return

            contacts = radar.get("contacts", [])
            player_pos = None
            rover_pos = None
            rover_forward = None

            for contact in contacts:
                if contact.get("type") == "player" and contact.get("name") == "root":
                    player_pos = contact["position"]
                elif contact.get("type") == "grid" and contact.get("name") == "Respawn Rover":
                    rover_pos = contact["position"]
                    rover_forward = contact["forward"]

            if player_pos and rover_pos and rover_forward:
                # Вычислить вектор от ровера к игроку
                vector_to_player = [p - r for p, r in zip(player_pos, rover_pos)]
                distance = math.sqrt(sum(v**2 for v in vector_to_player))
                print(f"Положение игрока: {player_pos}")
                print(f"Положение ровера: {rover_pos}")
                print(f"Форвард ровера: {rover_forward}")
                print(f"Вектор на игрока: {vector_to_player}")
                print(f"Расстояние: {distance}")

                if distance > MIN_DISTANCE:
                    rover.park_off()
                    # Вычислить скорость: увеличивается с расстоянием
                    speed = min(MAX_SPEED, BASE_SPEED + (distance - MIN_DISTANCE) * SPEED_FACTOR)
                    # Нормализовать вектор к игроку (только X и Z, игнорируя Y)
                    dir_to_player = [vector_to_player[0], 0, vector_to_player[2]]
                    dir_length = math.sqrt(sum(d**2 for d in dir_to_player))
                    if dir_length > 0:
                        dir_norm = [d / dir_length for d in dir_to_player]
                    else:
                        dir_norm = [1, 0, 0]  # fallback

                    # Нормализовать форвард ровера (только X и Z)
                    forward_horiz = [rover_forward[0], 0, rover_forward[2]]
                    forward_length = math.sqrt(sum(f**2 for f in forward_horiz))
                    if forward_length > 0:
                        forward_norm = [f / forward_length for f in forward_horiz]
                    else:
                        forward_norm = [1, 0, 0]  # fallback

                    # Вычислить угол между форвардом и направлением к игроку
                    dot = sum(a*b for a,b in zip(dir_norm, forward_norm))
                    cross = dir_norm[0]*forward_norm[2] - dir_norm[2]*forward_norm[0]
                    angle = math.atan2(cross, dot)

                    # Нормализовать steering к -1..1 (предполагая max угол pi/2)
                    steering = max(-1, min(1, angle / (math.pi / 2)))
                    # Усилить руление
                    steering *= STEERING_GAIN
                    steering = max(-1, min(1, steering))

                    print(f"Угол: {math.degrees(angle):.2f}°, Steering: {steering:.2f}, Speed: {speed:.2f}")
                    rover.drive(speed, -steering)
                else:
                    print("Близко к игроку, остановка.")
                    rover.stop()
                    rover.park_on()

        # Подписаться на телеметрию
        detector.on("telemetry", on_telemetry)

        # Запустить скан
        detector.scan(include_players=True, include_grids=True, include_voxels=False, radius=500)
        print("Скан запущен. Ожидание телеметрии... (Ctrl+C для выхода)")

        # Цикл для периодического сканирования
        while True:
            time.sleep(1)  # Интервал сканирования
            detector.scan(include_players=True, include_grids=True, include_voxels=False, radius=500)

    except KeyboardInterrupt:
        print("Выход...")
    finally:
        detector.off("telemetry", on_telemetry)
        close(grid)


if __name__ == "__main__":
    main()
