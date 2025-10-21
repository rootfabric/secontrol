"""Пример покраски блоков грида с использованием данных ``grid.iter_blocks``."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Iterator, Sequence

from secontrol.common import close, prepare_grid


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

    return {"color": "0,0,200", "space": "rgb"}
    # hsv = os.getenv("GRID_BLOCK_COLOR_HSV")
    # if hsv:
    #     return {"color": hsv, "space": "hsv"}
    #
    # rgb = os.getenv("GRID_BLOCK_COLOR_RGB")
    # if rgb:
    #     return {"color": rgb, "space": "rgb"}
    #
    # color = os.getenv("GRID_BLOCK_COLOR")
    # if color:
    #     space = os.getenv("GRID_BLOCK_COLOR_SPACE")
    #     payload: Dict[str, Any] = {"color": color}
    #     if space:
    #         payload["space"] = space
    #     return payload
    #
    # raise SystemExit(
    #     "Задайте один из GRID_BLOCK_COLOR, GRID_BLOCK_COLOR_RGB или GRID_BLOCK_COLOR_HSV"
    # )


def _collect_block_ids(blocks: Iterable[Any]) -> list[int]:
    block_ids: list[int] = []
    for block in blocks:
        block_id = getattr(block, "block_id", None)
        if block_id is None:
            continue
        try:
            resolved = int(block_id)
        except (TypeError, ValueError):
            continue
        if resolved > 0:
            block_ids.append(resolved)
    return block_ids


def _chunked(values: Sequence[int], size: int = 50) -> Iterator[Sequence[int]]:
    if size <= 0:
        size = 50
    for start in range(0, len(values), size):
        yield values[start : start + size]


def main() -> None:
    """Покрашивает все известные блоки выбранного грида."""

    color_payload = _parse_color_from_env()
    play_sound = _normalize_bool(os.getenv("GRID_BLOCK_PLAY_SOUND"))
    chunk_size = os.getenv("GRID_BLOCK_BATCH")
    try:
        batch_size = int(chunk_size) if chunk_size is not None else 99999
    except ValueError:
        batch_size = 500

    client, grid = prepare_grid()
    try:
        block_ids = _collect_block_ids(grid.iter_blocks())
        print(block_ids)
        if not block_ids:
            raise SystemExit(
                "Не удалось найти ни одного блока. Убедитесь, что Redis содержит обновлённые данные о гриде."
            )

        print(
            f"Покраска {len(block_ids)} блоков грида {grid.grid_id} с цветом "
            f"{', '.join(f'{k}={v}' for k, v in color_payload.items())}"
        )

        total_commands = 0
        for chunk in _chunked(block_ids, batch_size):
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
