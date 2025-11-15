"""Реальный тест построения карты и поиска пути с данными из радара ore_detector."""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pyvista as pv

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.radar_navigation import RawRadarMap, PathFinder, PassabilityProfile
import os

# Добавить src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../src"))

import os


def extract_solid(radar: Dict[str, Any]) -> tuple[List[List[float]], Dict[str, Any], List[Dict[str, Any]]]:
    """Извлекает solid массив, метаданные и contacts из радара."""
    raw = radar.get("raw", {})
    solid = raw.get("solidPoints", [])
    if not isinstance(solid, list):
        solid = []

    metadata = {
        "size": raw.get("size", [100, 100, 100]),
        "cellSize": raw.get("cellSize", 1.0),
        "origin": raw.get("origin", [0.0, 0.0, 0.0]),
        "oreCellsTruncated": radar.get("oreCellsTruncated", 0),
        "rev": raw.get("rev", 0),
        "tsMs": raw.get("tsMs", 0),
    }

    contacts = radar.get("contacts", [])
    if not isinstance(contacts, list):
        contacts = []

    return solid, metadata, contacts


def cross(a: List[float], b: List[float]) -> List[float]:
    """Векторное произведение."""
    return [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]]


def apply_quaternion(q: List[float], v: List[float]) -> List[float]:
    """Применить quaternion к вектору для поворота."""
    w, x, y, z = q
    qvec = [x, y, z]
    cross1 = cross(qvec, v)
    cross2 = cross(qvec, [c + w * vi for c, vi in zip(cross1, v)])
    return [v[0] + 2 * cross2[0], v[1] + 2 * cross2[1], v[2] + 2 * cross2[2]]


def get_forward_point(grid, distance: float = 50.0) -> List[float]:
    """Вычислить точку на distance метров вперед относительно грида."""
    return get_rover_position_and_forward(grid)[0]  # Пока просто позиция, но можно добавить смещение


def get_rover_position_and_forward(grid) -> tuple[List[float], List[float]]:
    """Получить позицию и направление вперед ровера."""
    # Найти cockpit или remote_control
    cockpit_devices = grid.find_devices_by_type("cockpit")
    remote_devices = grid.find_devices_by_type("remote_control")
    device = None
    if cockpit_devices:
        device = cockpit_devices[0]
    elif remote_devices:
        device = remote_devices[0]
    else:
        raise ValueError("Не найдено устройство с позицией (cockpit или remote_control).")

    # Обновить телеметрию
    device.update()

    # Получить position и orientation
    position = device.telemetry.get("planetPosition") or device.telemetry.get("position")
    orientation = device.telemetry.get("orientation")

    if not position or not orientation:
        raise ValueError("Не удалось получить позицию или ориентацию из телеметрии устройства.")

    # Обработать position
    if isinstance(position, dict):
        position = [position["x"], position["y"], position["z"]]
    elif not isinstance(position, list):
        raise ValueError("Неверный формат позиции.")

    # Обработать orientation: взять forward vector
    if isinstance(orientation, dict) and "forward" in orientation:
        forward = [orientation["forward"]["x"], orientation["forward"]["y"], orientation["forward"]["z"]]
    else:
        raise ValueError("Неверный формат ориентации.")

    print(f"Device position: {position}")

    return position, forward


# Глобальные переменные для состояния
last_scan_state = {}
last_solid_data = None
cancel_requested = False
plotter = None

def input_thread():
    global cancel_requested
    while True:
        try:
            cmd = input("Введите 'c' для отмены сканирования: ").strip().lower()
            if cmd == 'c':
                cancel_requested = True
                print("Отмена запрошена...")
                break
        except EOFError:
            break


