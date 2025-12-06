"""Утилиты для перемещения и ориентации грида.

Функции основаны на примерах автопилота и выравнивания по гравитации,
но вынесены в отдельный модуль для повторного использования и
упрощения основной логики сценариев управления дронами.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Iterable, Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice, Grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.common import prepare_grid


# ---- Базовая математика -----------------------------------------------------


def _vec(value: Sequence[float]) -> Tuple[float, float, float]:
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


def _dist(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _parse_vector(value: object) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) >= 5 and parts[0] == "GPS":
            return float(parts[2]), float(parts[3]), float(parts[4])
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return _vec((value["x"], value["y"], value["z"]))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return _vec(value)
    return None


class Basis:
    """Прямоугольный базис корабля в мировых координатах."""

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


# ---- Вспомогательные функции -------------------------------------------------


def get_orientation(device: BaseDevice) -> Basis:
    tel = device.telemetry or {}
    ori = tel.get("orientation") or tel.get("Orientation")
    if not ori:
        raise RuntimeError(f"Ориентация не найдена в телеметрии {device.name}")

    fwd = _parse_vector(ori.get("forward"))
    up = _parse_vector(ori.get("up"))
    if fwd and up:
        return Basis(fwd, up)

    raise RuntimeError(f"Неправильный формат ориентации для {device.name}")


def get_gravity_up(device: BaseDevice) -> Optional[Tuple[float, float, float]]:
    tel = device.telemetry or {}
    g = tel.get("gravitationalVector")
    if g:
        vec = _parse_vector(g)
        if vec:
            return _normalize((-vec[0], -vec[1], -vec[2]))
    return None


def get_world_position(device: BaseDevice) -> Optional[Tuple[float, float, float]]:
    tel = device.telemetry or {}
    pos = tel.get("worldPosition") or tel.get("position")
    if pos:
        return _parse_vector(pos)
    return None


# ---- Перелёт к точке ---------------------------------------------------------


def fly_to_point(
    remote: RemoteControlDevice,
    target: Tuple[float, float, float],
    *,
    waypoint_name: str = "Target",
    speed_far: float = 15.0,
    speed_near: float = 5.0,
    arrival_distance: float = 0.2,
    stop_tolerance: float = 0.7,
    max_flight_time: float = 240.0,
    check_interval: float = 0.2,
    cancel_check: Optional[Callable[[], bool]] = None,
    ship_connector: Optional[ConnectorDevice] = None,
    connector_target: Optional[Tuple[float, float, float]] = None,
) -> Optional[Tuple[float, float, float]]:
    """
    Компактная обёртка над автопилотом для полёта к точке.

    Аргумент ``cancel_check`` позволяет вызывать любую функцию для
    ранней остановки полёта (например, проверка условий или флаг из
    параллельного потока). Возвращает последнюю известную позицию RC
    или ``None``, если автопилот не стартовал.
    """

    curr_pos = get_world_position(remote)
    if not curr_pos:
        remote.update()
        curr_pos = get_world_position(remote)
    if not curr_pos:
        raise RuntimeError("Не удалось получить позицию RemoteControl")

    dist = _dist(curr_pos, target)
    speed = speed_far if dist > 15.0 else speed_near
    gps = f"GPS:{waypoint_name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(gps, speed=speed, gps_name=waypoint_name, dock=False)

    if ship_connector:
        ship_connector.update()

    engaged = False
    for _ in range(15):
        time.sleep(0.2)
        remote.update()
        if remote.telemetry.get("autopilotEnabled"):
            engaged = True
            break
    if not engaged:
        return None

    start_t = time.time()
    stop_pos = curr_pos

    while True:
        if cancel_check and cancel_check():
            remote.disable()
            break

        remote.update()
        if ship_connector:
            ship_connector.update()
        pos = get_world_position(remote)
        if not pos:
            time.sleep(check_interval)
            continue

        stop_pos = pos
        distance = _dist(pos, target)

        if distance < arrival_distance:
            break

        if cancel_check and cancel_check():
            remote.disable()
            break

        if distance < 1.0 and connector_target and ship_connector:
            conn_pos = get_world_position(ship_connector)
            if conn_pos and _dist(conn_pos, connector_target) < arrival_distance:
                remote.disable()
                break

        if not remote.telemetry.get("autopilotEnabled"):
            if distance < stop_tolerance:
                break
            return stop_pos

        if time.time() - start_t > max_flight_time:
            remote.disable()
            break

        time.sleep(check_interval)

    return stop_pos


# ---- Повороты с гироскопами --------------------------------------------------


def _enable_gyros(gyros: Iterable[GyroDevice]) -> None:
    for gyro in gyros:
        gyro.enable()


def _clear_gyro_override(gyros: Iterable[GyroDevice]) -> None:
    for gyro in gyros:
        gyro.clear_override()


def align_to_up_vector(
    grid,
    desired_up: Tuple[float, float, float],
    *,
    gain: float = 2.0,
    max_rate: float = 1.0,
    tolerance: float = 0.01,
    check_interval: float = 0.1,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Выравнивает грид так, чтобы ``Up`` совпал с ``desired_up``.

    Подходит для случаев, когда цель «показать верх» заранее известна
    (например, выравнивание по искусственному вектору). Для более
    удобной работы можно передать ``cancel_check`` — функция вернёт
    управление, если она начинает возвращать ``True``.
    """

    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        raise RuntimeError("RemoteControlDevice не найден")
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        raise RuntimeError("Гироскопы не найдены")

    desired_up = _normalize(desired_up)
    _enable_gyros(gyros)

    try:
        while True:
            if cancel_check and cancel_check():
                break

            rc_dev.update()
            try:
                basis = get_orientation(rc_dev)
            except RuntimeError:
                time.sleep(check_interval)
                continue

            dot_val = max(-1.0, min(1.0, _dot(basis.up, desired_up)))
            angle_error = math.acos(dot_val)

            if angle_error < tolerance or (abs(dot_val) > 0.99 and dot_val > 0):
                _clear_gyro_override(gyros)
                break

            local_y = _dot(desired_up, basis.forward)
            local_x = _dot(desired_up, basis.right)

            roll_cmd = 0.0
            pitch_cmd = -local_y * gain
            yaw_cmd = -local_x * gain

            pitch_cmd = max(-max_rate, min(max_rate, pitch_cmd))
            yaw_cmd = max(-max_rate, min(max_rate, yaw_cmd))

            for gyro in gyros:
                gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            time.sleep(check_interval)
    finally:
        _clear_gyro_override(gyros)


