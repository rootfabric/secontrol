from __future__ import annotations
import math
import time
from typing import Tuple, Optional

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


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
    """

    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        f = _normalize(forward)
        u = _normalize(up)
        r = _cross(f, u)

        # Обработка вырожденных случаев
        if _length(r) < 1e-6:
            if abs(f[1]) < 0.9:
                u = (0.0, 1.0, 0.0)
            else:
                u = (1.0, 0.0, 0.0)
            u = _normalize(u)
            r = _cross(f, u)

        self.right = _normalize(r)
        # Пересчитываем Up, чтобы он был строго перпендикулярен Forward и Right
        self.up = _normalize(_cross(self.right, f))
        self.forward = f


# ---- Ориентация -------------------------------------------------------------


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


def get_gravity(device: BaseDevice) -> Optional[Tuple[float, float, float]]:
    tel = device.telemetry or {}
    g = tel.get("gravitationalVector")
    if g:
        vec = _parse_vector(g)
        if vec:
            # Up is opposite to gravity
            return (-vec[0], -vec[1], -vec[2])
    return None


# ---- Логика управления гироскопами (Выравнивание Up по гравитации) ------------------------


def align_grid_to_gravity(grid) -> None:
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        print("Не найден RemoteControlDevice")
        return
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        print("Не найдены гироскопы")
        return

    for gyro in gyros:
        gyro.enable()


    gravity_vec = get_gravity(rc_dev)
    if not gravity_vec:
        print("Вектор гравитации не найден")
        return

    # Desired up is opposite to gravity, normalized
    desired_up = _normalize((-gravity_vec[0], -gravity_vec[1], -gravity_vec[2]))

    # Ensure always upright: Y component >= 0
    if desired_up[1] < 0:
        desired_up = (-desired_up[0], -desired_up[1], -desired_up[2])

    print(f"Целевой up вектор: ({desired_up[0]:.3f}, {desired_up[1]:.3f}, {desired_up[2]:.3f})")

    # Настройки PID (здесь только P - пропорциональный)
    GAIN = 2.0  # Коэффициент усиления ("резкость" поворота)
    MAX_RATE = 1.0  # Максимальная скорость вращения (1.0 = 100% override)
    TOLERANCE = 0.01  # Допустимая ошибка (в радианах, ~2 градуса)

    try:
        while True:
            rc_dev.update()

            try:
                basis = get_orientation(rc_dev)
            except RuntimeError:
                continue

            # 1. Текущее отклонение (угол)
            dot_val = max(-1.0, min(1.0, _dot(basis.up, desired_up)))
            angle_error = math.acos(dot_val)

            if angle_error < TOLERANCE or (abs(dot_val) > 0.99 and dot_val > 0):
                # Выровнено
                print(f"Выровнено. Ошибка: {angle_error:.4f} rad, команды отключены")
                for gyro in gyros:
                    gyro.clear_override()
                break
            else:
                # 2. Переводим целевой вектор в ЛОКАЛЬНЫЕ координаты корабля.
                # Для выравнивания Up: проекции на Forward и Right
                local_y = _dot(desired_up, basis.forward)
                local_x = _dot(desired_up, basis.right)

                roll_cmd = 0.0

                # Для Up: исправленный знак
                pitch_cmd = -local_y * GAIN

                # Если desired в right направлении, yaw -
                yaw_cmd = -local_x * GAIN

                # Логирование только при вращении
                print(
                    f"Angle: {angle_error:.3f} rad | "
                    f"Local tgt: [F={local_y:.2f}, R={local_x:.2f}] | "
                    f"CMD: R={roll_cmd:.2f}, P={pitch_cmd:.2f}, Y={yaw_cmd:.2f}"
                )

            # 3. Ограничиваем (Clamp) значения от -MAX_RATE до +MAX_RATE
            pitch_cmd = max(-MAX_RATE, min(MAX_RATE, pitch_cmd))
            yaw_cmd = max(-MAX_RATE, min(MAX_RATE, yaw_cmd))

            # 4. Применяем
            for gyro in gyros:
                gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            time.sleep(0.1)


    finally:
        # Всегда отключаем оверрайд при выходе
        print("Остановка гироскопов...")
        for gyro in gyros:
            gyro.clear_override()



# ---- Main -------------------------------------------------------------------


if __name__ == "__main__":
    # Замените 'taburet' на имя вашего грида
    grid_name = "taburet"


    grid = prepare_grid(grid_name)
    try:
        align_grid_to_gravity(grid)
    except Exception as e:
        print(f"Произошла ошибка: {e}")
    finally:
        close(grid)
