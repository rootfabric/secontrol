"""Subscribe to ore detector telemetry and output ore when there are updates."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.common import resolve_owner_id, prepare_grid


def _pick_radar_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Выбирает словарь радара из телеметрии, учитывая разные схемы."""

    # Обычный случай: внутри поля radar
    rad = data.get("radar")
    if isinstance(rad, dict):
        return rad
    # Альтернативно некоторые плагины складывают поля прямо в корень
    root_keys = set(data.keys())
    if {"contacts", "cellSize"} & root_keys:
        return data
    if {"contacts", "radius"} & root_keys:
        return data
    # Возможные обёртки
    alt = data.get("voxel") or data.get("ore") or data.get("map")
    if isinstance(alt, dict):
        return alt
    return None


def _extract_ore_cells(radar: Dict[str, Any]) -> tuple[list[dict], int]:
    """Извлекает список ячеек руды и флаг усечения из разных возможных полей."""

    cells: list[dict] = []
    truncated = 0

    # Основные варианты
    raw = radar.get("oreCells")
    if isinstance(raw, list):
        cells = [c for c in raw if isinstance(c, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("cells"), list):
        cells = [c for c in raw.get("cells", []) if isinstance(c, dict)]

    # Альтернативные имена/размещения
    if not cells:
        for key in ("ore_cells", "cells", "ores"):
            alt = radar.get(key)
            if isinstance(alt, list):
                cells = [c for c in alt if isinstance(c, dict)]
                break
            if isinstance(alt, dict) and isinstance(alt.get("cells"), list):
                cells = [c for c in alt.get("cells", []) if isinstance(c, dict)]
                break

    # Признак усечения
    trunc = radar.get("oreCellsTruncated")
    try:
        truncated = int(trunc) if trunc is not None else 0
    except (TypeError, ValueError):
        truncated = 0

    return cells, truncated


def main() -> None:
    owner_id = resolve_owner_id()
    print(owner_id)

    client, grid = prepare_grid("117014494109101689")

    ore_detector = next(
        (device for device in grid.devices.values() if isinstance(device, OreDetectorDevice)),
        None,
    )
    if ore_detector is None:
        print("No ore_detector detected on the selected grid.")
        return

    print(f"Found ore detector {ore_detector.device_id} named {ore_detector.name!r}")
    print(f"Telemetry key: {ore_detector.telemetry_key}")
    print("Subscribing to telemetry updates... (Ctrl+C to exit)")

    last_rev: Optional[int] = None
    last_ore_count: Optional[int] = None
    cached_ore_cells: list[dict] = []
    cached_ore_count: int = 0

    def _on_update(_key: str, payload: Any, event: str) -> None:
        nonlocal last_rev, last_ore_count
        if event == "del":
            print("[ore detector] telemetry deleted")
            return

        data: Dict[str, Any] | None = None
        if isinstance(payload, dict):
            data = payload
        elif isinstance(payload, str):
            text = payload.strip()
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = None

        if not isinstance(data, dict):
            return

        radar = _pick_radar_dict(data)
        ore_cells, _truncated = _extract_ore_cells(radar or {})

        # Ревизия
        rev_val = radar.get("revision") if radar else None
        try:
            rev = int(rev_val) if rev_val is not None else None
        except (TypeError, ValueError):
            rev = None

        ore_count_field = None
        try:
            ore_count_field = int(radar.get("oreCellCount")) if isinstance(radar, dict) and radar.get("oreCellCount") is not None else None
        except (TypeError, ValueError):
            ore_count_field = None

        contacts_count = len(radar.get("contacts", [])) if isinstance(radar, dict) else 0
        ore_effective = (ore_count_field if (ore_count_field is not None and not ore_cells) else len(ore_cells))

        # Кэшируем последнюю известную руду
        used_cached = False
        if ore_effective == 0 and cached_ore_count > 0:
            ore_effective = cached_ore_count
            if not ore_cells and cached_ore_cells:
                ore_cells = cached_ore_cells
            used_cached = True
        else:
            if ore_effective > 0:
                cached_ore_count = ore_effective
                cached_ore_cells = ore_cells[:]

        # Печатаем при изменении количества руды или ревизии
        if rev != last_rev or ore_effective != (last_ore_count if last_ore_count is not None else -1):
            last_rev = rev
            last_ore_count = ore_effective

            print(
                f"[ore detector] rev={rev}, contacts={contacts_count}, oreCells={ore_effective}{' [cached]' if used_cached else ''}"
            )

            # Перечень руды
            if ore_cells:
                preview = []
                for c in ore_cells[:5]:  # Первые 5 для превью
                    ore = c.get("ore") or c.get("material") or "?"
                    content = c.get("content")
                    idx = c.get("index")
                    preview.append(f"{ore}@{idx}:{content}")
                print(f"  Ores: {', '.join(preview)}{' (truncated)' if len(ore_cells) > 5 else ''}")
            elif ore_count_field:
                print(f"[ore detector] note: oreCells list missing, but oreCellCount={ore_count_field}")

    sub = client.subscribe_to_key(ore_detector.telemetry_key, _on_update)

    try:
        ore_detector.scan()  # Первый скан
        while True:
            time.sleep(1)  # Периодический скан
            ore_detector.scan()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sub.close()
        except Exception:
            pass

        # Завершение
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
