from __future__ import annotations
import math
import time
from typing import Tuple, Optional

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice


# ---- Математика -------------------------------------------------------------


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
    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        f = _normalize(forward)
        u = _normalize(up)
        r = _cross(f, u)
        if _length(r) < 1e-6:
            if abs(f[1]) < 0.9:
                u = (0.0, 1.0, 0.0)
            else:
                u = (1.0, 0.0, 0.0)
            u = _normalize(u)
            r = _cross(f, u)
        self.right = _normalize(r)
        self.up = _normalize(_cross(self.right, f))
        self.forward = f
        self.backward = (-f[0], -f[1], -f[2])

    def world_to_local(self, world_vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
        x = _dot(world_vec, self.right)
        y = _dot(world_vec, self.up)
        z = _dot(world_vec, self.backward)
        return (x, y, z)


def get_orientation(device: BaseDevice) -> Optional[Basis]:
    tel = device.telemetry or {}
    ori = tel.get("orientation")
    if not ori:
        return None  # Возвращаем None вместо ошибки, чтобы обработать это мягко
    fwd = _parse_vector(ori.get("forward"))
    up = _parse_vector(ori.get("up"))
    if fwd and up:
        return Basis(fwd, up)
    return None


# ---- Поиск игрока -----------------------------------------------------------


def get_player_forward(radar: OreDetectorDevice) -> Optional[Tuple[float, float, float]]:
    # print("Сканируем игроков...") # Закомментировал, чтобы не спамить в лог
    radar.scan(include_players=True, include_grids=False, include_voxels=False)
    contacts = radar.telemetry.get("radar", {}).get("contacts") or []
    for p in contacts:
        if p.get("type") == "player":
            fwd = p.get("headForward") or p.get("forward")
            if fwd:
                return _normalize(_vec(fwd))
    return None


# ---- Управление -------------------------------------------------------------


def align_grid_robust(grid, desired_forward: Tuple[float, float, float], radar: OreDetectorDevice) -> None:
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    gyros = grid.find_devices_by_type(GyroDevice)

    if not rc_list or not gyros:
        print("Ошибка: Нет Remote Control или Гироскопов")
        return

    rc = rc_list[0]

    # PID settings
    GAIN = 5.0
    MAX_RATE = 1.0

    print(f"Старт. Цель: {desired_forward}")
    counter = 0

    try:
        while True:
            # 1. ОБЯЗАТЕЛЬНО обновляем данные RC
            rc.update()

            # Периодическое обновление цели
            counter += 1
            if counter % 10 == 0:  # Раз в секунду (при sleep 0.1)
                new_fwd = get_player_forward(radar)
                if new_fwd:
                    desired_forward = new_fwd

            rc_basis = get_orientation(rc)
            if not rc_basis:
                print("Нет ориентации RC!")
                time.sleep(0.1)
                continue

            # 2. Математика ошибки (в мировых координатах)
            current_fwd = rc_basis.forward
            dot_val = max(-1.0, min(1.0, _dot(current_fwd, desired_forward)))
            angle = math.acos(dot_val)

            if angle < 0.02:
                # Если почти выровнялись - сбрасываем гироскопы и ждем
                for gyro in gyros:
                    gyro.set_override(pitch=0, yaw=0, roll=0)
                time.sleep(0.1)
                continue

            # Ось вращения в мире (cross product)
            axis_world = _cross(current_fwd, desired_forward)
            axis_len = _length(axis_world)

            # Если ось вырождена (мы ровно задом к цели), берем Up
            if axis_len < 1e-6:
                if dot_val < 0:
                    axis_world = rc_basis.up
                else:
                    axis_world = (0.0, 0.0, 0.0)
            else:
                # Нормализация
                axis_world = (axis_world[0] / axis_len, axis_world[1] / axis_len, axis_world[2] / axis_len)

            # Масштабирование (P-контроллер)
            cmd_mag = min(MAX_RATE, angle * GAIN)
            rot_cmd_world = (
                axis_world[0] * cmd_mag,
                axis_world[1] * cmd_mag,
                axis_world[2] * cmd_mag
            )

            if counter % 5 == 0:
                print(
                    f"Err: {angle:.2f} rad | WorldCmd: ({rot_cmd_world[0]:.2f}, {rot_cmd_world[1]:.2f}, {rot_cmd_world[2]:.2f})")

            # 3. Применение к гироскопам
            for i, gyro in enumerate(gyros):
                # !!! КРИТИЧЕСКИ ВАЖНО: Обновляем гироскоп, чтобы получить его ориентацию !!!
                gyro.update()

                gyro_basis = get_orientation(gyro)

                if gyro_basis:
                    # Умный режим: переводим мировую команду в локальную для этого конкретного гироскопа
                    local_rot = gyro_basis.world_to_local(rot_cmd_world)

                    # Инверсия знаков (стандарт SE для Override)
                    # P = -local_x, Y = -local_y, R = -local_z
                    p = -local_rot[0]
                    y = -local_rot[1]
                    r = -local_rot[2]

                    if counter % 10 == 0 and i == 0:
                        print(f"[DEBUG] Gyro{i} (Adaptive): P={p:.2f}, Y={y:.2f}, R={r:.2f}")
                else:
                    # Режим "вслепую" (Fallback): Если ориентация гироскопа неизвестна,
                    # считаем, что он стоит так же, как RC.
                    # Это лучше, чем ничего.
                    local_rot = rc_basis.world_to_local(rot_cmd_world)
                    p = -local_rot[0]
                    y = -local_rot[1]
                    r = -local_rot[2]

                    if counter % 10 == 0 and i == 0:
                        print(f"[DEBUG] Gyro{i} (Fallback/Blind): P={p:.2f}, Y={y:.2f}, R={r:.2f}")

                # Clamp
                p = max(-1.0, min(1.0, p))
                y = max(-1.0, min(1.0, y))
                r = max(-1.0, min(1.0, r))

                gyro.set_override(pitch=p, yaw=y, roll=r)

            time.sleep(0.1)

    finally:
        print("Стоп.")
        for gyro in gyros:
            gyro.set_override(pitch=0, yaw=0, roll=0)
            gyro.disable()


# ---- Запуск -----------------------------------------------------------------


if __name__ == "__main__":
    grid = prepare_grid("taburet")
    try:
        radars = grid.find_devices_by_type(OreDetectorDevice)
        if radars:
            target = get_player_forward(radars[0])
            if target:
                align_grid_robust(grid, target, radars[0])
            else:
                print("Игрок не найден")
        else:
            print("Радар не найден")
    finally:
        close(grid)