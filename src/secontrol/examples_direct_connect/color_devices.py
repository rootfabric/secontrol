"""Пример массовой покраски всех блоков первого доступного грида."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Iterator, List, Sequence, Set

from sepy.common import close, prepare_grid


def _normalize_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_color_from_env() -> Dict[str, Any]:
    hsv = os.getenv("GRID_BLOCK_COLOR_HSV")
    if hsv:
        return {"color": hsv, "space": "hsv"}

    rgb = os.getenv("GRID_BLOCK_COLOR_RGB")
    if rgb:
        return {"color": rgb, "space": "rgb"}

    color = os.getenv("GRID_BLOCK_COLOR")
    if color:
        space = os.getenv("GRID_BLOCK_COLOR_SPACE")
        payload: Dict[str, Any] = {"color": color}
        if space:
            payload["space"] = space
        return payload

    raise SystemExit(
        "Задайте один из GRID_BLOCK_COLOR, GRID_BLOCK_COLOR_RGB или GRID_BLOCK_COLOR_HSV"
    )


_BLOCK_ID_KEYS: Sequence[str] = (
    "blockId",
    "block_id",
    "entityId",
    "entity_id",
    "cubeBlockId",
    "id",
)

_BLOCK_CONTEXT_KEYS: Sequence[str] = (
    "type",
    "blockType",
    "subtype",
    "definition",
    "definitionId",
    "displayName",
    "name",
    "min",
    "max",
)


def _extract_block_id(entry: Dict[str, Any]) -> int | None:
    if not any(key in entry for key in _BLOCK_CONTEXT_KEYS):
        return None

    for key in _BLOCK_ID_KEYS:
        if key not in entry:
            continue
        try:
            value = int(entry[key])
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _collect_metadata_block_ids(metadata: Dict[str, Any]) -> Set[int]:
    pending: List[Any] = [metadata]
    collected: Set[int] = set()

    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            maybe_id = _extract_block_id(current)
            if maybe_id:
                collected.add(maybe_id)
            for value in current.values():
                if isinstance(value, (dict, list)):
                    pending.append(value)
        elif isinstance(current, list):
            for value in current:
                if isinstance(value, (dict, list)):
                    pending.append(value)

    return collected


def _collect_device_block_ids(devices: Iterable[Any]) -> Set[int]:
    block_ids: Set[int] = set()
    for device in devices:
        device_id = getattr(device, "device_id", None)
        if device_id is None:
            continue
        try:
            value = int(device_id)
        except (TypeError, ValueError):
            continue
        if value > 0:
            block_ids.add(value)
    return block_ids


def _collect_all_block_ids(grid) -> List[int]:
    block_ids: Set[int] = set()

    try:
        grid.refresh_devices()
    except AttributeError:
        pass

    devices = getattr(grid, "devices", {})
    if isinstance(devices, dict):
        block_ids.update(_collect_device_block_ids(devices.values()))

    metadata = getattr(grid, "metadata", None)
    if isinstance(metadata, dict):
        block_ids.update(_collect_metadata_block_ids(metadata))

    return sorted(block_ids)


def _chunked(values: Sequence[int], size: int = 50) -> Iterator[Sequence[int]]:
    if size <= 0:
        size = 50
    for start in range(0, len(values), size):
        yield values[start : start + size]


def main() -> None:
    # color_payload = _parse_color_from_env()
    color_payload = {"color": "0,128,0", "space": "rgb"}
    # color_payload = {"color": "246,0,142", "space": "rgb"}
    play_sound = _normalize_bool(os.getenv("GRID_BLOCK_PLAY_SOUND"))

    client, grid = prepare_grid()
    try:
        block_ids = _collect_all_block_ids(grid)
        if not block_ids:
            raise SystemExit(
                "Не удалось найти ни одного блока в gridinfo. Убедитесь, что Redis содержит обновлённые данные."
            )

        print(
            f"Покраска {len(block_ids)} блоков грида {grid.grid_id} с цветом "
            f"{', '.join(f'{k}={v}' for k, v in color_payload.items())}"
        )

        total_commands = 0
        for chunk in _chunked(block_ids):
            payload: Dict[str, Any] = {
                **color_payload,
                "blocks": [{"blockId": block_id} for block_id in chunk],
            }
            if play_sound is not None:
                payload["playSound"] = play_sound
            sent = grid.send_grid_command("paint_blocks", payload=payload)
            total_commands += sent

        print(f"Отправлено команд: {total_commands}")
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
