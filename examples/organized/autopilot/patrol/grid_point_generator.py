#!/usr/bin/env python3
"""
Генератор сетки точек патрулирования вокруг базы.

Этот скрипт создает 10x10 сетку точек (100 точек) вокруг позиции базы,
размещенных в горизонтальной плоскости корабля, с расстоянием 100 метров между точками.
Точки добавляются как GPS-маркеры для использования разведчиком.
"""

from __future__ import annotations
import math
import time
from typing import Tuple, List

from secontrol.base_device import BaseDevice
from secontrol.common import prepare_grid, close
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


def _parse_vector(value) -> Tuple[float, float, float] | None:
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


# ---- Генерация сетки точек --------------------------------------------------

class CoordinateGridGenerator:
    """
    Класс для генерации сеток координат вокруг базы.
    """

    @staticmethod
    def generate_grid(
        base_pos: Tuple[float, float, float],
        ship_forward: Tuple[float, float, float],
        ship_up: Tuple[float, float, float],
        grid_size: int = 10,
        spacing: float = 1000.0
    ) -> List[Tuple[float, float, float]]:
        """
        Генерирует сетку точек патрулирования вокруг базы.

        Args:
            base_pos: Позиция базы (центр сетки) в мировых координатах (x, y, z).
            ship_forward: Вектор вперед корабля в мировых координатах.
            ship_up: Вектор вверх корабля в мировых координатах.
            grid_size: Размер сетки (число точек по каждой оси, 10x10 = 100 точек).
            spacing: Расстояние между точками в метрах.

        Returns:
            Список координат точек (x, y, z).
        """
        basis = Basis(ship_forward, ship_up)
        points = []

        # Центр сетки - начало координат
        # Точки от -(grid_size-1)/2 * spacing до +(grid_size-1)/2 * spacing
        start_offset = -(grid_size - 1) / 2 * spacing

        for i in range(grid_size):
            for j in range(grid_size):
                offset_right = start_offset + i * spacing
                offset_forward = start_offset + j * spacing

                point = (
                    base_pos[0] + basis.right[0] * offset_right + basis.forward[0] * offset_forward,
                    base_pos[1] + basis.right[1] * offset_right + basis.forward[1] * offset_forward,
                    base_pos[2] + basis.right[2] * offset_right + basis.forward[2] * offset_forward,
                )
                points.append(point)

        return points


# ---- Main -------------------------------------------------------------------

def main():
    # Замените 'taburet' на имя вашего грида
    grid_name = "taburet"

    grid = prepare_grid(grid_name)
    try:
        # Находим RemoteControlDevice для получения позиции и ориентации
        rc_list = grid.find_devices_by_type(RemoteControlDevice)
        if not rc_list:
            print("Не найден RemoteControlDevice")
            return
        rc_dev = rc_list[0]

        # Обновляем телеметрию
        rc_dev.update()

        # Получаем позицию базы
        pos = rc_dev.telemetry.get("worldPosition") or rc_dev.telemetry.get("position")
        if not pos:
            print("Не удалось получить позицию корабля")
            return
        base_pos = _vec((pos["x"], pos["y"], pos["z"]))
        print(f"Позиция базы: {base_pos}")

        # Получаем ориентацию
        try:
            basis = get_orientation(rc_dev)
        except RuntimeError as e:
            print(f"Ошибка получения ориентации: {e}")
            return

        ship_forward = basis.forward
        ship_up = basis.up
        print(f"Вектор вперед: {ship_forward}")
        print(f"Вектор вверх: {ship_up}")

        # Генерируем сетку точеку
        grid_size = 10
        spacing = 100.0
        patrol_points = CoordinateGridGenerator.generate_grid(base_pos, ship_forward, ship_up, grid_size, spacing)
        print(f"Сгенерировано {len(patrol_points)} точек патрулирования")

        # Создаем GPS-маркеры для каждой точки
        for idx, point in enumerate(patrol_points):
            marker_name = f"Patrol_{idx:02d}"
            grid.create_gps_marker(marker_name, coordinates=point)
            print(f"Создан GPS-маркер: {marker_name} at {point}")
            time.sleep(0.1)

        print("Все точки патрулирования добавлены как GPS-маркеры.")

    except Exception as e:
        print(f"Произошла ошибка: {e}")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
