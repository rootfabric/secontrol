from __future__ import annotations

import math
import time
from typing import Dict, Optional, Sequence, Tuple, Any, Union

from secontrol.common import close, prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

CHECK_INTERVAL: float = 0.05
ALIGN_TIMEOUT: float = 20.0

# Требуемое качество совпадения направлений
DOT_THRESHOLD_FORWARD: float = 0.995
DOT_THRESHOLD_UP: float = 0.99

# Минимальная угловая ошибка (в радианах), ниже которой считаем, что выровнялись
ANGULAR_ERROR_EPS: float = math.radians(1.0)

# Коэффициент P-регулятора (по углу в рад/с)
P_GAIN_ROT: float = 0.7

# Ограничение по угловой скорости (рад/с) для гироскопов
MAX_GYRO_OMEGA: float = 0.7

Vector3 = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------

def vec_from_orientation(d: Union[dict, Sequence[float]]) -> Tuple[float, float, float]:
    if isinstance(d, dict):
        return float(d["x"]), float(d["y"]), float(d["z"])
    elif isinstance(d, (list, tuple)) and len(d) == 3:
        return float(d[0]), float(d[1]), float(d[2])
    else:
        raise ValueError("Invalid orientation format")


def vec_add(a: Vector3, b: Vector3) -> Vector3:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def vec_sub(a: Vector3, b: Vector3) -> Vector3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def vec_dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_len(a: Vector3) -> float:
    return math.sqrt(vec_dot(a, a))


def vec_normalize(a: Vector3) -> Vector3:
    length = vec_len(a)
    if length < 1e-9:
        return 0.0, 0.0, 0.0
    inv = 1.0 / length
    return a[0] * inv, a[1] * inv, a[2] * inv


def vec_scale(a: Vector3, k: float) -> Vector3:
    return a[0] * k, a[1] * k, a[2] * k


def clamp_omega(value: float) -> float:
    if value > MAX_GYRO_OMEGA:
        return MAX_GYRO_OMEGA
    if value < -MAX_GYRO_OMEGA:
        return -MAX_GYRO_OMEGA
    return value


# ---------------------------------------------------------------------------
# Matrix helpers (3x3)
# ---------------------------------------------------------------------------

Matrix3 = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


def mat_from_basis(right: Vector3, up: Vector3, forward: Vector3) -> Matrix3:
    """
    Матрица ориентации, столбцы — базисные векторы в мировых координатах:
        [ r.x  u.x  f.x ]
        [ r.y  u.y  f.y ]
        [ r.z  u.z  f.z ]
    """
    return (
        (right[0], up[0], forward[0]),
        (right[1], up[1], forward[1]),
        (right[2], up[2], forward[2]),
    )


def mat_transpose(m: Matrix3) -> Matrix3:
    return (
        (m[0][0], m[1][0], m[2][0]),
        (m[0][1], m[1][1], m[2][1]),
        (m[0][2], m[1][2], m[2][2]),
    )


def mat_mul(a: Matrix3, b: Matrix3) -> Matrix3:
    # c = a * b
    return (
        (
            a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
            a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
            a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2],
        ),
        (
            a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
            a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
            a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2],
        ),
        (
            a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
            a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
            a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2],
        ),
    )


def mat_trace(m: Matrix3) -> float:
    return m[0][0] + m[1][1] + m[2][2]


def rotation_matrix_to_axis_angle(m: Matrix3) -> Tuple[Vector3, float]:
    """
    Из deltaR получаем ось (в мировых координатах) и угол поворота (рад).
    """
    # Защита от численных артефактов
    tr = mat_trace(m)
    cos_angle = max(-1.0, min(1.0, 0.5 * (tr - 1.0)))
    angle = math.acos(cos_angle)

    if angle < 1e-4:
        # Практически совпадают
        return (0.0, 0.0, 0.0), 0.0

    # Для нормальных случаев (не угол ~pi)
    x = m[2][1] - m[1][2]
    y = m[0][2] - m[2][0]
    z = m[1][0] - m[0][1]
    axis = (x, y, z)
    axis_n = vec_normalize(axis)
    return axis_n, angle


