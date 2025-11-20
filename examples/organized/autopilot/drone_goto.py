
"""
Сценарий:
1. Запоминаем стартовую позицию REMOTE CONTROL и направление "вверх" по гравитации (если есть планета).
2. Считаем точку "выше" на 50 м относительно позиции REMOTE CONTROL.
3. Команда "отлететь": автопилот ведёт REMOTE CONTROL в эту точку.
4. Команда "вернуться": автопилот возвращает REMOTE CONTROL в исходную точку.

Расстояние считаем по позиции REMOTE CONTROL, а не кокпита.

Дополнительно:
- если расстояние до точки > 10 м, используем более высокую скорость;
- если <= 10 м — используем меньшую скорость для точного подлёта.
"""

import math
import time
from typing import Tuple

from secontrol.common import close, prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.cockpit_device import CockpitDevice

# Настройки точности и таймаутов
MIN_DISTANCE = 0.1           # "идеальная" точность (м)
UNLOCK_OFFSET_METERS = 50.0  # подъём "наверх" при отлёте
MAX_FLIGHT_TIME = 300.0      # секунд на манёвр
CHECK_INTERVAL = 0.2         # секунд между проверками
AUTOPILOT_ARM_TIME = 2.0     # секунд — дать автопилоту "завестись"

# Допуск, если RC сам выключил автопилот и решил, что прилетел
RC_STOP_TOLERANCE = 10.0     # м — считаем "прилетели достаточно близко"

# Порог изменения расстояния, ниже которого считаем, что "застряли"
STUCK_EPS = 0.05             # м
STUCK_TICKS = 30             # ~6 сек при CHECK_INTERVAL=0.2

# Порог для выбора скорости: дальше/ближе этой дистанции
SPEED_DISTANCE_THRESHOLD = 10.0  # м


def vec_from_orientation(d: dict) -> Tuple[float, float, float]:
    return float(d["x"]), float(d["y"]), float(d["z"])


def get_cockpit_up(cockpit: CockpitDevice) -> Tuple[float, float, float]:
    ori = cockpit.telemetry.get("orientation") or {}
    up = ori.get("up")
    if not up:
        raise RuntimeError("Cockpit telemetry does not contain orientation.up")
    return vec_from_orientation(up)


def get_remote_position(remote: RemoteControlDevice) -> Tuple[float, float, float]:
    t = remote.telemetry
    pos = t.get("position")
    if not pos:
        raise RuntimeError(
            "Remote telemetry does not contain position (x/y/z). "
            "Проверь, что в плагине RemoteControlDevice.GetTelemetryAsync добавлено поле position."
        )
    return float(pos["x"]), float(pos["y"]), float(pos["z"])


def get_remote_planet_position(remote: RemoteControlDevice) -> Tuple[float, float, float] | None:
    """
    planetPosition мы добавляли в телеметрию как массив [x, y, z].
    Если планеты рядом нет или TryGetPlanetPosition вернуло false — поля может не быть.
    """
    t = remote.telemetry
    pp = t.get("planetPosition")
    if pp is None:
        return None

    try:
        return float(pp[0]), float(pp[1]), float(pp[2])
    except Exception:
        return None


def get_cockpit_position(cockpit: CockpitDevice) -> Tuple[float, float, float]:
    t = cockpit.telemetry
    pos = t.get("position")
    if not pos:
        raise RuntimeError("Cockpit telemetry does not contain position (x/y/z)")
    return float(pos["x"]), float(pos["y"]), float(pos["z"])


def normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-6:
        raise ValueError("cannot normalize zero-length vector")
    return x / length, y / length, z / length


def add_scaled(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
    scale: float,
) -> Tuple[float, float, float]:
    return (
        a[0] + b[0] * scale,
        a[1] + b[1] * scale,
        a[2] + b[2] * scale,
    )