def process_and_visualize(solid: List[List[float]], metadata: Dict[str, Any], contacts: List[Dict[str, Any]], grid) -> None:
    """Обрабатывает solid данные, строит карту, ищет путь и визуализирует."""
    global last_solid_data, plotter
    if not solid:
        print("Нет данных solid для обработки.")
        return

    # Проверка на изменение данных
    current_data = (solid[:10], metadata["rev"])  # Первые 10 координат и rev
    if last_solid_data == current_data:
        return  # Данные не изменились
    last_solid_data = current_data

    print(f"Обработка solid: {len(solid)} точек, rev={metadata['rev']}, truncated={metadata['oreCellsTruncated']}")

    # Извлечь параметры
    size = metadata["size"]
    cell_size = metadata["cellSize"]
    origin = np.array(metadata["origin"], dtype=float)

    size_x, size_y, size_z = size

    # Преобразовать solid в локальные координаты относительно origin
    solid_local = [(x - origin[0], y - origin[1], z - origin[2]) for x, y, z in solid]

    # Создать occupancy grid: True - blocked (воздух), False - traversable (solid)
    occ = np.ones((size_x, size_y, size_z), dtype=bool)

    # Заполнить occupancy grid: solid точки - traversable
    for coord in solid_local:
        try:
            x, y, z = coord
            ix = int(np.floor(x / cell_size))
            iy = int(np.floor(y / cell_size))
            iz = int(np.floor(z / cell_size))
            if 0 <= ix < size_x and 0 <= iy < size_y and 0 <= iz < size_z:
                occ[ix, iy, iz] = False  # traversable
        except Exception as e:
            print(f"Ошибка обработки точки {coord}: {e}")

    print(f"Карта: {size_x}x{size_y}x{size_z}, origin: {origin}, cell_size: {cell_size}")
    print(f"Всего занятых вокселей: {int(occ.sum())}")

    # Создать RawRadarMap
    # Rebuild occupancy from solidPoints using RawRadarMap indexing semantics:
    # True = occupied (solid), False = free (traversable)
    try:
        arr = np.asarray(solid, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] == 3:
            rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
            idx = np.rint(rel).astype(np.int64)
            valid = (
                (idx[:, 0] >= 0)
                & (idx[:, 0] < size_x)
                & (idx[:, 1] >= 0)
                & (idx[:, 1] < size_y)
                & (idx[:, 2] >= 0)
                & (idx[:, 2] < size_z)
            )
            idx = idx[valid]
            occ = np.zeros((size_x, size_y, size_z), dtype=bool)
            if idx.size:
                occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    except Exception as e:
        print(f"Failed to rebuild occupancy from solidPoints: {e}")

    # Build walkable-surface occupancy without inventing voxels.
    # Walkable = air voxel with solid directly below; holes remain non-walkable.
    occ_solid = occ.copy()
    air = ~occ_solid
    solid_below = np.zeros_like(occ_solid, dtype=bool)
    solid_below[:, 1:, :] = occ_solid[:, 0:-1, :]
    walkable = air & solid_below
    # Replace occ with BLOCKED mask for path planning: True = blocked, False = walkable
    occ = ~walkable
    print(f"Walkable cells: {int((~occ).sum())}, blocked: {int(occ.sum())}")

    radar_map = RawRadarMap(
        occ=occ,
        origin=origin,
        cell_size=cell_size,
        size=(size_x, size_y, size_z),
        revision=metadata["rev"],
        timestamp_ms=metadata["tsMs"],
        contacts=contacts,
        _inflation_cache={},
    )

    # PathFinder с либеральным профилем для отладки
    profile = PassabilityProfile(
        robot_radius=0.0,
        max_slope_degrees=45.0,
        max_step_cells=1,
        allow_vertical_movement=False,
        allow_diagonal=True,
    )
    print(f"PassabilityProfile: robot_radius={profile.robot_radius}, max_slope_degrees={profile.max_slope_degrees}, max_step_cells={profile.max_step_cells}, allow_vertical_movement={profile.allow_vertical_movement}, allow_diagonal={profile.allow_diagonal}")
    pathfinder = PathFinder(radar_map, profile)

    # Получить позицию ровера и игрока
    try:
        position, forward = get_rover_position_and_forward(grid)
        print("Rover position:", position)
        start_world = position

        # Взять player_pos из contacts
        player_pos = None
        for contact in contacts:
            if contact.get("type") == "player" and str(contact.get("ownerId")) == grid.owner_id:
                player_pos = contact["position"]
                break

        if player_pos:
            goal_world = player_pos
            print(f"Player position: {player_pos}, Goal: {goal_world}")
        else:
            goal_world = [p + f * 100.0 for p, f in zip(position, forward)]
            print(f"No player found, Goal: {goal_world}")
    except Exception as e:
        print(f"Не удалось получить позицию ровера: {e}")
        # Fallback to random free cells
        free_indices = np.where(~occ)
        if len(free_indices[0]) < 2:
            print("Недостаточно свободных ячеек для пути")
            return
        start_world = radar_map.index_to_world_center((int(free_indices[0][0]), int(free_indices[1][0]), int(free_indices[2][0])))
        goal_world = radar_map.index_to_world_center((int(free_indices[0][-1]), int(free_indices[1][-1]), int(free_indices[2][-1])))

    # Найти ближайшую свободную ячейку к start_world и goal_world
    def find_nearest_free_index(world_pos):
        # Попытаться world_to_index
        try:
            idx = radar_map.world_to_index(world_pos)
            if 0 <= idx[0] < size_x and 0 <= idx[1] < size_y and 0 <= idx[2] < size_z and not occ[idx]:
                return idx
        except:
            pass
        # Найти ближайший свободный
        free_indices = np.where(~occ)
        if len(free_indices[0]) == 0:
            return None
        distances = []
        for i in range(len(free_indices[0])):
            idx = (free_indices[0][i], free_indices[1][i], free_indices[2][i])
            world = radar_map.index_to_world_center(idx)
            dist = np.linalg.norm(np.array(world) - np.array(world_pos))
            distances.append((dist, idx))
        distances.sort()
        return distances[0][1]

    start_idx = find_nearest_free_index(start_world)
    goal_idx = find_nearest_free_index(goal_world)

    if start_idx is None or goal_idx is None:
        print("Не удалось найти свободные ячейки для старта или цели")
        return

    print(f"Start idx: {start_idx}, Goal idx: {goal_idx}")
    print(f"Start blocked: {bool(occ[start_idx])}, Goal blocked: {bool(occ[goal_idx])}")
    print(f"Start world: {radar_map.index_to_world_center(start_idx)}, Goal world: {radar_map.index_to_world_center(goal_idx)}")

    # Найти reachable точки от start с помощью BFS
    def get_reachable_indices(start_idx, occ, size_x, size_y, size_z):
        from collections import deque
        visited = np.zeros((size_x, size_y, size_z), dtype=bool)
        queue = deque([start_idx])
        visited[start_idx] = True
        reachable = [start_idx]

        directions = [
            (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)
        ]

        while queue:
            current = queue.popleft()
            for dx, dy, dz in directions:
                nx, ny, nz = current[0] + dx, current[1] + dy, current[2] + dz
                if 0 <= nx < size_x and 0 <= ny < size_y and 0 <= nz < size_z:
                    if not occ[(nx, ny, nz)] and not visited[(nx, ny, nz)]:
                        visited[(nx, ny, nz)] = True
                        queue.append((nx, ny, nz))
                        reachable.append((nx, ny, nz))
        return reachable

    reachable_indices = get_reachable_indices(start_idx, occ, size_x, size_y, size_z)
    print(f"Reachable точек от start: {len(reachable_indices)}")
    closest_reachable_idx = None
    partial_path = []
    partial_path_points = []


    # Найти ближайшую reachable точку к goal
    if reachable_indices:
        distances = []
        for idx in reachable_indices:
            world = radar_map.index_to_world_center(idx)
            dist = np.linalg.norm(np.array(world) - np.array(goal_world))
            distances.append((dist, idx))
        distances.sort()
        closest_reachable_idx = distances[0][1]
        print(f"Ближайшая reachable к goal: {closest_reachable_idx}, dist: {distances[0][0]}")

        # Найти путь к ближайшей reachable
        print(f"Finding partial path from {start_idx} to {closest_reachable_idx}")
        partial_path = pathfinder.find_path_indices(start_idx, closest_reachable_idx)
        if partial_path:
            partial_path_points = [radar_map.index_to_world_center(idx) for idx in partial_path]
            print(f"Partial путь из {len(partial_path)} индексов")
        else:
            partial_path_points = []
            print(f"Partial путь не найден, хотя {closest_reachable_idx} reachable от {start_idx}")
    else:
        closest_reachable_idx = None
        partial_path = []
        partial_path_points = []

    fallback_path_used = False
    fallback_goal_world = None

    print(f"Finding full path from {start_idx} to {goal_idx}")
    path = pathfinder.find_path_indices(start_idx, goal_idx)

    path_points: List[Any] = []
    actual_goal_world = goal_world

    if path:
        print(f"Found path with {len(path)} nodes")
        print(f"Path indices: {path}")
        blocked_in_path = [idx for idx in path if occ[idx]]
        if blocked_in_path:
            print(f"Blocked indices in path: {blocked_in_path}")
        path_points = [radar_map.index_to_world_center(idx) for idx in path]
        path_points = [(x, y, z) for x, y, z in path_points]
        actual_goal_world = path_points[-1]
        print(f"Path starts at: {path_points[0]}")
    else:
        print(f"Goal {goal_idx} unreachable from {start_idx}")
        if partial_path_points:
            print("Using fallback path to the closest reachable voxel.")
            path_points = partial_path_points
            fallback_path_used = True
            if closest_reachable_idx is not None:
                fallback_goal_world = radar_map.index_to_world_center(closest_reachable_idx)
                actual_goal_world = fallback_goal_world
        else:
            path_points = []


    # Визуализация с pyvista
    print("Создаем/обновляем визуализацию...")

    if plotter is None:
        plotter = pv.Plotter()

    # Очистить предыдущую визуализацию
    plotter.clear()

    # Визуализировать воксельную сетку только для traversable вокселей
    # Traversable voxel grid drawing disabled (per earlier request).
    grid = pv.ImageData()
    grid.dimensions = np.array([size_x + 1, size_y + 1, size_z + 1])
    grid.spacing = (cell_size, cell_size, cell_size)
    grid.origin = origin
    # VTK expects Fortran-order flattening for cell data layout
    grid.cell_data["traversable"] = (~occ).ravel(order='F')
    # Показать только traversable воксели
    traversable_grid = grid.threshold(0.5, scalars="traversable")
    plotter.add_mesh(traversable_grid, style='wireframe', color='blue', label="Traversable Voxels")
    # plotter.add_mesh(traversable_grid, color='blue', label="Traversable Voxels")


    # Добавить start и goal точки
    plotter.add_points(
        np.array([start_world]),
        color="green",
        render_points_as_spheres=True,
        point_size=10,
        label="Start",
    )
    if fallback_path_used and fallback_goal_world is not None:
        plotter.add_points(
            np.array([goal_world]),
            color="orange",
            render_points_as_spheres=True,
            point_size=10,
            label="Original Goal",
        )
        plotter.add_points(
            np.array([actual_goal_world]),
            color="red",
            render_points_as_spheres=True,
            point_size=10,
            label="Fallback Goal",
        )
    else:
        plotter.add_points(
            np.array([goal_world]),
            color="red",
            render_points_as_spheres=True,
            point_size=10,
            label="Goal",
        )

    # Добавить желтые точки для проверки
    # test_points = np.array([[1036536, 184299, 1660050], [1036536 + 100, 184299 + 100, 1660050 + 10]])
    test_points = np.array([1036773.708, 184439.29,1660005.359])

    plotter.add_points(
        test_points,
        color="yellow",
        render_points_as_spheres=True,
        point_size=15,
        label="Test Points",
    )

    if partial_path_points and not fallback_path_used:
        partial_line = pv.lines_from_points(partial_path_points)
        partial_tube = partial_line.tube(radius=0.5)
        plotter.add_mesh(partial_tube, color="yellow", label="Partial Path to Closest Reachable")
        print(f"Added partial path tube with {len(partial_path_points)} points")

    if path_points:
        line = pv.lines_from_points(path_points)
        tube = line.tube(radius=0.5)
        plotter.add_mesh(tube, color="red", label="Path")
        plotter.add_points(np.array(path_points), color="red", point_size=10, label="Path Points")
        print(f"Added path tube and points with {len(path_points)} points")

    # Добавить точки устройств
    device_points = []
    for contact in contacts:
        if contact.get("type") == "grid":
            print(contact)
            pos = contact.get("position")
            if pos:
                device_points.append(pos)

    if device_points:
        device_cloud = pv.PolyData(device_points)
        plotter.add_mesh(device_cloud, color='red', label="Devices")

    plotter.add_text(f'Real Radar Map and Path (rev={metadata["rev"]}, points={len(solid)})', position='upper_left')
    plotter.show(title="Real Radar Map and Path")


