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
    }

    contacts = radar.get("contacts", [])
    if not isinstance(contacts, list):
        contacts = []

    return solid, metadata, contacts


# Глобальные переменные для состояния
last_scan_state = {}
last_solid_data = None
cancel_requested = False

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

def visualize_solid(solid: List[List[float]], metadata: Dict[str, Any], contacts: List[Dict[str, Any]]) -> None:
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
    device_points = []
    for contact in contacts:
        if contact.get("type") == "grid":
            pos = contact.get("position")
            print(contact)
            if pos:
                device_points.append(pos)

    device_cloud = None
    if device_points:
        device_cloud = pv.PolyData(device_points)

    # Использовать глобальный plotter для обновления
    global plotter
    if 'plotter' not in globals():
        plotter = pv.Plotter(off_screen=False)
        plotter.add_mesh(cloud, color='blue')
        if device_cloud:
            plotter.add_mesh(device_cloud, color='red')
        plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
        plotter.show(auto_close=False, interactive=True)
    else:
        # Обновить поверхность
        plotter.clear()
        plotter.add_mesh(cloud, color='blue')
        if device_cloud:
            plotter.add_mesh(device_cloud, color='red')
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
    global cancel_requested
    # Запустить поток для ввода команд
    input_t = threading.Thread(target=input_thread, daemon=True)
    input_t.start()

    grid = prepare_grid()
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
            print(f"Получен solid: {len(solid)} точек, rev={metadata['rev']}, truncated={metadata['oreCellsTruncated']}")

            if solid:
                visualize_solid(solid, metadata, contacts)

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
        seq = device.scan(
            # include_players=False,
            include_grids=True,
            budget_ms_per_tick=100,

            # полный скан
            include_voxels=True,
            fullSolidScan = True,
            voxel_step=1,
            cell_size=10,
            fast_scan=False,

            # Быстрый скан
            # include_voxels=True,
            # fast_scan=True,
            # gridStep=5,

            boundingBoxX=500,
            boundingBoxY=500,
            boundingBoxZ=30,

            radius = 300,

            # centerX=centerX,
            # centerY=centerY,
            # centerZ=centerZ
            # fastScanTileEdgeMax=256



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


