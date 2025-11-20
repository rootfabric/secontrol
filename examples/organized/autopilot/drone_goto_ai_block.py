"""
Тест AI Flight Autopilot:
1. Запоминаем стартовую позицию и up-ориентацию грида по кокпиту.
2. Считаем точку на 50 м вверх.
3. По Enter отлетаем на 50 м вверх через AI Flight (waypoint + автопилот).
4. По Enter возвращаемся точно в стартовую точку, контролируя расстояние
   и вручную выключая автопилот, когда дрон достаточно близко.
"""

import math
import time
from typing import Tuple

from secontrol.common import prepare_grid, close
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.ai_device import AiFlightAutopilotDevice


# Настройки точности и поведения
UNLOCK_OFFSET_METERS = 50.0   # на сколько подниматься "вверх"
ARRIVAL_DISTANCE = 0.3        # в метрах — считаем точку достигнутой
CHECK_INTERVAL = 0.2          # период проверки, секунды
MAX_FLIGHT_TIME = 300.0       # защитный таймаут на один перелёт, сек


def distance(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def add_scaled(
    base: Tuple[float, float, float],
    direction: Tuple[float, float, float],
    scale: float,
) -> Tuple[float, float, float]:
    return (
        base[0] + direction[0] * scale,
        base[1] + direction[1] * scale,
        base[2] + direction[2] * scale,
    )


def get_position(cockpit: CockpitDevice) -> Tuple[float, float, float]:
    t = cockpit.telemetry
    p = t["position"]
    return float(p["x"]), float(p["y"]), float(p["z"])


def get_up_vector(cockpit: CockpitDevice) -> Tuple[float, float, float]:
    t = cockpit.telemetry
    ori = t.get("orientation") or {}
    up = ori.get("up")
    if not up:
        raise RuntimeError("Cockpit telemetry does not contain orientation.up")
    return float(up["x"]), float(up["y"]), float(up["z"])


def fly_to(
    ai_flight: AiFlightAutopilotDevice,
    cockpit: CockpitDevice,
    target_pos: Tuple[float, float, float],
    *,
    speed_limit: float,
    waypoint_name: str,
    arrival_distance: float = ARRIVAL_DISTANCE,
    max_time: float = MAX_FLIGHT_TIME,
    use_precision: bool = False,
) -> None:
    """
    Общая функция перелёта к точке:
    - настраивает AI Flight (скорость, collision avoidance, precision),
    - создаёт waypoint на target_pos,
    - включает автопилот,
    - по телеметрии кокпита контролирует расстояние и отключает автопилот,
      когда дрон достаточно близко.
    """

    x, y, z = target_pos
    print(
        f"[fly_to] target={waypoint_name} "
        f"({x:.3f}, {y:.3f}, {z:.3f}), speed_limit={speed_limit:.2f}, "
        f"precision={use_precision}"
    )

    # Базовая настройка миссии / autopilot
    ai_flight.clear_waypoints()
    ai_flight.set_speed_limit(speed_limit)
    # Для тестов удобнее collision avoidance выключить, чтобы он не увиливал
    ai_flight.set_collision_avoidance(False)
    ai_flight.set_terrain_follow(False)
    ai_flight.set_mode("oneway")

    # Опционально включаем precision/docking режим, если он реализован
    if use_precision and hasattr(ai_flight, "enable_precision"):
        try:
            ai_flight.enable_precision()
        except Exception as exc:  # pragma: no cover - защитный код
            print(f"[fly_to] enable_precision error: {exc}")

    # Добавляем waypoint в целевую точку
    ai_flight.add_waypoint(
        {"x": x, "y": y, "z": z},
        speed=speed_limit,
        name=waypoint_name,
    )

    # Включаем автопилот
    ai_flight.enable_autopilot()

    start_time = time.time()
    last_print = start_time

    while True:
        now = time.time()
        if now - start_time > max_time:
            print(f"[fly_to] TIMEOUT after {max_time} s, disabling autopilot")
            ai_flight.disable_autopilot()
            break

        cockpit.update()
        ai_flight.update()
        cockpit.wait_for_telemetry()
        ai_flight.wait_for_telemetry()

        current_pos = get_position(cockpit)
        d = distance(current_pos, target_pos)

        # В телеметрии AI-блока можно повесить флаг "autopilotEnabled",
        # если ты его добавишь — здесь можно его читать. Пока считаем,
        # что если не долетели до arrival_distance, мы продолжаем.
        if now - last_print >= 1.0:
            print(
                f"[fly_to] {waypoint_name}: "
                f"distance={d:.3f} m"
            )
            last_print = now

        if d <= arrival_distance:
            print(
                f"[fly_to] reached {waypoint_name}, "
                f"distance={d:.4f} m — disabling autopilot"
            )
            ai_flight.disable_autopilot()
            break

        time.sleep(CHECK_INTERVAL)


def main() -> None:
    # Пример: конкретный gridId; при необходимости поменяешь на свой
    # Для теста используем известный grid_id из телеметрии
    grid = prepare_grid("Owl")

    try:
        # Ищем кокпит
        cockpits = grid.find_devices_by_type("cockpit")
        if not cockpits:
            print("Cockpit not found on grid")
            return
        cockpit: CockpitDevice = cockpits[0]
        print(f"Cockpit: {cockpit.name} (id={cockpit.device_id})")

        # Ищем AI Flight Autopilot блок
        ai_flights = grid.find_devices_by_type(AiFlightAutopilotDevice.device_type)
        if not ai_flights:
            print("AI Flight Autopilot block not found on grid")
            return
        ai_flight: AiFlightAutopilotDevice = ai_flights[0]
        print(f"AI Flight: {ai_flight.name} (id={ai_flight.device_id})")

        # Берём актуальную телеметрию
        cockpit.update()
        cockpit.wait_for_telemetry()

        start_pos = get_position(cockpit)
        up_vec = get_up_vector(cockpit)
        undock_pos = add_scaled(start_pos, up_vec, UNLOCK_OFFSET_METERS)

        print(f"Start position:    ({start_pos[0]:.3f}, {start_pos[1]:.3f}, {start_pos[2]:.3f})")
        print(f"Up vector:         ({up_vec[0]:.3f}, {up_vec[1]:.3f}, {up_vec[2]:.3f})")
        print(f"Undock target pos: ({undock_pos[0]:.3f}, {undock_pos[1]:.3f}, {undock_pos[2]:.3f})")

        input("Нажмите Enter, чтобы ОТЛЕТЕТЬ на 50 м вверх...")

        # 1. Отлёт наверх на 50 м (можно быстрее, без precision)
        fly_to(
            ai_flight=ai_flight,
            cockpit=cockpit,
            target_pos=undock_pos,
            speed_limit=5.0,
            waypoint_name="Undock_Up50",
            use_precision=False,
        )

        input("Нажмите Enter, чтобы ВЕРНУТЬСЯ ТОЧНО в стартовую точку...")

        # 2. Возврат обратно с включённой точностью и маленькой скоростью
        fly_to(
            ai_flight=ai_flight,
            cockpit=cockpit,
            target_pos=start_pos,
            speed_limit=1.5,
            waypoint_name="Return_Start",
            use_precision=True,
        )

        print("Последовательность завершена.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
