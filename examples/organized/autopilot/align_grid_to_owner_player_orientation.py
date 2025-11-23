#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
align_grid_to_owner_player_orientation.py

Выравнивает ориентацию грида под ориентацию владельца-игрока:
форвард и ап грида подгоняются под форвард и ап игрока по данным радара.

Требует:
  - secontrol
  - радар (Ore Detector / другой, который ты используешь как RadarDevice)
  - Remote Control
  - Гироскопы на гриде
"""

from __future__ import annotations

import math
import sys
import time
from typing import Iterable, Tuple

from secontrol.common import close, prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.gyro_device import GyroDevice

# ---------------------------------------------------------------------------
# Настройки

GRID_NAME = "taburet"          # можно переопределить первым аргументом
RADAR_NAME_SUBSTR = "Ore Detector"  # по подстроке имени
REMOTE_NAME_SUBSTR = None      # если None — первый найденный
MAX_ALIGNMENT_TIME = 20.0      # сек, твой таймаут
SLEEP_STEP = 0.05              # шаг цикла, сек

# Контроллер ориентации
FORWARD_WEIGHT = 1.0           # вес ошибки по forward
UP_WEIGHT = 0.7                # вес ошибки по up
MAX_ANGULAR_SPEED = 1.0        # рад/с — ограничение |ω|
ANGLE_TOLERANCE_DEG = 2.0      # если и по forward, и по up ошибка меньше — стоп
OPPOSITE_THRESHOLD = -0.7      # если dot(forward, target_forward) < этого — игнорируем forward

# ---------------------------------------------------------------------------
# Векторная математика

def vec_dot(a: Tuple[float, float, float],
            b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_len(a: Tuple[float, float, float]) -> float:
    return math.sqrt(vec_dot(a, a))


def vec_norm(a: Tuple[float, float, float]) -> Tuple[float, float, float]:
    l = vec_len(a)
    if l <= 1e-8:
        return 0.0, 0.0, 0.0
    return a[0] / l, a[1] / l, a[2] / l


def vec_cross(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ---------------------------------------------------------------------------
# Преобразование мирового ω в локальный (координаты грида)

def world_to_local(
    rc: RemoteControlDevice,
    w: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """
    Преобразует вектор из мировых координат в локальные координаты грида.

    Предполагается наличие у remote метода get_orientation_vectors_world(),
    который возвращает (forward, up, right) в мировых координатах.
    """
    grid_forward, grid_up, grid_right = rc.get_orientation_vectors_world()

    # Базис грида (локальные оси) в мировых координатах
    f = vec_norm(grid_forward)
    u = vec_norm(grid_up)
    r = vec_norm(grid_right)

    # Проекция w на локальные оси даёт компоненты в локальной системе
    # Здесь принимаем convention:
    #   forward -> -pitch
    #   up      -> roll
    #   right   -> yaw
    w_f = vec_dot(w, f)
    w_u = vec_dot(w, u)
    w_r = vec_dot(w, r)

    roll = w_u
    pitch = -w_f
    yaw = w_r
    return roll, pitch, yaw


# ---------------------------------------------------------------------------
# Расчёт угловой скорости выравнивания

def compute_omega_world(
    grid_forward: Tuple[float, float, float],
    grid_up: Tuple[float, float, float],
    target_forward: Tuple[float, float, float],
    target_up: Tuple[float, float, float],
) -> Tuple[
    Tuple[float, float, float],  # ω_world
    float, float,                # angF, angU (рад)
    float, float,                # dotF, dotU
    float                        # error_len (нормированное «суммарное»)
]:
    """
    Строим ось и величину вращения из текущего ориентира на целевой.
    Используем P-контроллер: ω ∝ угол.
    """
    gf = vec_norm(grid_forward)
    gu = vec_norm(grid_up)
    tf = vec_norm(target_forward)
    tu = vec_norm(target_up)

    dotF = clamp(vec_dot(gf, tf), -1.0, 1.0)
    dotU = clamp(vec_dot(gu, tu), -1.0, 1.0)

    angF = math.acos(dotF)  # 0..π
    angU = math.acos(dotU)

    # Основа: оси вращения по forward и up
    axisF = vec_cross(gf, tf)
    axisU = vec_cross(gu, tu)

    use_forward = dotF > OPPOSITE_THRESHOLD  # если почти противоположен — не дёргаем forward

    axis_total = (0.0, 0.0, 0.0)
    lenF = 0.0
    lenU = 0.0

    if use_forward and angF > math.radians(0.5):
        axisF = vec_norm(axisF)
        # P-часть: умножаем на угол и вес
        axisF = (
            axisF[0] * angF * FORWARD_WEIGHT,
            axisF[1] * angF * FORWARD_WEIGHT,
            axisF[2] * angF * FORWARD_WEIGHT,
        )
        lenF = vec_len(axisF)
        axis_total = (
            axis_total[0] + axisF[0],
            axis_total[1] + axisF[1],
            axis_total[2] + axisF[2],
        )

    if angU > math.radians(0.5):
        axisU = vec_norm(axisU)
        axisU = (
            axisU[0] * angU * UP_WEIGHT,
            axisU[1] * angU * UP_WEIGHT,
            axisU[2] * angU * UP_WEIGHT,
        )
        lenU = vec_len(axisU)
        axis_total = (
            axis_total[0] + axisU[0],
            axis_total[1] + axisU[1],
            axis_total[2] + axisU[2],
        )

    error_len = vec_len(axis_total)
    if error_len < 1e-6:
        return (0.0, 0.0, 0.0), angF, angU, dotF, dotU, 0.0

    # Нормируем и масштабируем до максимальной угловой скорости
    dir_axis = (
        axis_total[0] / error_len,
        axis_total[1] / error_len,
        axis_total[2] / error_len,
    )

    # ω = min(error_len, MAX_ANGULAR_SPEED) * dir_axis
    # error_len уже в ~рад*коэффициенты, так что это P с ограничением
    mag = error_len
    if mag > MAX_ANGULAR_SPEED:
        mag = MAX_ANGULAR_SPEED

    omega_world = (
        dir_axis[0] * mag,
        dir_axis[1] * mag,
        dir_axis[2] * mag,
    )

    return omega_world, angF, angU, dotF, dotU, error_len


# ---------------------------------------------------------------------------
# Управление гироскопами

def set_gyros(
    gyros: Iterable[GyroDevice],
    roll: float,
    pitch: float,
    yaw: float,
    override: bool,
) -> None:
    for g in gyros:
        g.set_override(override)
        if override:
            # Метод set_angular_velocity(roll, pitch, yaw) мы уже использовали в других автопилотах
            g.set_angular_velocity(roll=roll, pitch=pitch, yaw=yaw)


def stop_gyros(gyros: Iterable[GyroDevice]) -> None:
    set_gyros(gyros, 0.0, 0.0, 0.0, override=False)


# ---------------------------------------------------------------------------
# Основная логика выравнивания

def align_grid_to_player(
    rc: RemoteControlDevice,
    gyros: Iterable[GyroDevice],
    radar: OreDetectorDevice,
    owner_identity_id: int,
) -> None:
    print("Сканируем игрока-владельца и доворaчиваемся под его наклон...")
    print(f"[main] Grid owner identity id: {owner_identity_id}")

    # 1. Находим игрока и его ориентацию
    print(f"[radar] Scanning for owner identity_id={owner_identity_id}...")
    player = radar.scan_player_by_identity(owner_identity_id)
    if player is None:
        print("[radar] Owner player not found, abort.")
        return

    p_forward = player["forward"]  # (x,y,z)
    p_up = player["up"]            # (x,y,z)
    gravity = player.get("gravity", (0.0, 0.0, 0.0))

    print(
        f"[radar] Found owner player @ {player['position']}, "
        f"|forward|={vec_len(p_forward):.3f}, |up|={vec_len(p_up):.3f}, gravity={gravity}"
    )
    print(
        f"[main] Player orientation updated: "
        f"forward={p_forward}, up={p_up}"
    )

    # 2. Цикл выравнивания
    start = time.time()
    angle_tol = math.radians(ANGLE_TOLERANCE_DEG)

    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= MAX_ALIGNMENT_TIME:
                print(
                    f"[orientation] STOP by TIMEOUT: timeout: elapsed={elapsed:.2f}s"
                )
                break

            grid_forward, grid_up, grid_right = rc.get_orientation_vectors_world()

            omega_world, angF, angU, dotF, dotU, error_len = compute_omega_world(
                grid_forward, grid_up, p_forward, p_up
            )

            # Расчёт ω в локальных координатах для гироскопов
            roll, pitch, yaw = world_to_local(rc, omega_world)

            # Логи в том же стиле, что и у тебя
            print(
                "[orientation] elapsed={:5.2f}s, error_len={:4.3f}, "
                "dotF={:5.4f}, dotU={:5.4f}, angF={:6.2f}°, angU={:6.2f}°, "
                "omega_local=(roll={:+5.3f}, pitch={:+5.3f}, yaw={:+5.3f})".format(
                    elapsed,
                    error_len,
                    dotF,
                    dotU,
                    math.degrees(angF),
                    math.degrees(angU),
                    roll,
                    pitch,
                    yaw,
                )
            )

            # Критерий завершения — небольшие углы по обеим осям
            if angF < angle_tol and angU < angle_tol:
                print(
                    "[orientation] Alignment reached: "
                    f"angF={math.degrees(angF):.2f}°, angU={math.degrees(angU):.2f}°"
                )
                break

            # Применяем ω к гироскопам
            set_gyros(gyros, roll, pitch, yaw, override=True)

            time.sleep(SLEEP_STEP)

    finally:
        # Обязательно выключаем гироскопы
        stop_gyros(gyros)
        print(f"[main] Grid alignment finished: elapsed={time.time() - start:.2f}s")


# ---------------------------------------------------------------------------
# Поиск устройств и запуск

def main() -> None:
    grid_name = GRID_NAME
    if len(sys.argv) > 1:
        grid_name = sys.argv[1]

    cgrid = prepare_grid(grid_name)

    print(
        f"Resolved grid '{grid_name}' to: {grid.entity_id} ({grid.display_name})"
    )

    radar = ctx.find_radar_by_name_substr(RADAR_NAME_SUBSTR)
    if radar is None:
        print(f"Радар с подстрокой имени '{RADAR_NAME_SUBSTR}' не найден, выхожу.")
        close(client)
        return

    print(
        f"Найден радар device_id={radar.device_id} name='{radar.block_name}'"
    )

    rc = ctx.find_remote_control_by_name_substr(REMOTE_NAME_SUBSTR)
    if rc is None:
        print("Remote Control не найден, выхожу.")
        close(client)
        return

    print(
        f"Используется REMOTE CONTROL '{rc.block_name}' (id={rc.device_id})"
    )

    gyros = list(ctx.find_gyros())
    print(f"Найдено гироскопов: {len(gyros)}")
    if not gyros:
        print("Нет гироскопов, выхожу.")
        close(client)
        return

    owner_identity_id = grid.owner_identity_id
    align_grid_to_player(rc, gyros, radar, owner_identity_id)

    close(client)


if __name__ == "__main__":
    main()
