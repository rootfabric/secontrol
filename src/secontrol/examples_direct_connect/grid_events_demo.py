"""Минимальный пример подписки на события устройств и целостности грида."""

from __future__ import annotations

import time
from typing import Any, Dict

from secontrol.base_device import (
    GridDevicesEvent,
    GridIntegrityChange,
    Grid,
    RemovedDeviceInfo,
)
from secontrol.common import prepare_grid


def _describe_added(devices: list[Any]) -> str:
    labels = []
    for device in devices:
        name = getattr(device, "name", None) or getattr(device, "device_type", "device")
        labels.append(f"{name} (#{getattr(device, 'device_id', '?')})")
    return ", ".join(labels) if labels else "нет"


def _describe_removed(devices: list[RemovedDeviceInfo]) -> str:
    labels = []
    for info in devices:
        base = info.name or info.device_type or "device"
        labels.append(f"{base} (#{info.device_id})")
    return ", ".join(labels) if labels else "нет"


def _format_integrity(change: GridIntegrityChange) -> str:
    prev = change.previous_integrity
    curr = change.current_integrity
    if prev is None or curr is None:
        return f"{prev} -> {curr}"
    return f"{prev:.1f} -> {curr:.1f}"


def main() -> None:
    grid = prepare_grid()
    print(f"Подписываемся на грид {grid.name} (ID: {grid.grid_id})")

    def _on_devices(g: Grid, payload: GridDevicesEvent, source: str) -> None:
        added = _describe_added(payload.added)
        removed = _describe_removed(payload.removed)
        print(f"[{source}] Изменение состава устройств: добавлено {added}; удалено {removed}")

    def _on_integrity(g: Grid, payload: Dict[str, list[GridIntegrityChange]], source: str) -> None:
        changes = payload.get("changes", [])
        if not changes:
            return
        print(f"[{source}] Изменение целостности блоков ({len(changes)} шт.):")
        for change in changes:
            label = change.name or change.subtype or change.block_type or "block"
            print(
                f"  - {label} (#{change.block_id}): { _format_integrity(change) } | "
                f"damaged: {change.was_damaged} -> {change.is_damaged}"
            )

    grid.on("devices", _on_devices)
    grid.on("integrity", _on_integrity)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
