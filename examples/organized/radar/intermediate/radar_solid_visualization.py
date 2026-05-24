"""Визуализация solid из радара детектора руды с pyvista."""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import pyvista as pv

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice

# Функция linear_to_3d больше не нужна, поскольку solidPoints теперь абсолютные координаты


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

    # Вычислить центр
    center = [p + f * distance for p, f in zip(position, forward)]
    return center


def extract_solid(radar: Dict[str, Any]) -> tuple[List[List[float]], Dict[str, Any], List[Dict[str, Any]]]:
    """Извлекает solid массив, метаданные и contacts из радара."""
    raw = radar.get("raw", {})
    # solid = raw.get("solid", [])
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
        "radius": radar.get("radius"),
        "policy": radar.get("policy", {}),
    }

    contacts = radar.get("contacts", [])
    if not isinstance(contacts, list):
        contacts = []

    return solid, metadata, contacts


# Глобальные переменные для состояния
last_scan_state = {}
last_solid_data = None
cancel_requested = False
scan_started_at: Optional[float] = None

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

def visualize_solid(
    solid: List[List[float]],
    metadata: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    scan_duration: Optional[float] = None,
) -> None:
    """Визуализирует solid как 3D облако точек с pyvista."""
    global last_solid_data
    if not solid:
        print("Нет данных solid для визуализации.")
        return

    # Проверка на изменение данных
    current_data = (solid[:10], metadata["rev"])  # Первые 10 координат и rev
    if last_solid_data == current_data:
        return  # Данные не изменились
    last_solid_data = current_data

    points = []
    for coord in solid:
        try:
            x, y, z = coord
            points.append((x, y, z))
        except Exception as e:
            print(e)

    # print(points)
    # Создать PolyData из точек и voxelize
    cloud = pv.PolyData(points)
    # voxels = pv.voxelize(cloud, density=cellSize)
    # print(voxels)

    # Добавить точки устройств
    grid_points = []
    player_points = []
    for contact in contacts:
        contact_type = contact.get("type")
        pos = contact.get("position")
        if not pos:
            continue

        if contact_type == "grid":
            print(contact)
            grid_points.append(pos)
        elif contact_type == "player":
            print(contact)
            player_points.append(pos)

    grid_cloud = pv.PolyData(grid_points) if grid_points else None
    player_cloud = pv.PolyData(player_points) if player_points else None
    print(f"Contacts: {len(contacts)}, grids: {len(grid_points)}, players: {len(player_points)}")
    if scan_duration is not None:
        print(f"[scan] Total scan time before plot: {scan_duration:.2f}s")

    # Использовать глобальный plotter для обновления
    global plotter
    if 'plotter' not in globals():
        plotter = pv.Plotter(off_screen=False)
        plotter.add_mesh(cloud, color='blue')
        if grid_cloud:
            plotter.add_mesh(grid_cloud, color='red', point_size=20, render_points_as_spheres=True, label='Grids')
        if player_cloud:
            plotter.add_mesh(player_cloud, color='green', point_size=14, render_points_as_spheres=True, label='Players')
        plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
        plotter.show(auto_close=False, interactive=True)
    else:
        # Обновить поверхность
        plotter.clear()
        plotter.add_mesh(cloud, color='blue')
        if grid_cloud:
            plotter.add_mesh(grid_cloud, color='red', point_size=20, render_points_as_spheres=True, label='Grids')
        if player_cloud:
            plotter.add_mesh(player_cloud, color='green', point_size=14, render_points_as_spheres=True, label='Players')
        plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
        plotter.render()

    # global plotter
    # if 'plotter' not in globals():
    #     plotter = pv.Plotter(off_screen=False)
    #     plotter.add_mesh(voxels, color='blue')
    #     plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
    #     plotter.show(auto_close=False, interactive=True)
    # else:
    #     # Обновить воксели
    #     plotter.clear()
    #     plotter.add_mesh(voxels, color='blue')
    #     plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
    #     plotter.render()
    #

def main() -> None:
    global cancel_requested, scan_started_at
    # Запустить поток для ввода команд
    input_t = threading.Thread(target=input_thread, daemon=True)
    input_t.start()

    grid = prepare_grid("skynet-baza1")
    try:
        # Найти ore_detector
        # detectors = grid.find_devices_by_type("ore_detector")
        detectors = grid.find_devices_by_type(OreDetectorDevice)
        if not detectors:
            print("На гриде не найдено ни одного детектора руды (ore_detector).")
            return
        device:OreDetectorDevice = detectors[0]
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
            print(
                f"Scan meta: radius={metadata.get('radius')}, "
                f"cellSize={metadata.get('cellSize')}, size={metadata.get('size')}, "
                f"policy={metadata.get('policy')}"
            )
            print(f"Получен solid: {len(solid)} точек, rev={metadata['rev']}, truncated={metadata['oreCellsTruncated']}")

            if solid:
                xs = [float(p[0]) for p in solid if isinstance(p, list) and len(p) >= 3]
                ys = [float(p[1]) for p in solid if isinstance(p, list) and len(p) >= 3]
                zs = [float(p[2]) for p in solid if isinstance(p, list) and len(p) >= 3]
                if xs and ys and zs:
                    print(
                        f"Solid extents: "
                        f"x={max(xs)-min(xs):.1f}m, y={max(ys)-min(ys):.1f}m, z={max(zs)-min(zs):.1f}m"
                    )
                scan_duration = time.time() - scan_started_at if scan_started_at is not None else None
                visualize_solid(solid, metadata, contacts, scan_duration)

        device.on("telemetry", on_telemetry_update)

        # device.cancel_scan()

        # Отправить первое сканирование для solid
        print("Отправка команды scan для solid...")
        # device.scan()
        # device.wait_for_new_radar()
        #
        # center = get_forward_point(grid, 40.0)
        # centerX, centerY, centerZ = center
        # print(f"Центр сканирования: {center}")
        
        scan_radius = 5000
        
        seq = device.scan(
            include_players=True,
            include_grids=True,
            # budget_ms_per_tick=100,

            # полный скан
            include_voxels=True,
            # include_voxels=False,
            # fullSolidScan = True,
            voxel_step=1,

            # fast_scan=False,
            # fast_scan=True,
            
            # gridStep=200,      # 25-50 для грубой карты
            # cell_size=200,

            # Быстрый скан
            # include_voxels=True,
            
            # gridStep=10,

            boundingBoxX=100,
            boundingBoxY=100,
            boundingBoxZ=5000,

            radius=scan_radius,
            fastScanMaxRadius=scan_radius,

            # centerX=centerX,
            # centerY=centerY,
            # centerZ=centerZ
            # fastScanTileEdgeMax=256



        )
        print(f"Scan отправлен, seq={seq}. Ожидание телеметрии... (Ctrl+C для выхода)")


        # Цикл отслеживания прогресса и ожидания
        scan_started_at = time.time()
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

                time.sleep(5)  # Пауза 1 сек
                device.update()

        except KeyboardInterrupt:
            print("Выход...")
        finally:
            device.off("telemetry", on_telemetry_update)
    finally:
        close(grid)


if __name__ == "__main__":
    main()


