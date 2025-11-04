"""
Example: Random coloring of all grid blocks.

This script assigns random colors to all blocks in a grid using RGB color space.
Each block gets a unique random color.
"""

from __future__ import annotations

import os

from typing import Any, Dict, Iterable, Iterator, Sequence

from secontrol.common import close, prepare_grid
import random


def _normalize_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


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


def _generate_random_rgb() -> str:
    """Generate a random RGB color string."""
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    return f"{r},{g},{b}"


def main() -> None:
    """Paint all blocks in the selected grid with random colors."""

    play_sound = _normalize_bool(os.getenv("GRID_BLOCK_PLAY_SOUND"))
    chunk_size = os.getenv("GRID_BLOCK_BATCH")
    try:
        batch_size = int(chunk_size) if chunk_size is not None else 50
    except ValueError:
        batch_size = 50

    grid = prepare_grid()
    try:
        block_ids = _collect_block_ids(grid.iter_blocks())
        if not block_ids:
            raise SystemExit(
                "Не удалось найти ни одного блока. Убедитесь, что Redis содержит обновлённые данные о гриде."
            )

        print(f"Раскраска {len(block_ids)} блоков грида {grid.grid_id} случайными цветами")

        total_commands = 0
        for chunk in _chunked(block_ids, batch_size):
            # Create payload with random colors for each block
            payload: Dict[str, Any] = {
                "blocks": [
                    {"blockId": block_id, "color": _generate_random_rgb(), "space": "rgb"}
                    for block_id in chunk
                ],
            }
            print(payload)
            if play_sound is not None:
                payload["playSound"] = play_sound
            sent = grid.send_grid_command("paint_blocks", payload=payload)
            total_commands += sent

        print(f"Отправлено команд: {total_commands}")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
