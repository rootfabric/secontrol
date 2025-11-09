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

def linear_to_3d(idx: int, sx: int, sy: int, sz: int) -> tuple[int, int, int]:
    """Преобразует линейный индекс в 3D координаты."""
    x = idx % sx
    y = (idx // sx) % sy
    z = idx // (sx * sy)
    return x, y, z


def extract_solid(radar: Dict[str, Any]) -> tuple[List[int], Dict[str, Any]]:
    """Извлекает solid массив и метаданные из радара."""
    raw = radar.get("raw", {})
    solid = raw.get("solid", [])
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

    return solid, metadata


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

def visualize_solid(solid: List[int], metadata: Dict[str, Any]) -> None:
    """Визуализирует solid как 3D облако точек с pyvista."""
    global last_solid_data
    if not solid:
        print("Нет данных solid для визуализации.")
        return

    # Проверка на изменение данных
    current_data = (solid[:10], metadata["rev"])  # Первые 10 индексов и rev
    if last_solid_data == current_data:
        return  # Данные не изменились
    last_solid_data = current_data

    size = metadata["size"]
    cellSize = metadata["cellSize"]
    origin = metadata["origin"]
    sx, sy, sz = size

    points = []
    for idx in solid:
        x, y, z = linear_to_3d(idx, sx, sy, sz)
        wx = origin[0] + x * cellSize
        wy = origin[1] + y * cellSize
        wz = origin[2] + z * cellSize
        points.append((wx, wy, wz))

    # Создать PolyData из точек
    cloud = pv.PolyData(points)

    # Использовать глобальный plotter для обновления
    global plotter
    if 'plotter' not in globals():
        plotter = pv.Plotter(off_screen=False)
        plotter.add_mesh(cloud, color='blue', point_size=2, render_points_as_spheres=True)
        plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
        plotter.show(auto_close=False, interactive=True)
    else:
        # Обновить точки
        plotter.clear()
        plotter.add_mesh(cloud, color='blue', point_size=2, render_points_as_spheres=True)
        plotter.add_text(f'Solid Visualization (rev={metadata["rev"]}, points={len(points)})', position='upper_left')
        plotter.render()


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

            solid, metadata = extract_solid(radar)
            print(f"Получен solid: {len(solid)} точек, rev={metadata['rev']}, truncated={metadata['oreCellsTruncated']}")

            if solid:
                visualize_solid(solid, metadata)

        device.on("telemetry", on_telemetry_update)

        # Отправить первое сканирование для solid
        print("Отправка команды scan для solid...")
        seq = device.scan(
            include_players=False,
            include_grids=False,
            include_voxels=True,

            # fullSolidScan=True,
            fast_scan=True,
            voxel_scan_hz=0.2,
            budget_ms_per_tick=50,
            fastScanBudgetMs=20,

            voxel_step=1,
            cell_size = 1,

            gridStep=20,
            radius = 50,
            fastScanTileEdgeMax=256



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