# ---------------------------------------------------------------------------
# Orientation / basis helpers
# ---------------------------------------------------------------------------

def project_axis_to_basis(axis_world: Vector3, forward: Vector3, up: Vector3, right: Vector3) -> Vector3:
    """
    Проецируем ось вращения из мировых координат в локальные (yaw, pitch, roll).

    Конвенция Space Engineers для гироскопов:
        yaw   — вокруг локальной оси up
        pitch — вокруг локальной оси right
        roll  — вокруг локальной оси forward
    """
    yaw = vec_dot(axis_world, up)
    pitch = vec_dot(axis_world, right)
    roll = vec_dot(axis_world, forward)
    return yaw, pitch, roll


def get_remote_basis(remote: RemoteControlDevice) -> Tuple[Vector3, Vector3, Vector3]:
    """Возвращает forward, up, right из телеметрии REMOTE CONTROL, с ортонормализацией."""
    ori = remote.telemetry.get("orientation") or {}
    f_raw = ori.get("forward")
    u_raw = ori.get("up")
    r_raw = ori.get("right")
    l_raw = ori.get("left")

    if not f_raw or not u_raw:
        raise RuntimeError("Remote telemetry does not contain orientation.forward/up")

    forward = vec_normalize(vec_from_orientation(f_raw))
    up_hint = vec_normalize(vec_from_orientation(u_raw))

    # Делаем up ортогональным forward
    proj = vec_scale(forward, vec_dot(up_hint, forward))
    up_ortho = vec_sub(up_hint, proj)
    up = vec_normalize(up_ortho)

    if r_raw:
        right = vec_normalize(vec_from_orientation(r_raw))
    elif l_raw:
        lx, ly, lz = vec_from_orientation(l_raw)
        right = vec_normalize((-lx, -ly, -lz))
    else:
        # Вычисляем right как forward × up
        right = vec_normalize(vec_cross(forward, up))

    return forward, up, right


def build_basis(forward_v: Vector3, up_hint: Vector3) -> Tuple[Vector3, Vector3, Vector3]:
    """
    Строим ортонормальный базис (forward, up, right) вокруг заданного forward
    и "примерного" up (может быть не ортогонален).
    """
    forward_n = vec_normalize(forward_v)

    # Ортогонализируем up_hint относительно forward
    proj = vec_scale(forward_n, vec_dot(up_hint, forward_n))
    up_raw = vec_sub(up_hint, proj)
    up_n = vec_normalize(up_raw)
    if vec_len(up_n) < 1e-6:
        # Если up_hint почти параллелен forward — берём произвольный
        arbitrary_up: Vector3 = (0.0, 1.0, 0.0)
        if abs(vec_dot(forward_n, arbitrary_up)) > 0.9:
            arbitrary_up = (0.0, 0.0, 1.0)
        proj = vec_scale(forward_n, vec_dot(arbitrary_up, forward_n))
        up_raw = vec_sub(arbitrary_up, proj)
        up_n = vec_normalize(up_raw)

    right = vec_normalize(vec_cross(forward_n, up_n))

    # Пересобираем up как точно ортогональный (для устойчивости)
    up_n = vec_normalize(vec_cross(right, forward_n))

    return forward_n, up_n, right


