"""Mock code для проверки построения карты и построителя путей с данными из радара."""

from __future__ import annotations

import numpy as np
import pyvista as pv
from typing import List, Tuple
import sys
import os

# Добавить src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../src"))

from secontrol.tools.radar_navigation import RawRadarMap, PathFinder, PassabilityProfile


# Данные точек из логов radar_solid_visualization.py (подмножество для теста)
points: List[Tuple[float, float, float]] = [
    (1063456.4464285336, 158113.40619050368, 1675390.21148558),
    (1063444.4464285336, 158113.40619050368, 1675390.21148558),
    (1063447.4464285336, 158113.40619050368, 1675390.21148558),
    (1063435.4464285336, 158113.40619050368, 1675390.21148558),
    (1063426.4464285336, 158113.40619050368, 1675390.21148558),
    (1063444.4464285336, 158113.40619050368, 1675420.21148558),
    (1063468.4464285336, 158125.40619050368, 1675357.21148558),
    (1063477.4464285336, 158104.40619050368, 1675345.21148558),
    (1063468.4464285336, 158104.40619050368, 1675345.21148558),
    (1063435.4464285336, 158125.40619050368, 1675357.21148558),
    (1063426.4464285336, 158125.40619050368, 1675357.21148558),
    (1063435.4464285336, 158104.40619050368, 1675345.21148558),
    (1063456.4464285336, 158137.40619050368, 1675366.21148558),
    (1063456.4464285336, 158125.40619050368, 1675357.21148558),
    (1063426.4464285336, 158125.40619050368, 1675387.21148558),
    (1063447.4464285336, 158125.40619050368, 1675357.21148558),
    (1063444.4464285336, 158137.40619050368, 1675366.21148558),
    (1063447.4464285336, 158137.40619050368, 1675366.21148558),
    (1063444.4464285336, 158146.40619050368, 1675354.21148558),
    (1063444.4464285336, 158125.40619050368, 1675357.21148558),
    (1063456.4464285336, 158104.40619050368, 1675345.21148558),
    (1063435.4464285336, 158125.40619050368, 1675387.21148558),
    (1063447.4464285336, 158146.40619050368, 1675354.21148558),
    (1063444.4464285336, 158125.40619050368, 1675387.21148558),
    (1063435.4464285336, 158137.40619050368, 1675366.21148558),
    (1063444.4464285336, 158104.40619050368, 1675345.21148558),
    (1063447.4464285336, 158104.40619050368, 1675345.21148558),
    (1063447.4464285336, 158125.40619050368, 1675387.21148558),
    (1063468.4464285336, 158083.40619050368, 1675387.21148558),
    (1063456.4464285336, 158125.40619050368, 1675387.21148558),
    (1063426.4464285336, 158137.40619050368, 1675366.21148558),
    (1063477.4464285336, 158083.40619050368, 1675387.21148558),
    (1063447.4464285336, 158083.40619050368, 1675387.21148558),
    (1063444.4464285336, 158083.40619050368, 1675387.21148558),
    (1063435.4464285336, 158146.40619050368, 1675354.21148558),
    (1063456.4464285336, 158083.40619050368, 1675378.21148558),
    (1063447.4464285336, 158083.40619050368, 1675378.21148558),
    (1063426.4464285336, 158125.40619050368, 1675390.21148558),
    (1063456.4464285336, 158083.40619050368, 1675387.21148558),
    (1063444.4464285336, 158083.40619050368, 1675378.21148558),
    (1063435.4464285336, 158125.40619050368, 1675390.21148558),
    (1063477.4464285336, 158083.40619050368, 1675378.21148558),
    (1063468.4464285336, 158113.40619050368, 1675378.21148558),
    (1063444.4464285336, 158125.40619050368, 1675390.21148558),
    (1063447.4464285336, 158125.40619050368, 1675390.21148558),
    (1063435.4464285336, 158125.40619050368, 1675399.21148558),
    (1063456.4464285336, 158125.40619050368, 1675390.21148558),
    (1063468.4464285336, 158083.40619050368, 1675378.21148558),
    (1063426.4464285336, 158125.40619050368, 1675399.21148558),
    (1063447.4464285336, 158113.40619050368, 1675408.21148558),
    (1063444.4464285336, 158113.40619050368, 1675408.21148558),
    (1063447.4464285336, 158125.40619050368, 1675399.21148558),
    (1063444.4464285336, 158125.40619050368, 1675399.21148558),
]


