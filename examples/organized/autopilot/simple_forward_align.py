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


def get_player_forward(radar: OreDetectorDevice) -> Optional[Tuple[float, float, float]]:
    print("Сканируем игроков...")
    radar.scan(include_players=True, include_grids=False, include_voxels=False)

    contacts = radar.telemetry.get("radar", {}).get("contacts") or []
    for p in contacts:
        if p.get("type") != "player":
            continue

        # Пытаемся получить направление взгляда, или просто направление тела
        forward_list = p.get("headForward") or p.get("forward")
        if not forward_list:
            continue

        forward = _normalize(_vec(forward_list))
        print(
            f"Найден игрок {p.get('name', 'Unknown')}, forward: ({forward[0]:.3f}, {forward[1]:.3f}, {forward[2]:.3f})")
        return forward

    print("Игрок не найден.")
    return None


# ---- Логика управления гироскопами (Прямая проекция) ------------------------


def align_grid_to_vector(grid, desired_forward: Tuple[float, float, float], radar: OreDetectorDevice) -> None:
    rc_list = grid.find_devices_by_type(RemoteControlDevice)
    if not rc_list:
        print("Не найден RemoteControlDevice")
        return
    rc_dev = rc_list[0]

    gyros = grid.find_devices_by_type(GyroDevice)
    if not gyros:
        print("Не найдены гироскопы")
        return

    desired_forward = _normalize(desired_forward)
    print(f"Целевой вектор: ({desired_forward[0]:.3f}, {desired_forward[1]:.3f}, {desired_forward[2]:.3f})")

    # Настройки PID (здесь только P - пропорциональный)
    GAIN = 5.0  # Коэффициент усиления ("резкость" поворота)
    MAX_RATE = 1.0  # Максимальная скорость вращения (1.0 = 100% override)
    TOLERANCE = 0.02  # Допустимая ошибка (в радианах, ~1 градус)
    SCAN_INTERVAL = 10  # Интервал сканирования в итерациях (10 * 0.1s = 1s)

    counter = 0

    try:
        while True:
            rc_dev.update()

            # Периодическое сканирование игрока
            counter += 1
            if counter % SCAN_INTERVAL == 0:
                new_fwd = get_player_forward(radar)
                if new_fwd:
                    desired_forward = _normalize(new_fwd)
                    print(f"Обновленный целевой вектор: ({desired_forward[0]:.3f}, {desired_forward[1]:.3f}, {desired_forward[2]:.3f})")

            try:
                basis = get_orientation(rc_dev)
            except RuntimeError:
                continue

            # 1. Текущее отклонение (угол)
            dot_val = max(-1.0, min(1.0, _dot(basis.forward, desired_forward)))
            angle_error = math.acos(dot_val)

            if angle_error < TOLERANCE:
                # Выровнено, устанавливаем команды в ноль
                pitch_cmd = 0.0
                yaw_cmd = 0.0
                print(f"Выровнено. Ошибка: {angle_error:.4f} rad, команды отключены")
            else:
                # 2. Переводим целевой вектор в ЛОКАЛЬНЫЕ координаты корабля.
                # Это ключевой момент:
                # local_x > 0 значит цель справа -> нужно Yaw вправо
                # local_y > 0 значит цель сверху -> нужно Pitch вверх
                local_x = _dot(desired_forward, basis.right)
                local_y = _dot(desired_forward, basis.up)
                # local_z нам не так важен для руления, он показывает, спереди цель или сзади

                # 3. Рассчитываем команды для гироскопов
                # В Space Engineers:
                # Pitch: (+) нос вниз, (-) нос вверх.
                # Yaw:   (+) нос влево, (-) нос вправо.

                # Если цель сверху (local_y > 0), нам нужен Pitch ВВЕРХ (отрицательный override).
                pitch_cmd = -local_y * GAIN

                # Если цель справа (local_x > 0), нам нужен Yaw ВПРАВО (отрицательный override).
                yaw_cmd = -local_x * GAIN

                # Логирование только при вращении
                print(
                    f"Angle: {angle_error:.3f} rad | "
                    f"Local tgt: [R={local_x:.2f}, U={local_y:.2f}] | "
                    f"CMD: P={pitch_cmd:.2f}, Y={yaw_cmd:.2f}"
                )

            # Roll держим на нуле, чтобы не крутиться колбасой
            roll_cmd = 0.0

            # 4. Ограничиваем (Clamp) значения от -MAX_RATE до +MAX_RATE
            pitch_cmd = max(-MAX_RATE, min(MAX_RATE, pitch_cmd))
            yaw_cmd = max(-MAX_RATE, min(MAX_RATE, yaw_cmd))

            # 5. Применяем
            for gyro in gyros:
                gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            time.sleep(0.1)

    finally:
        # Всегда отключаем оверрайд при выходе
        print("Остановка гироскопов...")
        for gyro in gyros:
            gyro.set_override(pitch=0, yaw=0, roll=0)
            gyro.disable()


# ---- Main -------------------------------------------------------------------


if __name__ == "__main__":
    # Замените 'taburet' на имя вашего грида
    grid_name = "taburet"

    grid = prepare_grid(grid_name)
    try:
        radars = grid.find_devices_by_type(OreDetectorDevice)
        if not radars:
            print("Не найден OreDetectorDevice (для сканирования игрока)")
        else:
            radar = radars[0]
            player_fwd = get_player_forward(radar)

            if player_fwd:
                align_grid_to_vector(grid, player_fwd, radar)
            else:
                print("Не удалось получить вектор игрока.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")
    finally:
        close(grid)