def align_grid_to_orientation(
    rc: RemoteControlDevice,
    gyros: Sequence[GyroDevice],
    target_forward: Vector3,
    target_up: Vector3,
    timeout: float = ALIGN_TIMEOUT,
) -> bool:
    """
    Поворачиваем грид так, чтобы его forward / up совпали с целевыми (ориентация игрока).

    Используем матричную ошибку ориентации:
      * строим базисы грида и цели (forward, up, right);
      * вычисляем deltaR = R_target * R_grid^T;
      * из deltaR получаем ось+угол поворота;
      * ось проецируем в локальные yaw/pitch/roll и задаём гироскопам ω,
        пропорциональную углу (с ограничением по MAX_GYRO_OMEGA).
    """
    if not gyros:
        print("[orientation] No gyros specified, cannot align.")
        return False

    # Собираем целевой базис один раз
    t_forward, t_up, t_right = build_basis(target_forward, target_up)
    R_target = mat_from_basis(t_right, t_up, t_forward)

    t_start = time.time()

    print("[orientation] Start aligning grid to player orientation...")

    try:
        # Включаем override заранее, с нулевыми значениями
        for g in gyros:
            g.set_override(pitch=0.0, yaw=0.0, roll=0.0)

        while True:
            now = time.time()
            elapsed = now - t_start
            if elapsed > timeout:
                print(f"[orientation] Timeout after {elapsed:.1f}s, stopping.")
                return False

            # Ориентация грида
            g_forward, g_up, g_right = get_remote_basis(rc)
            g_forward_n, g_up_n, g_right_n = build_basis(g_forward, g_up)

            R_grid = mat_from_basis(g_right_n, g_up_n, g_forward_n)

            # Скалярные метрики для логов/критерия останова
            dot_forward = vec_dot(g_forward_n, t_forward)
            dot_up = vec_dot(g_up_n, t_up)

            # Матрица относительного поворота: как повернуть grid, чтобы стать target
            R_delta = mat_mul(R_target, mat_transpose(R_grid))

            axis_world, angle = rotation_matrix_to_axis_angle(R_delta)
            error_len = angle  # угол — натуральная мера ошибки

            print(
                f"[orientation] elapsed={elapsed:5.2f}s, "
                f"error_len={error_len:7.4f}, "
                f"dotF={dot_forward:7.4f}, dotU={dot_up:7.4f}"
            )

            # Критерий "хватит крутить"
            if (
                error_len < ANGULAR_ERROR_EPS
                and dot_forward > DOT_THRESHOLD_FORWARD
                and dot_up > DOT_THRESHOLD_UP
            ):
                print("[orientation] Target orientation reached — stopping.")
                # Обнуляем гиры перед выходом
                for g in gyros:
                    g.set_override(pitch=0.0, yaw=0.0, roll=0.0)
                return True

            if error_len < 1e-4 or vec_len(axis_world) < 1e-6:
                # Ошибка очень маленькая или ось плохо определена
                for g in gyros:
                    g.set_override(pitch=0.0, yaw=0.0, roll=0.0)
                print("[orientation] Very small rotation error, stopping.")
                return True

            # Пропорциональное управление по углу.
            # Чем больше угол — тем больше задаём ω, но не выше MAX_GYRO_OMEGA.
            omega_mag = min(MAX_GYRO_OMEGA, P_GAIN_ROT * error_len)
            control_axis_world = vec_scale(axis_world, omega_mag)

            # Проекция на локальные оси грида (yaw/pitch/roll)
            yaw_raw, pitch_raw, roll_raw = project_axis_to_basis(
                control_axis_world, g_forward_n, g_up_n, g_right_n
            )

            yaw = clamp_omega(yaw_raw)
            pitch = clamp_omega(pitch_raw)
            roll = clamp_omega(roll_raw)

            print(
                f"[orientation] omega_local=({yaw:+.3f}, {pitch:+.3f}, {roll:+.3f})"
            )

            for g in gyros:
                g.set_override(pitch=pitch, yaw=yaw, roll=roll)

            time.sleep(CHECK_INTERVAL)

    finally:
        # Всегда снимаем override с гироскопов
        for g in gyros:
            try:
                g.clear_override()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Radar helpers
# ---------------------------------------------------------------------------