def align_to_gravity(
    grid,
    *,
    gain: float = 2.0,
    max_rate: float = 1.0,
    tolerance: float = 0.01,
    check_interval: float = 0.1,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Упрощённый вызов ``align_to_up_vector`` для выравнивания по гравитации."""

    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        raise RuntimeError("RemoteControlDevice не найден")
    rc_dev = rc_list[0]
    up_vec = get_gravity_up(rc_dev)
    if not up_vec:
        raise RuntimeError("Вектор гравитации не найден")
    align_to_up_vector(
        grid,
        up_vec,
        gain=gain,
        max_rate=max_rate,
        tolerance=tolerance,
        check_interval=check_interval,
        cancel_check=cancel_check,
    )


def align_heading_with_gravity(
    grid,
    target_forward: Tuple[float, float, float],
    *,
    gain: float = 2.0,
    max_rate: float = 1.0,
    tolerance: float = 0.01,
    check_interval: float = 0.1,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Совмещает ``Up`` по гравитации и поворачивает корабль на заданный угол по
    горизонту (проекция ``target_forward`` на плоскость).

    Функция остаётся компактной: в основной логике достаточно передать
    целевой вектор и (по желанию) колбэк ``cancel_check``.
    """

    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        raise RuntimeError("RemoteControlDevice не найден")
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        raise RuntimeError("Гироскопы не найдены")

    gravity_up = get_gravity_up(rc_dev)
    if not gravity_up:
        raise RuntimeError("Вектор гравитации не найден")

    desired_up = gravity_up
    forward_proj = _normalize(
        (
            target_forward[0] - _dot(target_forward, desired_up) * desired_up[0],
            target_forward[1] - _dot(target_forward, desired_up) * desired_up[1],
            target_forward[2] - _dot(target_forward, desired_up) * desired_up[2],
        )
    )

    _enable_gyros(gyros)

    try:
        while True:
            if cancel_check and cancel_check():
                break

            rc_dev.update()
            try:
                basis = get_orientation(rc_dev)
            except RuntimeError:
                time.sleep(check_interval)
                continue

            dot_up = max(-1.0, min(1.0, _dot(basis.up, desired_up)))
            angle_up = math.acos(dot_up)

            flat_forward = _normalize(
                (
                    basis.forward[0] - _dot(basis.forward, desired_up) * desired_up[0],
                    basis.forward[1] - _dot(basis.forward, desired_up) * desired_up[1],
                    basis.forward[2] - _dot(basis.forward, desired_up) * desired_up[2],
                )
            )
            dot_forward = max(-1.0, min(1.0, _dot(flat_forward, forward_proj)))
            angle_yaw = math.acos(dot_forward)
            yaw_sign = 1.0 if _dot(_cross(flat_forward, forward_proj), desired_up) > 0 else -1.0

            if angle_up < tolerance and angle_yaw < tolerance:
                _clear_gyro_override(gyros)
                break

            local_y = _dot(desired_up, basis.forward)
            local_x = _dot(desired_up, basis.right)

            roll_cmd = 0.0
            pitch_cmd = -local_y * gain
            yaw_cmd = -local_x * gain + yaw_sign * angle_yaw * gain

            pitch_cmd = max(-max_rate, min(max_rate, pitch_cmd))
            yaw_cmd = max(-max_rate, min(max_rate, yaw_cmd))

            for gyro in gyros:
                gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            time.sleep(check_interval)
    finally:
        _clear_gyro_override(gyros)




def goto(ship_grid: Grid, point_target: str | Tuple[float, float, float] = None, speed = 10):

    if isinstance(point_target, (tuple, list)) and len(point_target) == 3:
        try:
            x, y, z = map(float, point_target)
            point_target = f"GPS:Target:{x:.6f}:{y:.6f}:{z:.6f}:"
        except (ValueError, TypeError):
            raise ValueError("Invalid point_target format")

    remote = ship_grid.get_first_device(RemoteControlDevice)

    print(f"Target GPS: {point_target}")

    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(point_target, speed=speed)

    time.sleep(1)

    # remote.disable()
    while True:
        remote.update()
        remote.wait_for_telemetry()
        autopilotEnabled = remote.telemetry.get("autopilotEnabled", True)

        if not autopilotEnabled:
            break
        print(remote.telemetry.get("position"))
        time.sleep(1)