def main() -> None:
    global cancel_requested, plotter
    # Запустить поток для ввода команд
    input_t = threading.Thread(target=input_thread, daemon=True)
    input_t.start()

    grid = prepare_grid()
    try:
        # Найти ore_detector
        detectors = grid.find_devices_by_type(OreDetectorDevice)
        if not detectors:
            print("На гриде не найдено ни одного детектора руды (ore_detector).")
            return
        device: OreDetectorDevice = detectors[0]
        print(f"Найден радар device_id={device.device_id} name={device.name!r}")
        print(f"Ключ телеметрии: {device.telemetry_key}")

        # Подписка на телеметрию
        def on_telemetry_update(dev: OreDetectorDevice, telemetry: Dict[str, Any], source_event: str) -> None:
            global last_scan_state
            if not isinstance(telemetry, dict):
                return

            # Сохранить состояние scan
            scan_state = telemetry.get("scan", {})
            if isinstance(scan_state, dict):
                last_scan_state = scan_state

            radar = telemetry.get("radar")
            if not isinstance(radar, dict):
                return

            solid, metadata, contacts = extract_solid(radar)
            if solid:
                process_and_visualize(solid, metadata, contacts, grid)

        device.on("telemetry", on_telemetry_update)

        # Отправить сканирование для solid
        print("Отправка команды scan для solid...")
        seq = device.scan(
            include_players=True,
            include_grids=True,
            include_voxels=True,
            fullSolidScan=True,
            voxel_step=1,
            cell_size=1,  # Размер вокселя 5 метров
            fast_scan=False,
            boundingBoxX=500,
            boundingBoxY=500,
            boundingBoxZ=40,
            radius=50,
        )
        print(f"Scan отправлен, seq={seq}. Ожидание телеметрии... (Ctrl+C для выхода)")

        # Цикл отслеживания прогресса и ожидания
        last_progress = -1
        try:
            while True:
                # Проверка на отмену
                if cancel_requested:
                    print("Отправка команды отмены сканирования...")
                    device.cancel_scan()
                    cancel_requested = False  # Сбросить флаг

                # Печатать прогресс сканирования
                scan = last_scan_state
                if scan:
                    in_progress = scan.get("inProgress", False)
                    progress = scan.get("progressPercent", 0)
                    processed = scan.get("processedTiles", 0)
                    total = scan.get("totalTiles", 0)
                    elapsed = scan.get("elapsedSeconds", 0)

                    if in_progress and progress != last_progress:
                        print(f"[scan progress] {progress:.1f}% ({processed}/{total} tiles, {elapsed:.1f}s)")
                        last_progress = progress
                    elif not in_progress and last_progress != -1:
                        print(f"[scan] Завершено: {progress:.1f}% ({processed}/{total} tiles, {elapsed:.1f}s)")
                        last_progress = -1

                time.sleep(5)  # Пауза 5 сек
                device.update()

        except KeyboardInterrupt:
            print("Выход...")
        finally:
            device.off("telemetry", on_telemetry_update)
    finally:
        if plotter:
            plotter.close()
        close(grid)


if __name__ == "__main__":
    main()
