from __future__ import annotations
import math
import time
from typing import Dict, Tuple, List, Optional

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice


# ---- Математика --------------------------------------------------------------

def _vec(value) -> Tuple[float, float, float]:
    return float(value[0]), float(value[1]), float(value[2])


def _cross(a: Tuple[float, ...], b: Tuple[float, ...]) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalize(v: Tuple[float, ...]) -> Tuple[float, float, float]:
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-6:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _parse_vector(value: dict) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return _vec((value["x"], value["y"], value["z"]))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return _vec(value)
    return None


class Basis:
    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        self.forward = _normalize(forward)
        self.up = _normalize(up)
        self.right = _normalize(_cross(self.forward, self.up))


# ---- Quaternion functions ---------------------------------------------------

def quaternion_multiply(q1: Tuple[float, float, float, float], q2: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
    x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
    y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
    z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
    return (w, x, y, z)


def quaternion_normalize(q: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    w, x, y, z = q
    length = math.sqrt(w**2 + x**2 + y**2 + z**2)
    return (w / length, x / length, y / length, z / length)


def matrix_to_quaternion(matrix: List[List[float]]) -> Tuple[float, float, float, float]:
    # Из rotation matrix в quaternion
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0:
        S = math.sqrt(trace + 1.0) * 2
        w = 0.25 * S
        x = (matrix[2][1] - matrix[1][2]) / S
        y = (matrix[0][2] - matrix[2][0]) / S
        z = (matrix[1][0] - matrix[0][1]) / S
    elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
        S = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2
        w = (matrix[2][1] - matrix[1][2]) / S
        x = 0.25 * S
        y = (matrix[0][1] + matrix[1][0]) / S
        z = (matrix[0][2] + matrix[2][0]) / S
    elif matrix[1][1] > matrix[2][2]:
        S = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2
        w = (matrix[0][2] - matrix[2][0]) / S
        x = (matrix[0][1] + matrix[1][0]) / S
        y = 0.25 * S
        z = (matrix[1][2] + matrix[2][1]) / S
    else:
        S = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2
        w = (matrix[1][0] - matrix[0][1]) / S
        x = (matrix[0][2] + matrix[2][0]) / S
        y = (matrix[1][2] + matrix[2][1]) / S
        z = 0.25 * S
    return quaternion_normalize((w, x, y, z))


def quaternion_to_euler(q: Tuple[float, float, float, float]) -> Tuple[float, float, float]:
    # To pitch, yaw, roll
    w, x, y, z = q
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)

    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    return pitch, yaw, roll


def quaternion_inverse(q: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    w, x, y, z = q
    return (w, -x, -y, -z)


def basis_to_quaternion(basis: Basis) -> Tuple[float, float, float, float]:
    # Basis.forward, up, right to rotation matrix then to quaternion
    matrix = [
        [basis.right[0], basis.up[0], basis.forward[0]],
        [basis.right[1], basis.up[1], basis.forward[1]],
        [basis.right[2], basis.up[2], basis.forward[2]]
    ]
    return matrix_to_quaternion(matrix)


# ---- Получение ориентации ---------------------------------------------------

def get_orientation(device: BaseDevice) -> Basis:
    tel = device.telemetry or {}
    ori = tel.get("orientation")
    if not ori:
        raise RuntimeError(f"Ориентация не найдена в телеметрии {device.name}")

    fwd = _parse_vector(ori.get("forward"))
    up = _parse_vector(ori.get("up"))
    if fwd and up:
        return Basis(fwd, up)
    raise RuntimeError(f"Неправильный format ориентации для {device.name}")


# ---- Вычисление углов для поворота ------------------------------------------

def compute_rotation_angles(current_basis: Basis, desired_basis: Basis, threshold_rad: float = 0.002) -> Tuple[float, float, float]:
    # Compute relative quaternion
    q_current = basis_to_quaternion(current_basis)
    q_desired = basis_to_quaternion(desired_basis)
    q_rel = quaternion_multiply(q_desired, quaternion_inverse(q_current))
    # Normalize
    q_rel = quaternion_normalize(q_rel)

    # To euler angles
    pitch, yaw, roll = quaternion_to_euler(q_rel)

    # If angle small, set to 0
    if abs(pitch) < threshold_rad:
        pitch = 0.0
    if abs(yaw) < threshold_rad:
        yaw = 0.0
    if abs(roll) < threshold_rad:
        roll = 0.0

    return pitch, yaw, roll


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
        print(f"Найден игрок, forward: {forward}")
        return forward

    print("Игрок не найден.")
    return None


def simple_align_forward(grid, player_forward: Tuple[float, float, float]):
    """
    Однократный поворот грида к форварду игрока, сохраняя текущий up.
    """
    rc = grid.find_devices_by_type(RemoteControlDevice)
    if not rc:
        print("Не найден RemoteControlDevice")
        return
    rc_dev = rc[0]
    rc_dev.update()

    try:
        current_basis = get_orientation(rc_dev)
    except RuntimeError as e:
        print(f"Ошибка ориентации грида: {e}")
        return

    desired_up = current_basis.up  # сохранение up
    desired_basis = Basis(player_forward, desired_up)

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        print("Не найдены гироскопы")
        return

    print(f"Желаемый forward: ({player_forward[0]:.3f}, {player_forward[1]:.3f}, {player_forward[2]:.3f})")
    print(".3f")
    print(".3f")

    # Расчитать углы
    pitch, yaw, roll = compute_rotation_angles(current_basis, desired_basis)

    print(".3f")

    # Установить override на все gyro
    for gyro in gyros:
        gyro.set_override(pitch=pitch, yaw=yaw, roll=roll)

    time.sleep(1.0)  # дать повернуться

    # Остановить
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
