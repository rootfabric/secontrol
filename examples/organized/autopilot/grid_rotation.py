from __future__ import annotations
import math
import time
from typing import Dict, Tuple, List, Optional

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


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


def _scale(v: Tuple[float, float, float], s: float) -> Tuple[float, float, float]:
    return (v[0] * s, v[1] * s, v[2] * s)


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


# ---- Quaternion функции -----------------------------------------------------

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
    # Предполагаем matrix 3x3, rows = forward, up, right
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
    # To pitch, yaw, roll (equation for aircraft-like)
    w, x, y, z = q
    # Yaw (around up axis)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    # Pitch (around right axis)
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)  # use 90 degrees if out of range
    else:
        pitch = math.asin(sinp)

    # Roll (around forward axis)
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
    """
    Получает ориентацию из телеметрии устройства (connector или RC).
    Priority: 1. orientation, 2. Orientation
    """
    tel = device.telemetry or {}
    ori = tel.get("orientation") or tel.get("Orientation")
    if not ori:
        raise RuntimeError(f"Ориентация не найдена в телеметрии {device.name}")

    fwd = _parse_vector(ori.get("forward"))
    up = _parse_vector(ori.get("up"))
    if fwd and up:
        return Basis(fwd, up)
    raise RuntimeError(f"Неправильный format ориентации для {device.name}")


def find_orientation_device(grid) -> BaseDevice:
    """Найти устройство для получения ориентации (pred. connector, then RC)"""
    conns = grid.find_devices_by_type(ConnectorDevice)
    if conns:
        return conns[0]
    rcs = grid.find_devices_by_type(RemoteControlDevice)
    if rcs:
        return rcs[0]
    raise RuntimeError("Нет connector или RC для ориентации")


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


def angle_between_vectors(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    dot = _dot(a, b)
    return math.acos(max(min(dot, 1.0), -1.0))


def check_alignment(current_basis: Basis, desired_basis: Basis, tolerance_deg: float = 0.1) -> bool:
    # Check if forward and up aligned
    fwd_diff = angle_between_vectors(current_basis.forward, desired_basis.forward) * 180 / math.pi
    up_diff = angle_between_vectors(current_basis.up, desired_basis.up) * 180 / math.pi
    right_diff = angle_between_vectors(current_basis.right, desired_basis.right) * 180 / math.pi
    max_diff = max(fwd_diff, up_diff, right_diff)
    return max_diff <= tolerance_deg


# ---- Основная функция -------------------------------------------------------

def align_grid_to_vector(grid_id: str, desired_forward: dict, desired_up: dict, threshold_deg: float = 0.1, max_attempts: int = 100) -> bool:
    """
    Развернуть грид к желаемой ориентации с использованием gyro.
    threshold_deg: точность в градусах
    max_attempts: максAttempts итераций
    Возвращает True если siker, False если timeout.
    """
    grid = prepare_grid(grid_id)
    try:
        orientation_device = find_orientation_device(grid)
        gyros = grid.find_devices_by_type(GyroDevice)
        if not gyros:
            print("Нет gyro устройств!")
            return False

        dfwd = _parse_vector(desired_forward)
        dup = _parse_vector(desired_up)
        if not dfwd or not dup:
            print("Неверные desired vectors")
            return False
        # Инвертировать desired_forward, так как коннектор направлен противоположно для стыковки
        dfwd = _scale(dfwd, -1)
        desired_basis = Basis(dfwd, dup)

        print(f"Начинаем разворот грид {grid_id}")

        for attempt in range(max_attempts):
            # Получить current orientation
            orientation_device.update()
            try:
                current_basis = get_orientation(orientation_device)
            except RuntimeError as e:
                print(f"Ошибка ориентации: {e}. Пропускаем попытку {attempt}")
                continue

            # Вывести текущую телеметрию грида
            current_forward_deg = (current_basis.forward[0], current_basis.forward[1], current_basis.forward[2])
            current_up_deg = (current_basis.up[0], current_basis.up[1], current_basis.up[2])
            current_right_deg = (current_basis.right[0], current_basis.right[1], current_basis.right[2])

            desired_forward_deg = desired_basis.forward
            desired_up_deg = desired_basis.up
            desired_right_deg = desired_basis.right

            # Углы различий в градусах
            fwd_diff = angle_between_vectors(current_basis.forward, desired_basis.forward) * 180 / math.pi
            up_diff = angle_between_vectors(current_basis.up, desired_basis.up) * 180 / math.pi
            right_diff = angle_between_vectors(current_basis.right, desired_basis.right) * 180 / math.pi

            print(f"--- Попытка {attempt} ---")
            print(".2f")
            print(".2f")
            print(f"  Углы различий: fwd={fwd_diff:.2f}°, up={up_diff:.2f}°, right={right_diff:.2f}°")

            # Проверить alignment
            aligned = check_alignment(current_basis, desired_basis, threshold_deg)
            if aligned:
                print("Разворот завершён успешно")
                # Остановить gyro
                for gyro in gyros:
                    gyro.disable()
                return True

            # Расчитать углы
            pitch, yaw, roll = compute_rotation_angles(current_basis, desired_basis)
            # Reduce speeds proportionally
            max_angle = max(abs(pitch), abs(yaw), abs(roll))
            scale = min(1.0, max_angle / (math.pi / 6))  # reduce if close

            p = pitch * scale
            y = yaw * scale
            r = roll * scale

            print(".2f")
            print(f"  Устанавливаем gyro override: pitch={p:.4f}, yaw={y:.4f}, roll={r:.4f}")

            # Установить override на все gyro
            for gyro in gyros:
                gyro.set_override(pitch=p, yaw=y, roll=r)

            time.sleep(0.5)  # Allow rotation

        print(f"Не удалось развернуть за {max_attempts} попыток")
        # Disable gyros
        for gyro in gyros:
            gyro.disable()
        return False

    finally:
        close(grid)


# ---- Тестирование -------------------------------------------------------------

if __name__ == "__main__":
    # Пример из вашего сообщения
    success = align_grid_to_vector(
        grid_id="Owl",
        desired_forward={"x": -0.3490170085715021, "y": 0.6489942765680748, "z": 0.6760129856072892},
        desired_up={"x": 0.6889376377796076, "y": -0.3113129318342129, "z": 0.654560302587501}
    )
    print("Test result:", success)
