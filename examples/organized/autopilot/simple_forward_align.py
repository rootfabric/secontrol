from __future__ import annotations
import math
import time
from typing import Tuple, Optional

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice


# ---- Вспомогательная математика ---------------------------------------------

def _vec(value) -> Tuple[float, float, float]:
    return float(value[0]), float(value[1]), float(value[2])


def _dot(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Tuple[float, ...], b: Tuple[float, ...]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(v: Tuple[float, ...]) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _normalize(v: Tuple[float, ...]) -> Tuple[float, float, float]:
    length = _length(v)
    if length < 1e-6:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _parse_vector(value) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return _vec((value["x"], value["y"], value["z"]))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return _vec(value)
    return None


class Basis:
    """
    Ортонормированный базис корабля в мировых координатах.
    forward, up, right и left соответствуют ориентации Remote Control.
    """

    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        f = _normalize(forward)
        u = _normalize(up)

        # right = forward × up
        r = _cross(f, u)
        if _length(r) < 1e-6:
            # Защита от вырожденного случая
            if abs(f[1]) < 0.9:
                u = (0.0, 1.0, 0.0)
            else:
                u = (1.0, 0.0, 0.0)
            u = _normalize(u)
            r = _cross(f, u)

        r = _normalize(r)
        l = (-r[0], -r[1], -r[2])
        # Пересчитаем up для строгой ортонормальности
        u = _normalize(_cross(r, f))

        self.forward = f
        self.up = u
        self.right = r
        self.left = l


# ---- Ориентация устройств ---------------------------------------------------

def get_orientation(device: BaseDevice) -> Basis:
    tel = device.telemetry or {}
    ori = tel.get("orientation")
    if not ori:
        raise RuntimeError(f"Ориентация не найдена в телеметрии {device.name}")

    fwd = _parse_vector(ori.get("forward"))
    up = _parse_vector(ori.get("up"))
    if fwd and up:
        return Basis(fwd, up)

    raise RuntimeError(f"Неправильный формат ориентации для {device.name}")


# ---- Ориентация игрока ------------------------------------------------------

def get_player_forward(radar: OreDetectorDevice) -> Optional[Tuple[float, float, float]]:
    print("Сканируем игроков...")
    radar.scan(
        include_players=True,
        include_grids=False,
        include_voxels=False,
    )

    contacts = radar.telemetry.get("radar", {}).get("contacts") or []
    for p in contacts:
        if p.get("type") != "player":
            continue

        forward_list = p.get("headForward") or p.get("forward")
        if not forward_list:
            continue

        forward = _vec(forward_list)
        forward = _normalize(forward)
        print(
            f"Найден игрок, forward: "
            f"({forward[0]:.3f}, {forward[1]:.3f}, {forward[2]:.3f})"
        )
        return forward

    print("Игрок не найден.")
    return None


# ---- Управление гироскопами -------------------------------------------------

def compute_gyro_commands(
    basis: Basis,
    desired_forward: Tuple[float, float, float],
    max_rate: float = 0.8,
) -> Tuple[float, float, float, float]:
    """
    Возвращает (pitch_cmd, yaw_cmd, roll_cmd, angle_between) в системе pitch/yaw/roll.
    Используем вектор вращения axis = cross(current_forward, desired_forward).
    """

    f = basis.forward
    d = _normalize(desired_forward)

    dot_fd = max(-1.0, min(1.0, _dot(f, d)))
    angle = math.acos(dot_fd)

    # Почти выровнялись
    if angle < math.radians(0.5):
        return 0.0, 0.0, 0.0, angle

    # Почти строго назад — ось вращения не определена (sin(pi) ≈ 0)
    if dot_fd < -0.999:
        # крутимся вокруг up, чтобы уйти из этой зоны
        axis = basis.up
    else:
        axis = _cross(f, d)
        axis_len = _length(axis)
        if axis_len < 1e-6:
            return 0.0, 0.0, 0.0, angle
        axis = (axis[0] / axis_len, axis[1] / axis_len, axis[2] / axis_len)

    # Перевод в локальный базис корабля:
    # axis = wx * right + wy * up + wz * forward
    wx = _dot(axis, basis.right)
    wy = _dot(axis, basis.up)
    wz = _dot(axis, basis.forward)

    # Замедляемся при малых углах, чтобы не раскачиваться
    slow_angle = math.radians(30.0)
    k = min(1.0, angle / slow_angle)

    # Базовые команды (без учёта возможного инверта знака гироскопов)
    pitch_cmd = k * wx
    yaw_cmd = k * wy
    roll_cmd = k * wz

    # Ограничим по максимальной скорости
    def clamp(v: float) -> float:
        if v > max_rate:
            return max_rate
        if v < -max_rate:
            return -max_rate
        return v

    return clamp(pitch_cmd), clamp(yaw_cmd), clamp(roll_cmd), angle


# ---- Основное выравнивание --------------------------------------------------

def simple_align_forward(grid, player_forward: Tuple[float, float, float]) -> None:
    """
    Поворачивает грид так, чтобы forward корабля совпал с forward игрока.
    Используем векторное управление и авто-подбор знака гироскопов.
    """
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        print("Не найден RemoteControlDevice")
        return
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        print("Не найдены гироскопы")
        return

    desired_forward = _normalize(player_forward)

    rc_dev.update()
    try:
        basis = get_orientation(rc_dev)
    except RuntimeError as e:
        print(f"Ошибка ориентации грида: {e}")
        return

    print(
        "Желаемый forward: "
        f"({desired_forward[0]:.3f}, {desired_forward[1]:.3f}, {desired_forward[2]:.3f})"
    )

    max_time = 40.0               # секунд
    sleep_interval = 0.1          # шаг цикла
    angle_threshold = math.radians(2.0)

    start_time = time.time()
    prev_dot = None
    worsen_steps = 0

    # sign_correction позволяет автоматически подобрать правильный знак управления
    sign_correction = -1.0

    while True:
        rc_dev.update()
        try:
            basis = get_orientation(rc_dev)
        except RuntimeError as e:
            print(f"Ошибка ориентации грида в цикле: {e}")
            break

        pitch_cmd, yaw_cmd, roll_cmd, angle = compute_gyro_commands(
            basis, desired_forward, max_rate=0.6
        )

        dot_fd = _dot(basis.forward, desired_forward)

        print(
            "Текущий forward: "
            f"({basis.forward[0]:.3f}, {basis.forward[1]:.3f}, {basis.forward[2]:.3f}), "
            f"dot={dot_fd:.4f}, angle={angle:.3f} rad, "
            f"raw_cmd(p,y,r)=({pitch_cmd:.3f}, {yaw_cmd:.3f}, {roll_cmd:.3f}), "
            f"sign={sign_correction:+.1f}"
        )

        # Условие выхода
        if angle < angle_threshold:
            print("Целевой поворот достигнут.")
            break

        # Отслеживаем, улучшается ли dot (становится ближе к 1)
        if prev_dot is not None:
            if dot_fd < prev_dot - 1e-4:
                worsen_steps += 1
            else:
                worsen_steps = 0
        prev_dot = dot_fd

        # Если несколько шагов подряд только хуже — пробуем перевернуть знак гироскопов
        if worsen_steps >= 15:
            sign_correction *= -1.0
            worsen_steps = 0
            print(f"[align] Инвертируем знак управления гироскопами, новый sign={sign_correction:+.1f}")

        pitch_cmd *= sign_correction
        yaw_cmd *= sign_correction
        roll_cmd *= sign_correction

        for gyro in gyros:
            gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

        if time.time() - start_time > max_time:
            print("Таймаут выравнивания по forward, выходим.")
            break

        time.sleep(sleep_interval)

    for gyro in gyros:
        gyro.disable()

    print("Поворот завершён.")


# ---- Main -------------------------------------------------------------------

if __name__ == "__main__":
    grid = prepare_grid("taburet")
    try:
        radars = grid.find_devices_by_type(OreDetectorDevice)
        if not radars:
            print("Не найден OreDetectorDevice")
        else:
            radar = radars[0]
            player_forward = get_player_forward(radar)
            if player_forward:
                simple_align_forward(grid, player_forward)
    finally:
        close(grid)