def _build_player_up_vector(
    forward_v: Vector3,
    gravity_v: Optional[Vector3],
    fallback_up: Optional[Vector3],
) -> Vector3:
    """
    Строим вектор up для игрока:
      * если есть гравитация — up = -normalize(gravityVector)
      * иначе, если есть fallback_up (up грида) — используем его
      * иначе строим ортонормальный basis вокруг forward.
    """
    forward_n = vec_normalize(forward_v)

    # 1. Гравитация
    if gravity_v is not None:
        g_len = vec_len(gravity_v)
        if g_len > 1e-6:
            # гравитация обычно направлена вниз, up — противоположно
            up = vec_scale(vec_normalize(gravity_v), -1.0)
            return up

    # 2. Fallback от грида
    if fallback_up is not None and vec_len(fallback_up) > 1e-6:
        return vec_normalize(fallback_up)

    # 3. Строим up сами, ортогональный forward
    arbitrary_up: Vector3 = (0.0, 1.0, 0.0)
    if abs(vec_dot(forward_n, arbitrary_up)) > 0.9:
        arbitrary_up = (0.0, 0.0, 1.0)

    proj = vec_scale(forward_n, vec_dot(arbitrary_up, forward_n))
    up_raw = vec_sub(arbitrary_up, proj)
    up_n = vec_normalize(up_raw)
    return up_n


def find_first_owner_player_orientation(
    radar: OreDetectorDevice,
    owner_identity_id: int,
    fallback_up: Optional[Vector3] = None,
) -> Optional[Tuple[Vector3, Vector3]]:
    """
    Делаем scan у радара и ищем первого игрока с ownerId == owner_identity_id.
    Возвращаем (forward, up) этого игрока в мировых координатах.
    """
    print(f"[radar] Scanning for owner identity_id={owner_identity_id}...")
    radar.scan(
        include_players=True,
        include_grids=False,
        include_voxels=False,
    )

    contacts = radar.telemetry.get("radar", {}).get("contacts") or []

    for p in contacts:
        if p.get("type") != "player":
            continue

        try:
            player_owner_id = int(p.get("ownerId"))
        except (TypeError, ValueError):
            continue

        try:
            grid_owner_id_int = int(owner_identity_id)
        except (TypeError, ValueError):
            continue

        if player_owner_id != grid_owner_id_int:
            continue

        pos = p.get("position")
        forward_list = p.get("headForward") or p.get("forward")
        gravity_list = p.get("gravityVector")

        if not (pos and forward_list):
            continue

        forward_v: Vector3 = (
            float(forward_list[0]),
            float(forward_list[1]),
            float(forward_list[2]),
        )

        gravity_v: Optional[Vector3] = None
        if gravity_list is not None and len(gravity_list) == 3:
            gravity_v = (
                float(gravity_list[0]),
                float(gravity_list[1]),
                float(gravity_list[2]),
            )

        forward_n = vec_normalize(forward_v)
        up_v = _build_player_up_vector(forward_n, gravity_v, fallback_up)
        up_n = vec_normalize(up_v)

        f_len = vec_len(forward_n)
        u_len = vec_len(up_n)
        print(
            f"[radar] Found owner player @ {pos}, "
            f"|forward|={f_len:.3f}, |up|={u_len:.3f}, "
            f"gravity={gravity_v}"
        )

        return forward_n, up_n

    print("[radar] Owner player not found in scan.")
    return None


import math
import time


import math
import time


