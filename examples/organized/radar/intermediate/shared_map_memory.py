"""Пример совместной карты для нескольких гридов.

Сценарий выполняет скан радара, складывает воксели и посещенные точки
в ключ ``se:{owner_id}:memory`` и строит обратный путь на основе известных
точек. Данные читаются и записываются через :class:`SharedMapController`,
поэтому ими могут пользоваться другие гриды или скрипты.
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
    grid_name = os.getenv("SE_GRID_NAME") or os.getenv("SE_GRID_ID") or ""  # пустая строка возьмет первый грид
    grid = prepare_grid(grid_name)

    radar: OreDetectorDevice = _pick_device(grid.find_devices_by_type(OreDetectorDevice), OreDetectorDevice)
    remote: RemoteControlDevice = _pick_device(grid.find_devices_by_type(RemoteControlDevice), RemoteControlDevice)

    shared_map = SharedMapController(owner_id=grid.owner_id)
    shared_map.load()
    print(f"Работаем с ключом карты: {shared_map.memory_key}")

    radar_controller = RadarController(radar, radius=80.0)
    solid, metadata, contacts, ore_cells = shared_map.ingest_radar_scan(radar_controller)
    print(f"Найдено вокселей: {len(solid or [])}, контактов: {len(contacts or [])}")

    current_pos = shared_map.add_remote_position(remote)
    print(f"Текущая позиция RC: {current_pos}")

    return_path = shared_map.build_and_store_return_path(remote)
    print(f"Построенный путь возврата ({len(return_path)} точек):")
    for point in return_path:
        print(f"  {point}")

    snapshot = shared_map.client.get_json(shared_map.memory_key)
    print("\nСодержимое Redis ключа:")
    print(snapshot)


if __name__ == "__main__":
    main()
