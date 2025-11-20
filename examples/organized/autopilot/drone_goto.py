"""
Сценарий:
1. Запоминаем стартовую позицию и ориентацию грида по телеметрии кокпита.
2. Считаем точку "выше" на 50 м по локальному up кокпита.
3. Команда "отлететь": автопилот уводит грид в эту точку.
4. Команда "вернуться": автопилот в точном режиме (dock=True) возвращает грид обратно.

При этом Python следит за расстоянием до целевой точки и мягко отключает автопилот,
когда грид достаточно близко — этого уровня точности обычно хватает для стыковки коннектора.
"""

import math
import time
from typing import Tuple

from secontrol.common import close, prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.cockpit_device import CockpitDevice

# Настройки точности и таймаутов
MIN_DISTANCE = 0.3           # метров — считаем точку достигнутой
UNLOCK_OFFSET_METERS = 50.0  # подъём "наверх" при отлёте
MAX_FLIGHT_TIME = 300.0      # секунд на манёвр
CHECK_INTERVAL = 0.2         # секунд между проверками


def vec_from_orientation(d: dict) -> Tuple[float, float, float]:
    return float(d["x"]), float(d["y"]), float(d["z"])


def get_position(cockpit: CockpitDevice) -> Tuple[float, float, float]:
    t = cockpit.telemetry
    p = t["position"]
    return float(p["x"]), float(p["y"]), float(p["z"])


def get_up_vector(cockpit: CockpitDevice) -> Tuple[float, float, float]:
    ori = cockpit.telemetry.get("orientation") or {}
    up = ori.get("up")
    if not up:
        raise RuntimeError("Cockpit telemetry does not contain orientation.up")
    return vec_from_orientation(up)


def add_scaled(a: Tuple[float, float, float],
               b: Tuple[float, float, float],
               scale: float) -> Tuple[float, float, float]:
    return (
        a[0] + b[0] * scale,
        a[1] + b[1] * scale,
        a[2] + b[2] * scale,
    )


def distance(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def fly_to(
    remote: RemoteControlDevice,
    cockpit: CockpitDevice,
    target_pos: Tuple[float, float, float],
    *,
    speed: float,
    gps_name: str,
    dock: bool,
    arrival_distance: float = MIN_DISTANCE,
    max_time: float = MAX_FLIGHT_TIME,
) -> None:
    """
    Общая функция перелёта:
    - ставит режим one-way
    - отправляет remote_goto с нужной скоростью и флагом dock
    - циклически проверяет расстояние и отключает автопилот, когда мы близко.
    """
    x, y, z = target_pos
    gps = f"GPS:{gps_name}:{x:.6f}:{y:.6f}:{z:.6f}:"

    print(f"[fly_to] target={gps}, dock={dock}, speed={speed:.2f}")

    # Страховка: режим one-way
    remote.set_mode("oneway")

    # Запускаем автопилот
    remote.goto(gps, speed=speed, gps_name=gps_name, dock=dock)

    start_time = time.time()
    last_print = start_time

    while True:
        now = time.time()
        if now - start_time > max_time:
            print(f"[fly_to] TIMEOUT {max_time} s, stopping autopilot")
            remote.disable()
            break

        cockpit.update()
        remote.update()

        cockpit.wait_for_telemetry()
        remote.wait_for_telemetry()

        current_pos = get_position(cockpit)
        d = distance(current_pos, target_pos)
        autopilot_enabled = bool(remote.telemetry.get("autopilotEnabled", False))

        if now - last_print >= 1.0:
            print(
                f"[fly_to] {gps_name}: distance={d:.2f} m, "
                f"autopilot={'on' if autopilot_enabled else 'off'}"
            )
            last_print = now

        # Достигли нужной точки
        if d <= arrival_distance:
            print(f"[fly_to] reached {gps_name}, distance={d:.3f} m")
            if autopilot_enabled:
                remote.disable()
            break

        # Если автопилот неожиданно выключился раньше — выходим, чтобы не улететь далеко.
        if not autopilot_enabled and d > arrival_distance:
            print(
                f"[fly_to] autopilot turned off early, "
                f"distance={d:.2f} m — leaving as is"
            )
            break

        time.sleep(CHECK_INTERVAL)


def main() -> None:
    # TODO: при желании можно вынести id грида в ENV / аргументы
    grid = prepare_grid("110178923215948443")

    try:
        remotes = grid.find_devices_by_type("remote_control")
        if not remotes:
            print("Remote Control not found on grid")
            return
        remote: RemoteControlDevice = remotes[0]
        print(f"Remote control: {remote.name} (id={remote.device_id})")

        cockpits = grid.find_devices_by_type("cockpit")
        if not cockpits:
            print("Cockpit not found on grid")
            return
        cockpit: CockpitDevice = cockpits[0]
        print(f"Cockpit: {cockpit.name} (id={cockpit.device_id})")

        # первая телеметрия
        cockpit.update()
        cockpit.wait_for_telemetry()

        start_pos = get_position(cockpit)
        up_vec = get_up_vector(cockpit)
        undock_pos = add_scaled(start_pos, up_vec, UNLOCK_OFFSET_METERS)

        print(f"Start position: {start_pos}")
        print(f"Up vector:      {up_vec}")
        print(f"Undock target:  {undock_pos}")

        input("Нажмите Enter, чтобы ОТЛЕТЕТЬ на 50 м вверх...")

        # Отлёт на 50 м вверх (dock=False, обычный режим)
        fly_to(
            remote,
            cockpit,
            undock_pos,
            speed=3.0,
            gps_name="Undock",
            dock=False,
        )

        input("Нажмите Enter, чтобы ВЕРНУТЬСЯ на стартовую точку...")

        # Возврат обратно в точном режиме (dock=True)
        fly_to(
            remote,
            cockpit,
            start_pos,
            speed=1.5,
            gps_name="Return",
            dock=True,
        )

        print("Последовательность завершена.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
