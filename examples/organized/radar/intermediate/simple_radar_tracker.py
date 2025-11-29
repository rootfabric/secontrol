"""Простой трекер радара: выводит координаты гридов и игрока, отслеживает изменения."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice


def main() -> None:
    # Храним предыдущее состояние
    prev_grids: Dict[int, List[float]] = {}  # entityId -> position
    prev_player: List[float] | None = None

    def on_telemetry_update(dev: OreDetectorDevice, telemetry: Dict[str, Any], source_event: str) -> None:
        nonlocal prev_grids, prev_player
        if not isinstance(telemetry, dict):
            return

        radar = telemetry.get("radar")
        if not isinstance(radar, dict):
            return

        contacts = radar.get("contacts", [])
        if not isinstance(contacts, list):
            contacts = []

        # Текущие гриды: entityId -> position
        current_grids = {}
        current_player = None

        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            ctype = contact.get("type")
            pos = contact.get("position")
            if not isinstance(pos, list) or len(pos) != 3:
                continue

            if ctype == "grid":
                entity_id = contact.get("entityId")
                if entity_id is not None:
                    current_grids[int(entity_id)] = pos
            elif ctype == "player":
                current_player = pos

        # Сравниваем с предыдущим и печатаем события
        # Новые гриды
        for eid, pos in current_grids.items():
            if eid not in prev_grids:
                print(f"Новый грид появился: entityId={eid}, pos={pos}")

        # Исчезнувшие гриды
        for eid in prev_grids:
            if eid not in current_grids:
                print(f"Грид исчез: entityId={eid}")

        # Переместившиеся гриды
        for eid, pos in current_grids.items():
            if eid in prev_grids and pos != prev_grids[eid]:
                print(f"Грид переместился: entityId={eid}, old={prev_grids[eid]}, new={pos}")

        # Игрок
        if current_player != prev_player:
            if prev_player is None and current_player is not None:
                print(f"Игрок появился: pos={current_player}")
            elif prev_player is not None and current_player is None:
                print("Игрок исчез")
            elif prev_player is not None and current_player is not None:
                print(f"Игрок переместился: old={prev_player}, new={current_player}")

        # Обновляем предыдущее состояние
        prev_grids = current_grids.copy()
        prev_player = current_player

        # Всегда выводим текущие координаты
        if current_grids:
            print(f"Текущие гриды: {current_grids}")
        else:
            print("Текущие гриды: нет")

        if current_player:
            print(f"Игрок: {current_player}")
        else:
            print("Игрок: не найден")

        print("---")

    grid = prepare_grid("taburet")
    try:
        # Найти ore_detector
        detectors = grid.find_devices_by_type(OreDetectorDevice)
        if not detectors:
            print("На гриде не найдено ни одного детектора руды (ore_detector).")
            return
        device = detectors[0]
        print(f"Найден радар device_id={device.device_id} name={device.name!r}")
        print(f"Ключ телеметрии: {device.telemetry_key}")

        # Подписка на телеметрию
        device.on("telemetry", on_telemetry_update)


        # Цикл обновления
        try:
            while True:
                # Запустить сканирование
                seq = device.scan(
                    include_players=True,
                    include_grids=True,
                    radius=500,
                    contacts_hz=1.0,  # Частота обновления контактов
                )
                print(f"Scan отправлен, seq={seq}. Ожидание телеметрии... (Ctrl+C для выхода)")

                time.sleep(1)

        except KeyboardInterrupt:
            print("Выход...")

    finally:
        device.off("telemetry", on_telemetry_update)
        close(grid)


if __name__ == "__main__":
    main()
