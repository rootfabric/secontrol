
"""
Сценарий:
1. Запоминаем стартовую позицию REMOTE CONTROL и направление "вверх" по гравитации (если есть планета).
2. Считаем точку "выше" на 50 м относительно позиции REMOTE CONTROL.
3. Команда "отлететь": автопилот ведёт REMOTE CONTROL в эту точку.
4. Команда "вернуться": автопилот возвращает REMOTE CONTROL в исходную точку
   и доворотом гироскопов восстанавливает исходную ориентацию грида.

Расстояние считаем по позиции REMOTE CONTROL, а не кокпита.

Дополнительно:
- если расстояние до точки > 10 м, используем более высокую скорость;
- если <= 10 м — используем меньшую скорость для точного подлёта.
"""

import math
import time
from typing import Iterable, Sequence, Tuple

from secontrol.common import close, prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.gyro_device import GyroDevice

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


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def cross(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (
        float(a[1] * b[2] - a[2] * b[1]),
        float(a[2] * b[0] - a[0] * b[2]),
        float(a[0] * b[1] - a[1] * b[0]),
    )


def clamp(x: float, min_value: float, max_value: float) -> float:
    return float(max(min_value, min(max_value, x)))


def get_remote_up(remote: RemoteControlDevice) -> Tuple[float, float, float]:
    ori = remote.telemetry.get("orientation") or {}
    up = ori.get("up")
    if not up:
        raise RuntimeError("Remote telemetry does not contain orientation.up")
    return vec_from_orientation(up)


def get_remote_basis(remote: RemoteControlDevice) -> Tuple[Tuple[float, float, float], ...]:
    """
    Возвращает базис forward, up, right для ВЫРАВНИВАНИЯ ГРИДА.

    Приоритет:
    1) Если в телеметрии есть gridOrientation (ориентация всего грида),
       используем её — это лучше совпадает с осями гироскопов.
    2) Иначе — падаем обратно на orientation (ориентация самого Remote).

    Ожидаем структуру вида:
      "gridOrientation": {
          "forward": { "x": ..., "y": ..., "z": ... },
          "up":      { "x": ..., "y": ..., "z": ... },
          "right":   { "x": ..., "y": ..., "z": ... }  # опционально
      }
    """

    t = remote.telemetry or {}

    # 1. Пробуем взять ориентацию целого грида
    grid_ori = t.get("gridOrientation") or {}

    f_raw = grid_ori.get("forward")
    u_raw = grid_ori.get("up")
    r_raw = grid_ori.get("right")
    l_raw = grid_ori.get("left")

    # 2. Если gridOrientation нет или в нём чего-то не хватает — используем старое поле orientation
    if not f_raw or not u_raw:
        ori = t.get("orientation") or {}
        f_raw = ori.get("forward")
        u_raw = ori.get("up")
        r_raw = ori.get("right")
        l_raw = ori.get("left")

    if not f_raw or not u_raw:
        raise RuntimeError("Telemetry does not contain forward/up either in gridOrientation or orientation")

    forward = normalize(vec_from_orientation(f_raw))
    up = normalize(vec_from_orientation(u_raw))

    if r_raw:
        right = normalize(vec_from_orientation(r_raw))
    elif l_raw:
        lx, ly, lz = vec_from_orientation(l_raw)
        right = normalize((-lx, -ly, -lz))
    else:
        # Поддерживаем правую систему координат:
        # x (right), y (up), z (forward) => right = up × forward
        rx, ry, rz = cross(up, forward)
        right = normalize((rx, ry, rz))

    return forward, up, right



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


def correct_orientation(
    remote: RemoteControlDevice,
    gyros: Iterable[GyroDevice],
    target_forward: Sequence[float],
    target_up: Sequence[float],
    *,
    up_tolerance_deg: float = 5.0,
    yaw_tolerance_deg: float = 2.0,
    gain_up_phase: float = 0.5,       # усиление в фазе UP
    gain_up_stab: float = 0.3,        # усиление стабилизации UP во время YAW
    gain_yaw: float = 0.5,
    max_time: float = 20.0,
    sleep_interval: float = 0.1,
) -> None:
    """
    1) Фаза UP: ставим корабль "на ноги" (current_up -> target_up).
    2) Фаза YAW: выравниваем курс по горизонту, при этом постоянно
       подравниваем UP, чтобы не заваливало.
    """

    gyro_list = list(gyros)
    if not gyro_list:
        print("[orientation] No gyros found, skipping alignment")
        return

    t_f = normalize(tuple(target_forward))
    t_u = normalize(tuple(target_up))

    up_tol_rad = math.radians(up_tolerance_deg)
    yaw_tol_rad = math.radians(yaw_tolerance_deg)

    def _project_to_plane(
        v: Tuple[float, float, float],
        n: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        d = dot(v, n)
        return (
            v[0] - n[0] * d,
            v[1] - n[1] * d,
            v[2] - n[2] * d,
        )

    def _yaw_angle_and_sign(
        current_forward: Tuple[float, float, float],
        target_forward: Tuple[float, float, float],
        up_axis: Tuple[float, float, float],
    ) -> Tuple[float, float]:
        """
        Угол и знак вращения вокруг up_axis.
        sign подобран так, чтобы УМЕНЬШАТЬ угол.
        """
        cf = _project_to_plane(current_forward, up_axis)
        tf = _project_to_plane(target_forward, up_axis)

        try:
            cf = normalize(cf)
            tf = normalize(tf)
        except ValueError:
            return 0.0, 0.0

        c = clamp(dot(cf, tf), -1.0, 1.0)
        angle = math.acos(c)
        if angle < 1e-6:
            return 0.0, 0.0

        cross_cf_tf = cross(cf, tf)
        s = dot(cross_cf_tf, up_axis)

        # важно: знак инвертирован, чтобы крутить в сторону уменьшения угла
        sign = -1.0 if s > 0.0 else 1.0
        return angle, sign

    def _stop_gyros() -> None:
        for g in gyro_list:
            g.set_override(pitch=0.0, yaw=0.0, roll=0.0)
        print("[orientation] Gyros stopped")

    print(
        "[orientation] Starting 2-phase orientation correction\n"
        f"  target_forward={t_f}\n"
        f"  target_up={t_u}"
    )

    start_time = time.time()
    last_log = start_time

    try:
        # ===========================
        # ФАЗА 1 — ВЫРАВНИВАЕМ UP
        # ===========================
        while True:
            now = time.time()
            if now - start_time > max_time:
                print(f"[orientation] TIMEOUT during UP phase after {max_time:.1f} s")
                _stop_gyros()
                return

            remote.update()
            remote.wait_for_telemetry()

            current_forward, current_up, current_right = get_remote_basis(remote)

            du = clamp(dot(current_up, t_u), -1.0, 1.0)
            up_angle = math.acos(du)

            if up_angle <= up_tol_rad:
                print(
                    "[orientation] UP aligned:\n"
                    f"  up_angle={math.degrees(up_angle):.2f}° (dotU={du:.4f})"
                )
                _stop_gyros()
                break

            err_u = cross(current_up, t_u)

            yaw_cmd = clamp(dot(err_u, current_up) * gain_up_phase, -0.5, 0.5)
            pitch_cmd = clamp(dot(err_u, current_right) * gain_up_phase, -0.5, 0.5)
            roll_cmd = clamp(dot(err_u, current_forward) * gain_up_phase, -0.5, 0.5)

            for g in gyro_list:
                g.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            if now - last_log >= 0.5:
                print(
                    "[orientation][UP] step:\n"
                    f"  up_angle={math.degrees(up_angle):.2f}° (dotU={du:.4f})\n"
                    f"  cmd: pitch={pitch_cmd:.4f}, yaw={yaw_cmd:.4f}, roll={roll_cmd:.4f}"
                )
                last_log = now

            time.sleep(sleep_interval)

        # ===========================
        # ФАЗА 2 — ВЫРАВНИВАЕМ YAW
        # ===========================
        yaw_phase_start = time.time()
        last_log = yaw_phase_start

        # для простого «анти-разгона» — отслеживаем предыдущий yaw_angle
        prev_yaw_angle = None
        worse_steps = 0

        while True:
            now = time.time()
            if now - yaw_phase_start > max_time:
                print(f"[orientation] TIMEOUT during YAW phase after {max_time:.1f} s")
                break

            remote.update()
            remote.wait_for_telemetry()

            current_forward, current_up, current_right = get_remote_basis(remote)

            # угол по горизонту считаем вокруг ТЕКУЩЕГО up,
            # чтобы соответствовать оси yaw гироскопов
            yaw_angle, yaw_sign = _yaw_angle_and_sign(current_forward, t_f, current_up)

            df = clamp(dot(current_forward, t_f), -1.0, 1.0)
            f_angle = math.degrees(math.acos(df))

            du = clamp(dot(current_up, t_u), -1.0, 1.0)
            up_angle_deg = math.degrees(math.acos(du))

            # если курс уже достаточно близко — выходим
            if yaw_angle <= yaw_tol_rad:
                print(
                    "[orientation] YAW aligned:\n"
                    f"  yaw_angle={math.degrees(yaw_angle):.2f}°\n"
                    f"  angleF={f_angle:.2f}° (dotF={df:.4f})\n"
                    f"  angleU={up_angle_deg:.2f}° (dotU={du:.4f})"
                )
                break

            # простая защита: если up сильно ушёл — прекращаем, чтобы не улететь в переворот
            if up_angle_deg > 30.0:
                print(
                    "[orientation] UP drift too large during YAW "
                    f"({up_angle_deg:.2f}°) — stopping"
                )
                break

            # защита от «разгона»: если несколько шагов подряд yaw_angle не уменьшается — выходим
            if prev_yaw_angle is not None and yaw_angle >= prev_yaw_angle - math.radians(0.1):
                worse_steps += 1
                if worse_steps >= 5:
                    print(
                        "[orientation] YAW not improving for several steps "
                        f"(last angle={math.degrees(yaw_angle):.2f}°) — stopping"
                    )
                    break
            else:
                worse_steps = 0
            prev_yaw_angle = yaw_angle

            # ======= СТАБИЛИЗАЦИЯ UP во время YAW =======
            err_u = cross(current_up, t_u)
            stab_pitch = clamp(dot(err_u, current_right) * gain_up_stab, -0.3, 0.3)
            stab_roll = clamp(dot(err_u, current_forward) * gain_up_stab, -0.3, 0.3)

            # yaw вокруг текущего up
            yaw_cmd = clamp(yaw_sign * yaw_angle * gain_yaw, -0.5, 0.5)
            pitch_cmd = stab_pitch
            roll_cmd = stab_roll

            for g in gyro_list:
                g.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            if now - last_log >= 0.5:
                print(
                    "[orientation][YAW] step:\n"
                    f"  yaw_angle={math.degrees(yaw_angle):.2f}° (cmd yaw={yaw_cmd:.4f})\n"
                    f"  angleF={f_angle:.2f}° (dotF={df:.4f})\n"
                    f"  angleU={up_angle_deg:.2f}° (dotU={du:.4f})\n"
                    f"  stab: pitch={stab_pitch:.4f}, roll={stab_roll:.4f}"
                )
                last_log = now

            time.sleep(sleep_interval)

    finally:
        _stop_gyros()




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
    align_orientation: bool = False,
    gyros_for_alignment: Iterable[GyroDevice] | None = None,
    target_forward: Sequence[float] | None = None,
    target_up: Sequence[float] | None = None,
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

    # После завершения подлёта — доворот в исходную ориентацию
    if align_orientation and gyros_for_alignment:
        if target_forward is None or target_up is None:
            print("[fly_to] alignment requested but target basis not provided")
        else:
            correct_orientation(
                remote=remote,
                gyros=gyros_for_alignment,
                target_forward=target_forward,
                target_up=target_up,
            )


def main() -> None:
    grid = prepare_grid("Owl_1")

    try:
        remotes = grid.find_devices_by_type("remote_control")
        if not remotes:
            print("Remote Control not found on grid")
            return
        remote: RemoteControlDevice = remotes[0]
        print(f"Remote control: {remote.name} (id={remote.device_id})")

        gyros = grid.find_devices_by_type("gyro")
        if not gyros:
            print("Gyroscopes not found on grid")
            return
        print(f"Gyros on grid: {len(gyros)}")

        # первая телеметрия
        remote.update()
        remote.wait_for_telemetry()

        # стартовая позиция REMOTE CONTROL
        start_pos = get_remote_position(remote)

        # запоминаем стартовую ориентацию грида по REMOTE CONTROL
        start_forward, start_up, _start_right = get_remote_basis(remote)

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
            up_vec = get_remote_up(remote)
            up_vec = normalize(up_vec)
            print("No planetPosition found, using remote up vector.")

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
                align_orientation=True,
                gyros_for_alignment=gyros,
                target_forward=start_forward,
                target_up=start_up,
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
