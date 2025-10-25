"""Пример покраски блоков грида с использованием данных ``grid.iter_blocks`` с пер-блочным цветом."""

from __future__ import annotations

import os
import random
from typing import Any, Dict, Iterable, Iterator, List, Sequence, Tuple

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


def _generate_random_rgb() -> str:
    """Generate a random RGB color string 'r,g,b' with 0..255 each."""
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    return f"{r},{g},{b}"


def _sanitize_rgb_str(rgb: str) -> str:
    """
    Приводит строку 'r,g,b' к целым 0..255 и возвращает нормализованную строку.
    Некорректные/выходящие за диапазон значения будут зажаты в 0..255.
    """
    parts = (rgb or "").replace(" ", "").split(",")
    if len(parts) != 3:
        #fallback: чёрный
        return "0,0,0"

    clamped: List[int] = []
    for p in parts:
        try:
            v = int(float(p))
        except (ValueError, TypeError):
            v = 0
        if v < 0:
            v = 0
        elif v > 255:
            v = 255
        clamped.append(v)
    r, g, b = clamped
    return f"{r},{g},{b}"


def _color_payload_for_block(block: Any) -> Dict[str, Any]:
    """
    Возвращает payload цвета ДЛЯ КОНКРЕТНОГО БЛОКА.
    Режим выбирается через GRID_BLOCK_COLOR_MODE:
      - 'fixed'  (по умолчанию): берёт GRID_BLOCK_RGB или '0,0,0'
      - 'random': случайный цвет на каждый блок
    """
    mode = (os.getenv("GRID_BLOCK_COLOR_MODE", "fixed") or "fixed").strip().lower()
    if mode == "random":
        color = _generate_random_rgb()
    else:
        # color = _sanitize_rgb_str(os.getenv("GRID_BLOCK_RGB", "255,255,255"))
        color = _sanitize_rgb_str(os.getenv("GRID_BLOCK_RGB", "50,250,50"))

    # Только чистый RGB, как просили
    return {"color": color, "space": "rgb"}


def _collect_blocks_with_ids(blocks: Iterable[Any]) -> List[Tuple[int, Any]]:
    result: List[Tuple[int, Any]] = []
    for block in blocks:
        block_id = getattr(block, "block_id", None)
        if block_id is None:
            continue
        try:
            resolved = int(block_id)
        except (TypeError, ValueError):
            continue
        if resolved > 0:
            result.append((resolved, block))
    return result


def _chunked(values: Sequence[Tuple[int, Any]], size: int = 50) -> Iterator[Sequence[Tuple[int, Any]]]:
    if size <= 0:
        size = 50
    for start in range(0, len(values), size):
        yield values[start : start + size]


def main() -> None:
    """Покрашивает все известные блоки выбранного грида, назначая цвет для КАЖДОГО блока отдельно."""
    play_sound = _normalize_bool(os.getenv("GRID_BLOCK_PLAY_SOUND"))
    chunk_size = os.getenv("GRID_BLOCK_BATCH")
    try:
        batch_size = int(chunk_size) if chunk_size is not None else 50
    except ValueError:
        batch_size = 50

    # Можно указать GRID_ID, иначе используйте свою логику выбора
    grid_id = os.getenv("GRID_ID", "143981447307572837")

    client, grid = prepare_grid(grid_id)
    try:
        blocks_with_ids = _collect_blocks_with_ids(grid.iter_blocks())
        if not blocks_with_ids:
            raise SystemExit(
                "Не удалось найти ни одного блока. Убедитесь, что Redis содержит обновлённые данные о гриде."
            )

        print(f"Покраска {len(blocks_with_ids)} блоков грида {grid.grid_id} пер-блочными цветами...")

        total_commands = 0
        for chunk in _chunked(blocks_with_ids, batch_size):
            # ВАЖНО: цвет вычисляем ДЛЯ КАЖДОГО БЛОКА отдельно
            blocks_payload = []
            for block_id, block in chunk:
                color_payload = _color_payload_for_block(block)
                blocks_payload.append({
                    "blockId": block_id,
                    # Цвет задаём на уровне каждого блока
                    "color": color_payload["color"],
                    "space": color_payload["space"],
                })

            payload: Dict[str, Any] = {"blocks": blocks_payload}
            if play_sound is not None:
                payload["playSound"] = play_sound

            # Одна команда на порцию блоков
            sent = grid.send_grid_command("paint_blocks", payload=payload)
            total_commands += sent

        print(f"Отправлено команд: {total_commands}")
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
