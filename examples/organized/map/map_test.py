#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import Iterable, List

from secontrol.controllers.shared_map_controller import SharedMapController
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


def _init_grid_and_devices(grid_name: str) -> tuple[SharedMapController, RadarController, RemoteControlDevice]:
    """Инициализация грида, устройств и контроллера карты."""

    grid = prepare_grid(grid_name)

    ore_detectors = grid.find_devices_by_type(OreDetectorDevice)
    remotes = grid.find_devices_by_type(RemoteControlDevice)

    if not ore_detectors:
        raise RuntimeError("Не найден ни один OreDetector на гриде")
    if not remotes:
        raise RuntimeError("Не найден ни один RemoteControl на гриде")

    ore_detector = ore_detectors[0]
    remote = remotes[0]

    # Здесь радиус радара можно менять для проверки
    radar_radius = 100.0
    radar_ctrl = RadarController(ore_detector, radius=radar_radius)

    # Общая карта привязана к owner_id грида
    map_ctrl = SharedMapController(owner_id=grid.owner_id)

    return map_ctrl, radar_ctrl, remote


def run_single_scan(
    map_ctrl: SharedMapController,
    radar_ctrl: RadarController,
) -> None:
    """Выполнить один скан и сохранить данные в карту."""

    print("=== Шаг 1: выполняю один скан радара и сохраняю в карту ===")
    solid, metadata, contacts, ore_cells = map_ctrl.ingest_radar_scan(
        radar_ctrl,
        persist_metadata=True,
        save=True,
    )

    print(
        f"[scan] Получено от радара: "
        f"{len(solid or [])} вокселей, "
        f"{len(ore_cells or [])} ячеек руды, "
        f"контактов: {len(contacts or []) if contacts else 0}"
    )

    data_all = map_ctrl.load()
    print(
        f"[map] В карте после скана: "
        f"{len(data_all.voxels)} вокселей, "
        f"{len(data_all.ores)} руд, "
        f"{len(data_all.visited)} посещённых точек"
    )


def debug_load_region_for_radii(
    map_ctrl: SharedMapController,
    remote: RemoteControlDevice,
    radii: Iterable[float],
) -> None:
    """Проверка: сколько данных возвращает load_region при разных радиусах."""

    print("\n=== Шаг 2: проверка load_region с разными радиусами ===")

    remote.update()
    center = get_world_position(remote)
    if not center:
        raise RuntimeError("Не удалось получить позицию RemoteControl для центра области")

    cx, cy, cz = center
    print(f"Центр области: ({cx:.2f}, {cy:.2f}, {cz:.2f})")

    # Для справки: полная карта
    data_all = map_ctrl.load()
    total_voxels = len(data_all.voxels)
    total_ores = len(data_all.ores)
    total_visited = len(data_all.visited)
    print(
        f"[total] Вся карта: "
        f"{total_voxels} voxels, {total_ores} ores, {total_visited} visited"
    )

    last_voxels = 0
    last_ores = 0
    last_visited = 0

    for radius in radii:
        data_region = map_ctrl.load_region(center=center, radius=radius)
        voxels_count = len(data_region.voxels)
        ores_count = len(data_region.ores)
        visited_count = len(data_region.visited)

        print(
            f"[radius {radius:6.1f} м] "
            f"voxels={voxels_count:6d}, ores={ores_count:6d}, visited={visited_count:6d}"
        )

        if voxels_count < last_voxels:
            print(
                f"  !! ВНИМАНИЕ: число вокселей уменьшилось "
                f"({last_voxels} -> {voxels_count}) при увеличении радиуса."
            )
        if ores_count < last_ores:
            print(
                f"  !! ВНИМАНИЕ: число руд уменьшилось "
                f"({last_ores} -> {ores_count}) при увеличении радиуса."
            )
        if visited_count < last_visited:
            print(
                f"  !! ВНИМАНИЕ: число visited уменьшилось "
                f"({last_visited} -> {visited_count}) при увеличении радиуса."
            )

        last_voxels = voxels_count
        last_ores = ores_count
        last_visited = visited_count


def main() -> None:
    if len(sys.argv) >= 2:
        grid_name = sys.argv[1]
    else:
        # Можно изменить на свой грид, если не хотите передавать параметром
        grid_name = "taburet"

    print(f"Использую грид: {grid_name!r}")

    map_ctrl, radar_ctrl, remote = _init_grid_and_devices(grid_name)

    # 1) Один скан и сохранение в карту
    run_single_scan(map_ctrl, radar_ctrl)

    # 2) Проверка load_region для разных радиусов
    test_radii: List[float] = [50.0, 100.0, 200.0, 400.0, 800.0]
    debug_load_region_for_radii(map_ctrl, remote, test_radii)

    # 3) Для справки размер в Redis
    redis_size = map_ctrl.get_redis_memory_usage()
    print(f"\nПримерный размер карты в Redis: {redis_size} байт ({redis_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