def distance(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def fly_to(
    remote: RemoteControlDevice,
    target_pos: Tuple[float, float, float],
    *,
    speed_far: float,
    speed_near: float,
    gps_name: str,
    dock: bool,
    arrival_distance: float = MIN_DISTANCE,
    rc_stop_tolerance: float = RC_STOP_TOLERANCE,
    max_time: float = MAX_FLIGHT_TIME,
) -> None:
    """
    Общая функция перелёта:
    - измеряет стартовое расстояние до цели;
      * если > SPEED_DISTANCE_THRESHOLD → берём speed_far,
      * иначе → speed_near.
    - ставит режим one-way;
    - отправляет remote_goto с выбранной скоростью и флагом dock;
    - даёт автопилоту немного времени "завестись";
    - циклически проверяет расстояние (по позиции REMOTE CONTROL)
      и завершает, когда:
        * d <= arrival_distance  (идеальный сценарий)
        * ИЛИ RC сам выключил автопилот и d <= rc_stop_tolerance
        * ИЛИ расстояние почти не меняется долгое время (застряли).
    """
    # Сначала обновим телеметрию и измерим стартовую дистанцию
    remote.update()
    remote.wait_for_telemetry()
    current_pos = get_remote_position(remote)
    initial_d = distance(current_pos, target_pos)

    # Выбираем скорость в зависимости от расстояния
    if initial_d > SPEED_DISTANCE_THRESHOLD:
        speed = float(speed_far)
    else:
        speed = float(speed_near)

    x, y, z = target_pos
    gps = f"GPS:{gps_name}:{x:.6f}:{y:.6f}:{z:.6f}:"

    print(
        f"[fly_to] target={gps}, dock={dock}, "
        f"initial_distance={initial_d:.2f} m, chosen_speed={speed:.2f}"
    )


    # Страховка: режим one-way
    remote.set_mode("oneway")

    # Запускаем автопилот с выбранной скоростью
    remote.goto(gps, speed=speed, gps_name=gps_name, dock=dock)

    # Переменная для отслеживания текущей установленной скорости
    current_speed = speed

    # Даем автопилоту немного времени включиться и обновить телеметрию
    arm_start = time.time()
    while time.time() - arm_start < AUTOPILOT_ARM_TIME:
        remote.update()
        remote.wait_for_telemetry()
        time.sleep(0.1)

    start_time = time.time()
    last_print = start_time

    prev_d = None
    stuck_counter = 0

    while True:
        now = time.time()
        if now - start_time > max_time:
            print(f"[fly_to] TIMEOUT {max_time} s, stopping autopilot")
            remote.disable()
            break

        remote.update()
        remote.wait_for_telemetry()

        current_pos = get_remote_position(remote)
        d = distance(current_pos, target_pos)
        autopilot_enabled = bool(remote.telemetry.get("autopilotEnabled", False))

        # Детектор "застревания": расстояние почти не меняется
        if prev_d is not None:
            if abs(prev_d - d) < STUCK_EPS:
                stuck_counter += 1
            else:
                stuck_counter = 0
        prev_d = d

        if now - last_print >= 1.0:
            ship_speed = float(remote.telemetry.get("speed", 0.0))

            print(
                f"[fly_to] {gps_name}: distance={d:.2f} m, "
                f"autopilot={'on' if autopilot_enabled else 'off'}, "
                f"speed={ship_speed:.2f} m/s, "
                f"stuck_ticks={stuck_counter}, "
                f"RC_pos={current_pos} "

            )

            last_print = now

        # Динамическая смена скорости
        if d <= SPEED_DISTANCE_THRESHOLD:
            if current_speed != speed_near:
                print(f"[fly_to] {gps_name}: switching to near speed {speed_near:.2f}")
                remote.goto(gps, speed=speed_near, gps_name=gps_name, dock=dock)
                current_speed = speed_near
        else:
            if current_speed != speed_far:
                print(f"[fly_to] {gps_name}: switching to far speed {speed_far:.2f}")
                remote.goto(gps, speed=speed_far, gps_name=gps_name, dock=dock)
                current_speed = speed_far

        # Идеальный случай — сами по нашему порогу считаем точку достигнутой
        if d <= arrival_distance:
            print(f"[fly_to] reached {gps_name} (our threshold), distance={d:.3f} m")
            if autopilot_enabled:
                remote.disable()
            break

        # Если автопилот уже выключен, а мы не дошли до нашего порога —
        # смотрим, не в "допустимом" ли радиусе останова RC
        if not autopilot_enabled:
            if d <= rc_stop_tolerance:
                print(
                    f"[fly_to] RC disabled autopilot at distance={d:.3f} m "
                    f"(<={rc_stop_tolerance:.1f} m), treating as arrived."
                )
            else:
                print(
                    f"[fly_to] RC disabled autopilot early at distance={d:.3f} m "
                    f"(>{rc_stop_tolerance:.1f} m)."
                )
            break

        # Если долгое время почти нет изменения дистанции — считаем, что застряли
        if stuck_counter >= STUCK_TICKS:
            print(
                f"[fly_to] distance change below {STUCK_EPS} m for {STUCK_TICKS} ticks, "
                f"considering movement stalled at d={d:.3f} m."
            )
            if autopilot_enabled:
                remote.disable()
            break

        time.sleep(CHECK_INTERVAL)


def main() -> None:
    grid = prepare_grid("Owl_1")

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
        remote.update()
        cockpit.wait_for_telemetry()
        remote.wait_for_telemetry()

        # стартовая позиция REMOTE CONTROL
        start_pos = get_remote_position(remote)

        # Пытаемся взять "вверх" по гравитации (от планеты)
        planet_pos = get_remote_planet_position(remote)
        if planet_pos is not None:
            # вектор от планеты к кораблю = "вверх"
            gravity_up = (
                start_pos[0] - planet_pos[0],
                start_pos[1] - planet_pos[1],
                start_pos[2] - planet_pos[2],
            )
            up_vec = normalize(gravity_up)
            print("Using gravity-based up vector (away from planet).")
        else:
            # fallback: up кокпита
            up_vec = get_cockpit_up(cockpit)
            up_vec = normalize(up_vec)
            print("No planetPosition found, using cockpit up vector.")

        undock_pos = add_scaled(start_pos, up_vec, UNLOCK_OFFSET_METERS)

        print(f"Start RC position: {start_pos}")
        print(f"Up vector:         {up_vec}")
        print(f"Undock target:     {undock_pos}")

        input("Нажмите Enter, чтобы ОТЛЕТЕТЬ на 50 м вверх...")

        # Отлёт на 50 м вверх.
        # Если далеко (>10 м) — летим быстрее (speed_far),
        # если запускали почти в точке — медленнее.
        fly_to(
            remote=remote,
            target_pos=undock_pos,
            speed_far=20.0,
            speed_near=1.0,
            gps_name="Undock",
            dock=False,
            arrival_distance=2.0,
            rc_stop_tolerance=10.0,
        )

        input("Нажмите Enter, чтобы ВЕРНУТЬСЯ на стартовую точку...")

        while True:
            # Возврат обратно. Тоже: далеко — быстрее, близко — медленнее.
            fly_to(
                remote=remote,
                target_pos=start_pos,
                speed_far=10.0,
                speed_near=0.5,
                gps_name="Return",
                dock=False,
                arrival_distance=MIN_DISTANCE,
                rc_stop_tolerance=0.1,
            )

            print("Последовательность завершена.")
            # === ПРОВЕРКА ФАКТИЧЕСКОГО СМЕЩЕНИЯ RC ===
            remote.update()
            remote.wait_for_telemetry()
            final_pos = get_remote_position(remote)

            dx = final_pos[0] - start_pos[0]
            dy = final_pos[1] - start_pos[1]
            dz = final_pos[2] - start_pos[2]
            dist = distance(final_pos, start_pos)

            print(
                "Final RC offset from start:",
                f"dx={dx:.3f} m, dy={dy:.3f} m, dz={dz:.3f} m, dist={dist:.3f} m",
            )


            input("Нажмите Enter, чтобы ВЕРНУТЬСЯ на стартовую точку...")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
