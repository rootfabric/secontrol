from __future__ import annotations
import math
import time
from typing import Tuple, Optional

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice


# ---- Векторная математика ---------------------------------------------------


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
    Ортонормированный базис (матрица ориентации) объекта.
    Позволяет переводить векторы из Мира в Локальное пространство.
    """

    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        f = _normalize(forward)
        u = _normalize(up)
        r = _cross(f, u)

        # Коррекция вырожденных случаев
        if _length(r) < 1e-6:
            if abs(f[1]) < 0.9:
                u = (0.0, 1.0, 0.0)
            else:
                u = (1.0, 0.0, 0.0)
            u = _normalize(u)
            r = _cross(f, u)

        self.right = _normalize(r)  # Ось X
        self.up = _normalize(_cross(self.right, f))  # Ось Y
        self.forward = f  # Ось -Z (в OpenGL), но в SE Forward обычно -Z
        self.backward = (-f[0], -f[1], -f[2])  # Ось +Z

    def world_to_local(self, world_vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """
        Проецирует мировой вектор на локальные оси (Right, Up, Backward).
        Backward используется как +Z для соответствия правилу правой руки в SE Gyros.
        """
        # Pitch вращает вокруг X (Right)
        # Yaw вращает вокруг Y (Up)
        # Roll вращает вокруг Z (Backward)
        x = _dot(world_vec, self.right)
        y = _dot(world_vec, self.up)
        z = _dot(world_vec, self.backward)
        return (x, y, z)


def get_orientation(device: BaseDevice) -> Basis:
    tel = device.telemetry or {}
    ori = tel.get("orientation")
    if not ori:
        raise RuntimeError(f"Ориентация не найдена {device.name}")
    fwd = _parse_vector(ori.get("forward"))
    up = _parse_vector(ori.get("up"))
    if fwd and up:
        return Basis(fwd, up)
    raise RuntimeError(f"Неверные данные ориентации {device.name}")


# ---- Поиск игрока -----------------------------------------------------------


def get_player_forward(radar: OreDetectorDevice) -> Optional[Tuple[float, float, float]]:
    print("Сканируем игроков...")
    radar.scan(include_players=True, include_grids=False, include_voxels=False)
    contacts = radar.telemetry.get("radar", {}).get("contacts") or []

    # Ищем root (обычно это сам игрок) или любого игрока
    for p in contacts:
        if p.get("type") == "player":
            fwd = p.get("headForward") or p.get("forward")
            if fwd:
                v = _normalize(_vec(fwd))
                print(f"Цель ({p.get('name')}) forward: ({v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f})")
                return v
    print("Игрок не найден.")
    return None


# ---- Основная логика выравнивания -------------------------------------------


def align_grid_robust(grid, desired_forward: Tuple[float, float, float]) -> None:
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    gyros = grid.find_devices_by_type(GyroDevice)

    if not rc_list or not gyros:
        print("Не найден Remote Control или Гироскопы.")
        return

    rc = rc_list[0]
    target_vec = _normalize(desired_forward)

    print(f"Старт стабилизации. Цель: {target_vec}")

    # Константы PID
    Kp = 5.0  # Сила реакции
    MAX_RPM = 30.0  # Ограничение скорости (RPM), чтобы не разнесло
    # В API SE override обычно 0..1 (где 1 это 30 RPM = Pi rad/s), или rad/s напрямую.
    # Библиотека secontrol обычно принимает RPM или 0-1.
    # Предположим, что set_override принимает 0..1 (процент) или rad/s.
    # Обычно в secontrol это "процент от макс силы" или число.
    # Для безопасности будем считать, что 1.0 = 100% мощности (30 RPM).

    TIMEOUT = 20.0
    start_time = time.time()

    try:
        while True:
            if time.time() - start_time > TIMEOUT:
                print("Таймаут.")
                break

            rc.update()
            try:
                # 1. Получаем базис главного контроллера (куда смотрит нос корабля)
                rc_basis = get_orientation(rc)
            except Exception:
                continue

            current_fwd = rc_basis.forward

            # 2. Считаем ошибку через Векторное Произведение
            # axis_world - это вектор оси, вокруг которой надо повернуть корабль в МИРОВЫХ координатах
            # Длина этого вектора = sin(угла ошибки).
            axis_world = _cross(current_fwd, target_vec)
            dot_val = _dot(current_fwd, target_vec)

            # Защита от перекручивания (если цель строго сзади)
            if dot_val < -0.99:
                # Если цель сзади, крутимся вокруг Up, пока не развернемся
                axis_world = rc_basis.up

            # Угол ошибки
            angle = math.acos(max(-1.0, min(1.0, dot_val)))

            if angle < 0.02:  # ~1 градус
                print("Выравнено!")
                break

            # 3. Применяем P-регулятор
            # rotation_cmd_world - это вектор угловой скорости в мировых координатах
            # Чем больше угол, тем быстрее крутим.
            # Если угол маленький, замедляемся (пропорциональное управление).
            factor = min(1.0, angle * Kp)

            # Нормализуем ось вращения и умножаем на силу
            axis_len = _length(axis_world)
            if axis_len > 1e-6:
                rot_cmd_world = (
                    axis_world[0] / axis_len * factor,
                    axis_world[1] / axis_len * factor,
                    axis_world[2] / axis_len * factor
                )
            else:
                rot_cmd_world = (0.0, 0.0, 0.0)

            print(
                f"Angle: {angle:.3f} rad | World Cmd: ({rot_cmd_world[0]:.2f}, {rot_cmd_world[1]:.2f}, {rot_cmd_world[2]:.2f})")

            # 4. Распределяем по гироскопам С УЧЕТОМ ИХ ОРИЕНТАЦИИ
            for gyro in gyros:
                try:
                    gyro_basis = get_orientation(gyro)

                    # Проецируем МИРОВОЙ вектор вращения на ЛОКАЛЬНЫЕ оси конкретного гироскопа
                    local_rot = gyro_basis.world_to_local(rot_cmd_world)

                    # В SE:
                    # Pitch Override (+) -> Нос вниз (вращение вокруг +X)
                    # Yaw Override (+)   -> Нос влево (вращение вокруг +Y)
                    # Roll Override (+)  -> Крен вправо (вращение вокруг +Z)
                    # Но мат. вектор вращения обычно "против часовой".
                    # Обычно требуется инверсия.

                    # Коэффициент пересчета (подбирается экспериментально, обычно -1 или 1)
                    # При projection logic часто требуется инверсия для Pitch и Yaw

                    cmd_pitch = -local_rot[0]
                    cmd_yaw = -local_rot[1]
                    cmd_roll = -local_rot[2]

                    # Ограничение (clamp) от -1 до 1
                    cmd_pitch = max(-1.0, min(1.0, cmd_pitch))
                    cmd_yaw = max(-1.0, min(1.0, cmd_yaw))
                    cmd_roll = max(-1.0, min(1.0, cmd_roll))

                    gyro.set_override(pitch=cmd_pitch, yaw=cmd_yaw, roll=cmd_roll)

                except Exception:
                    pass

            time.sleep(0.1)

    finally:
        print("Сброс гироскопов.")
        for gyro in gyros:
            gyro.set_override(pitch=0, yaw=0, roll=0)
            gyro.disable()


# ---- Запуск -----------------------------------------------------------------


if __name__ == "__main__":
    grid_name = "taburet"
    grid = prepare_grid(grid_name)
    try:
        radars = grid.find_devices_by_type(OreDetectorDevice)
        if radars:
            target = get_player_forward(radars[0])
            if target:
                align_grid_robust(grid, target)
        else:
            print("Радар не найден")
    finally:
        close(grid)