def main() -> None:
    print("Загружаем точки...")

    # Вычислить min и max для origin и size
    x_coords = [p[0] for p in points]
    y_coords = [p[1] for p in points]
    z_coords = [p[2] for p in points]
    min_x = min(x_coords)
    min_y = min(y_coords)
    min_z = min(z_coords)
    max_x = max(x_coords)
    max_y = max(y_coords)
    max_z = max(z_coords)

    cell_size = 3.0

    # origin c половинным смещением, чтобы центры вокселей совпадали с исходными точками
    origin = np.array(
        [
            min_x - 0.5 * cell_size,
            min_y - 0.5 * cell_size,
            min_z - 0.5 * cell_size,
        ],
        dtype=float,
    )

    size_x = int(np.ceil((max_x - origin[0]) / cell_size)) + 1
    size_y = int(np.ceil((max_y - origin[1]) / cell_size)) + 1
    size_z = int(np.ceil((max_z - origin[2]) / cell_size)) + 1

    occ = np.zeros((size_x, size_y, size_z), dtype=bool)

    print(f"Карта: {size_x}x{size_y}x{size_z}, origin: {origin}")

    # Заполнить occupancy grid: точки считаем solid-вокселями
    for x, y, z in points:
        ix = int(np.floor((x - origin[0]) / cell_size))
        iy = int(np.floor((y - origin[1]) / cell_size))
        iz = int(np.floor((z - origin[2]) / cell_size))
        if 0 <= ix < size_x and 0 <= iy < size_y and 0 <= iz < size_z:
            occ[ix, iy, iz] = True

    print(f"Всего занятых вокселей: {int(occ.sum())}")

    # Создать RawRadarMap
    radar_map = RawRadarMap(
        occ=occ,
        origin=origin,
        cell_size=cell_size,
        size=(size_x, size_y, size_z),
        revision=0,
        timestamp_ms=0,
        contacts=(),
        _inflation_cache={},
    )

    # PathFinder с максимально либеральным профилем
    profile = PassabilityProfile(
        robot_radius=0.0,
        max_slope_degrees=999.0,
        max_step_cells=10,
        allow_vertical_movement=True,
        allow_diagonal=True,
    )
    pathfinder = PathFinder(radar_map, profile)

    # Выбираем СВОБОДНЫЕ ячейки как старт и цель
    free_indices = np.where(~occ)
    if len(free_indices[0]) < 2:
        print("Недостаточно свободных ячеек для пути")
        return

    start_idx = (
        int(free_indices[0][0]),
        int(free_indices[1][0]),
        int(free_indices[2][0]),
    )
    goal_idx = (
        int(free_indices[0][-1]),
        int(free_indices[1][-1]),
        int(free_indices[2][-1]),
    )

    print(f"Start idx: {start_idx}, Goal idx: {goal_idx}")
    print(f"Start blocked: {bool(occ[start_idx])}, Goal blocked: {bool(occ[goal_idx])}")

    # Получить world coords для start и goal
    start_world = radar_map.index_to_world_center(start_idx)
    goal_world = radar_map.index_to_world_center(goal_idx)
    print(f"Start world: {start_world}, Goal world: {goal_world}")

    path = pathfinder.find_path_indices(start_idx, goal_idx)

    if path:
        print(f"Найден путь из {len(path)} индексов")
        path_points = [radar_map.index_to_world_center(idx) for idx in path]
        print(f"Первая точка пути: {path_points[0]}")
    else:
        print("Путь не найден")
        path_points = []

    # Визуализация с pyvista
    print("Создаем визуализацию...")
    plotter = pv.Plotter()

    if occ.any():
        occupied_pos = []
        indices = np.where(occ)
        for i in range(len(indices[0])):
            ix, iy, iz = int(indices[0][i]), int(indices[1][i]), int(indices[2][i])
            center = radar_map.index_to_world_center((ix, iy, iz))
            occupied_pos.append(center)

        if occupied_pos:
            occupied_cloud = pv.PolyData(occupied_pos)
            plotter.add_points(
                occupied_cloud,
                color="blue",
                render_points_as_spheres=True,
                point_size=3,
                label="Solid voxels",
            )

    # Добавить start и goal точки
    plotter.add_points(
        np.array([start_world]),
        color="green",
        render_points_as_spheres=True,
        point_size=10,
        label="Start",
    )
    plotter.add_points(
        np.array([goal_world]),
        color="red",
        render_points_as_spheres=True,
        point_size=10,
        label="Goal",
    )

    if path_points:
        line = pv.lines_from_points(path_points)
        plotter.add_mesh(line, color="cyan", label="Path")

    plotter.add_legend()
    plotter.show(title="Mock Radar Map and Path")


if __name__ == "__main__":
    main()