def align_grid_to_player_orientation(
    remote,
    gyros,
    target_forward,
    target_up,
    max_time: float = 20.0,
) -> str:
    """Выравниваем грид по ориентации игрока.

    remote.get_orientation_vectors_world() должен возвращать:
        (forward: (x, y, z), up: (x, y, z), right: (x, y, z))

    gyros — список GyroDevice, у которых есть:
        enable(), disable(), clear_override(),
        set_override(pitch=..., yaw=..., roll=..., power=...)

    Возвращает строку с причиной останова (для логов).
    """

    def normalize(v):
        length = math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        if length < 1e-6:
            return (0.0, 0.0, 0.0)
        return (v[0]/length, v[1]/length, v[2]/length)

    def dot(a, b):
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    def cross(a, b):
        return (
            a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0],
        )

    def length(v):
        return math.sqrt(dot(v, v))

    # Нормализуем целевые векторы игрока
    target_forward = normalize(target_forward)
    target_up = normalize(target_up)

    # Настройки контроллера (под SE-гиру, вход [-1..1])
    MAX_COMMAND = 1.0                     # максимум по модулю на pitch/yaw/roll
    KP = 0.8                              # коэффициент "на сколько крутимся" от ошибки
    STOP_ANGLE_FORWARD = math.radians(1)  # 1° по forward
    STOP_ANGLE_UP = math.radians(1)       # 1° по up
    MIN_EFFECTIVE_ERROR = math.radians(0.2)

    t0 = time.time()
    last_reason = "unknown"

    # Включаем гиры (если были выключены)
    for g in gyros:
        try:
            g.enable()
        except Exception:
            pass

    try:
        while True:
            now = time.time()
            elapsed = now - t0
            if elapsed > max_time:
                last_reason = f"timeout: elapsed={elapsed:.2f}s"
                print(f"[orientation] STOP by TIMEOUT: {last_reason}")
                break

            # Текущая ориентация грида по remote (в мировых координатах)
            forward, up, right = remote.get_orientation_vectors_world()
            forward = normalize(forward)
            up = normalize(up)

            # Скалярные произведения с целевыми осями
            dotF = max(-1.0, min(1.0, dot(forward, target_forward)))
            dotU = max(-1.0, min(1.0, dot(up, target_up)))

            angF = math.acos(dotF)   # радианы
            angU = math.acos(dotU)   # радианы

            # Сводная "длина ошибки"
            error_len = math.hypot(angF, angU)

            # ---- Критерий успеха -----------------------------------------
            if angF < STOP_ANGLE_FORWARD and angU < STOP_ANGLE_UP:
                last_reason = (
                    f"precision reached: "
                    f"angF={math.degrees(angF):.2f}°, "
                    f"angU={math.degrees(angU):.2f}°"
                )
                print(f"[orientation] Alignment complete, {last_reason}")
                break

            # Ошибка уже маленькая — дальше будет только болтаться
            if error_len < MIN_EFFECTIVE_ERROR:
                last_reason = (
                    f"small error but not improving: "
                    f"angF={math.degrees(angF):.2f}°, "
                    f"angU={math.degrees(angU):.2f}°"
                )
                print(f"[orientation] STOP by SMALL ERROR: {last_reason}")
                break

            # ---- Вектор ошибки в мировом базисе ---------------------------
            axisF = cross(forward, target_forward)
            axisU = cross(up, target_up)

            omega_world = (
                axisF[0] + axisU[0],
                axisF[1] + axisU[1],
                axisF[2] + axisU[2],
            )

            norm = length(omega_world)
            if norm < 1e-5:
                last_reason = "omega_world almost zero (nothing to rotate)"
                print(f"[orientation] STOP by ZERO OMEGA: {last_reason}")
                break

            # ---- Масштабируем "ω" по величине ошибки ----------------------
            # Тут "ω" — не настоящие рад/с, а просто команда [-1..1].
            scale = KP * error_len / norm
            omega_world = (
                omega_world[0] * scale,
                omega_world[1] * scale,
                omega_world[2] * scale,
            )

            # Ограничиваем максимум по модулю команды
            omega_len = length(omega_world)
            if omega_len > MAX_COMMAND:
                k = MAX_COMMAND / omega_len
                omega_world = (
                    omega_world[0] * k,
                    omega_world[1] * k,
                    omega_world[2] * k,
                )

            # ---- Переводим в локальные оси грида --------------------------
            f = forward
            u = up
            # right = u × f
            r = (
                u[1]*f[2] - u[2]*f[1],
                u[2]*f[0] - u[0]*f[2],
                u[0]*f[1] - u[1]*f[0],
            )

            wx, wy, wz = omega_world
            rx, ry, rz = r
            ux, uy, uz = u
            fx, fy, fz = f

            # roll — вокруг right, pitch — вокруг up, yaw — вокруг forward
            omega_roll = wx*rx + wy*ry + wz*rz
            omega_pitch = wx*ux + wy*uy + wz*uz
            omega_yaw = wx*fx + wy*fy + wz*fz

            # Для логов видно и ошибку, и команду
            print(
                f"[orientation] elapsed={elapsed:5.2f}s, "
                f"error_len={error_len:5.3f}, "
                f"dotF={dotF:5.4f}, dotU={dotU:5.4f}, "
                f"angF={math.degrees(angF):6.2f}°, "
                f"angU={math.degrees(angU):6.2f}°, "
                f"omega_local=(roll={omega_roll:+6.3f}, "
                f"pitch={omega_pitch:+6.3f}, yaw={omega_yaw:+6.3f})"
            )

            # Отправляем команды на все гиры.
            # ВАЖНО: используем именованные параметры
            for g in gyros:
                try:
                    g.set_override(
                        pitch=omega_pitch,
                        yaw=omega_yaw,
                        roll=omega_roll,
                        power=1.0,   # 100% мощности гира
                    )
                except Exception as e:
                    print(f"[orientation] Gyro command error: {e!r}")

            time.sleep(0.05)

    finally:
        # Снимаем оверрайд и гасим команды (иначе будет продолжать крутиться)
        for g in gyros:
            try:
                g.clear_override()
            except Exception:
                pass

    return last_reason



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    grid = prepare_grid("taburet")

    try:
        detectors = grid.find_devices_by_type(OreDetectorDevice)
        if not detectors:
            print("На гриде не найдено ни одного детектора руды (ore_detector).")
            return
        detector: OreDetectorDevice = detectors[0]
        print(f"Найден радар device_id={detector.device_id} name={detector.name!r}")

        remotes = grid.find_devices_by_type(RemoteControlDevice)
        if not remotes:
            print("Не найдено блока REMOTE CONTROL для чтения ориентации грида.")
            return
        remote: RemoteControlDevice = remotes[0]
        print(f"Используется REMOTE CONTROL {remote.name!r} (id={remote.device_id})")

        gyros = grid.find_devices_by_type(GyroDevice)
        if not gyros:
            print("Не найдено гироскопов на гриде.")
            return
        print(f"Найдено гироскопов: {len(gyros)}")

        print("Сканируем игрока-владельца и доворaчиваемся под его наклон...")

        owner_identity_id = getattr(grid, "owner_id", None)
        if owner_identity_id is None:
            print("[main] Grid owner_id is not available.")
            return

        print(f"[main] Grid owner identity id: {owner_identity_id}")

        # fallback_up берём из RemoteControl
        _, grid_up, _ = get_remote_basis(remote)
        fallback_up: Vector3 = vec_normalize(grid_up)

        orientation = find_first_owner_player_orientation(
            detector,
            owner_identity_id,
            fallback_up=fallback_up,
        )
        if orientation is None:
            print("[main] Could not get player orientation from radar.")
            return

        player_forward, player_up = orientation
        print(
            "[main] Player orientation updated: "
            f"forward={player_forward}, up={player_up}"
        )

        reason = align_grid_to_player_orientation(
            remote=remote,
            gyros=gyros,
            target_forward=player_forward,
            target_up=player_up,
            max_time=20.0,
        )
        print("[main] Grid alignment finished:", reason)


    except KeyboardInterrupt:
        print("Выход...")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
