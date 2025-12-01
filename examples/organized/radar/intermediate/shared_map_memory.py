"""Пример совместной карты для нескольких гридов с раздельным хранением.

Сценарий выполняет скан радара, складывает воксели, руды и посещенные точки
в чанки Redis (``{memory_prefix}:voxels:<chunk>``, ``{memory_prefix}:ores:<chunk>``
и т.д.) и строит обратный путь на основе известных точек. Данные читаются и
записываются через :class:`SharedMapController`, поэтому ими могут
пользоваться другие гриды или скрипты.
"""

from __future__ import annotations

import os
from typing import Tuple

from dotenv import load_dotenv

from secontrol.common import prepare_grid
from secontrol.controllers import RadarController, SharedMapController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

load_dotenv()


Point3D = Tuple[float, float, float]


def _pick_device(devices, expected_cls):
    if not devices:
        raise RuntimeError(f"Не найдено устройство {expected_cls.__name__}")
    return devices[0]


def main():

    grid = prepare_grid("taburet2")

    radar: OreDetectorDevice = _pick_device(grid.find_devices_by_type(OreDetectorDevice), OreDetectorDevice)
    remote: RemoteControlDevice = _pick_device(grid.find_devices_by_type(RemoteControlDevice), RemoteControlDevice)

    shared_map = SharedMapController(owner_id=grid.owner_id, chunk_size=80.0)
    shared_map.load()
    print(f"Работаем с префиксом карты: {shared_map.memory_prefix}")

    radar_controller = RadarController(radar, radius=80.0)
    solid, metadata, contacts, ore_cells = shared_map.ingest_radar_scan(radar_controller)
    print(f"Найдено вокселей: {len(solid or [])}, контактов: {len(contacts or [])}, руд: {len(ore_cells or [])}")

    current_pos = shared_map.add_remote_position(remote)
    print(f"Текущая позиция RC: {current_pos}")

    return_path = shared_map.build_and_store_return_path(remote)
    print(f"Построенный путь возврата ({len(return_path)} точек):")
    for point in return_path:
        print(f"  {point}")

    print("\nИзвестные руды:")
    for ore in shared_map.get_known_ores():
        print(f"  {ore.material} @ {ore.position} (content={ore.content})")

    # Загружаем только нужный радиус вокруг текущей позиции
    region = shared_map.load_region(current_pos or (0.0, 0.0, 0.0), radius=200.0)
    print(
        "\nЧанковый снимок вокруг корабля: "
        f"voxels={len(region.voxels)}, visited={len(region.visited)}, ores={len(region.ores)}"
    )

    index_snapshot = shared_map.client.get_json(shared_map.index_key)
    print("\nИндекс карты:")
    print(index_snapshot)
    if index_snapshot.get("voxels"):
        sample_chunk = index_snapshot["voxels"][0]
        sample_points = shared_map.client.get_json(shared_map._chunk_key("voxels", sample_chunk))
        print(f"Пример хранения точек в чанке {sample_chunk}: {sample_points[:5]} ...")


if __name__ == "__main__":
    main()
