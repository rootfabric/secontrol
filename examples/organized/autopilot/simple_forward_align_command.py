"""Пример выравнивания грида с помощью новой команды гироскопа ``align_vector``.

Скрипт ищет игрока через Ore Detector, берёт его forward-вектор и просит первый
гироскоп на гриде выровнять корабль по этому направлению. Для удобства
дублируется лог прогресса через Remote Control (если он есть).
"""

from __future__ import annotations

import math
import time
from typing import Optional, Tuple

from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


Vector3 = Tuple[float, float, float]


def _vec(value) -> Vector3:
    return float(value[0]), float(value[1]), float(value[2])


def _length(v: Vector3) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _normalize(v: Vector3) -> Vector3:
    length = _length(v)
    if length < 1e-6:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _angle_between(a: Vector3, b: Vector3) -> float:
    a_n = _normalize(a)
    b_n = _normalize(b)
    dot = max(-1.0, min(1.0, _dot(a_n, b_n)))
    return math.acos(dot)


def get_player_forward(radar: OreDetectorDevice) -> Optional[Vector3]:
    print("Сканируем игроков...")
    radar.scan(include_players=True, include_grids=False, include_voxels=False)
    radar.wait_for_telemetry()

    contacts = radar.telemetry.get("radar", {}).get("contacts") or []
    for p in contacts:
        if p.get("type") != "player":
            continue

        forward_list = p.get("headForward") or p.get("forward")
        if not forward_list:
            continue

        forward = _normalize(_vec(forward_list))
        print(
            f"Найден игрок {p.get('name', 'Unknown')}, forward: "
            f"({forward[0]:.3f}, {forward[1]:.3f}, {forward[2]:.3f})"
        )
        return forward

    print("Игрок не найден.")
    return None


def log_alignment_progress(rc: Optional[RemoteControlDevice], target: Vector3) -> None:
    """Отслеживает приближение forward-вектора к цели через Remote Control."""

    if rc is None:
        print("Remote Control не найден, прогресс не отслеживается.")
        return

    for _ in range(40):
        rc.update()
        if not rc.wait_for_telemetry(0.25):
            time.sleep(0.25)
            continue

        try:
            forward, _, _ = rc.get_orientation_vectors_world()
        except Exception:
            time.sleep(0.25)
            continue

        angle = _angle_between(forward, target)
        print(f"Текущая ошибка: {math.degrees(angle):.2f}°")
        if angle < 0.01:
            print("Выровнено.")
            return
        time.sleep(0.25)


if __name__ == "__main__":
    grid_name = "taburet"  # Замените на имя вашего грида

    grid = prepare_grid(grid_name)
    try:
        radars = grid.find_devices_by_type(OreDetectorDevice)
        radar = radars[0] if radars else None

        target_forward: Optional[Vector3] = None
        if radar:
            target_forward = get_player_forward(radar)

        if target_forward is None:
            target_forward = (0.0, 0.0, -1.0)
            print("Используем дефолтный вектор (0,0,-1)")

        gyros = grid.find_devices_by_type(GyroDevice)
        if not gyros:
            print("Не найдено ни одного гироскопа")
            raise SystemExit(1)

        gyro = gyros[0]
        gyro.enable()
        print(
            "Отправляем команду align_vector на гироскоп: "
            f"({target_forward[0]:.3f}, {target_forward[1]:.3f}, {target_forward[2]:.3f})"
        )
        gyro.align_vector(target_forward)

        rc_list = grid.find_devices_by_type(RemoteControlDevice)
        rc_dev = rc_list[0] if rc_list else None
        log_alignment_progress(rc_dev, target_forward)

    except Exception as exc:  # noqa: BLE001 - примерный скрипт
        print(f"Произошла ошибка: {exc}")
    finally:
        close(grid)
