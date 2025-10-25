"""
Paint a small image onto a grid by coloring armor blocks like pixels (pure RGB).

- Всегда шлёт на сервер **чистый RGB** (0..255) без конверсий.
- Дополнительно сохраняет:
  1) точную копию исходной картинки (ориг. разрешение/цвета)
  2) downscale-версию (width x height), по которой красим блоки

Env:
- GRID_ID
- GRID_IMAGE_FILE            (default: ./python.png)
- GRID_IMAGE_WIDTH           (default: 10)
- GRID_IMAGE_HEIGHT          (default: 10)
- GRID_IMAGE_BLOCK_TYPE      (default: LargeBlockArmorBlock)
- GRID_IMAGE_PLANE           xy|xz|yz (default: xy)
- GRID_IMAGE_ALIGN_X         min|center|max (default: min)
- GRID_IMAGE_ALIGN_Y         min|center|max (default: min)
- GRID_IMAGE_OFFSET_X        (default: 0)
- GRID_IMAGE_OFFSET_Y        (default: 0)
- GRID_IMAGE_FLIP_Y          1/0 (default: 1)
- GRID_IMAGE_FLIP_X          1/0 (default: 0)
- GRID_BLOCK_BATCH           (default: 50)
- GRID_BLOCK_PLAY_SOUND      1/0 (default: unset)
- GRID_IMAGE_OUTDIR          куда сохранять копии (default: рядом с исходником)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from secontrol.common import close, prepare_grid


# ---------------------------- small helpers ----------------------------

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_int_opt(value: Optional[str]) -> Optional[int]:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _detect_step(sorted_values: Sequence[float]) -> float:
    diffs = []
    for a, b in zip(sorted_values, sorted_values[1:]):
        d = b - a
        if d > 1e-6:
            diffs.append(d)
    if not diffs:
        return 1.0
    return _median(diffs)


def _unique_sorted(values: Iterable[float]) -> List[float]:
    return sorted({round(float(v), 6) for v in values})


def _chunked(values: Sequence[Any], size: int = 50) -> Iterator[Sequence[Any]]:
    if size <= 0:
        size = 50
    for start in range(0, len(values), size):
        yield values[start : start + size]


@dataclass(frozen=True)
class _Block2D:
    block_id: int
    x: float
    y: float
    ix: int
    iy: int


def _project_block_xy_plane(block: Any, plane: str) -> Optional[Tuple[float, float]]:
    pos = getattr(block, "local_position", None)
    if not isinstance(pos, tuple) or len(pos) < 3:
        return None
    x, y, z = pos[0], pos[1], pos[2]
    p = plane.lower()
    if p == "xy":
        return float(x), float(y)
    if p == "xz":
        return float(x), float(z)
    if p == "yz":
        return float(y), float(z)
    return float(x), float(y)


def _filter_blocks_for_plane(
    blocks: Iterable[Any], *, block_type: Optional[str], plane: str
) -> List[Tuple[int, float, float]]:
    result: List[Tuple[int, float, float]] = []
    want_type = (block_type or "").strip().lower() or None
    for b in blocks:
        bid = getattr(b, "block_id", None)
        if not isinstance(bid, int) or bid <= 0:
            continue
        if want_type:
            bt = (getattr(b, "subtype", None) or getattr(b, "block_type", None) or "").strip().lower()
            if bt != want_type:
                continue
        coords = _project_block_xy_plane(b, plane)
        if coords is None:
            continue
        x, y = coords
        result.append((bid, float(x), float(y)))
    return result


def _index_blocks(
    blocks_xy: List[Tuple[int, float, float]]
) -> Tuple[List[_Block2D], List[float], List[float], float, float]:
    if not blocks_xy:
        return [], [], [], 1.0, 1.0

    xs = _unique_sorted(x for _, x, _ in blocks_xy)
    ys = _unique_sorted(y for _, _, y in blocks_xy)

    step_x = _detect_step(xs)
    step_y = _detect_step(ys)
    min_x = xs[0]
    min_y = ys[0]

    out: List[_Block2D] = []
    seen: set[Tuple[int, int]] = set()
    for bid, x, y in blocks_xy:
        ix = int(round((x - min_x) / step_x))
        iy = int(round((y - min_y) / step_y))
        key = (ix, iy)
        if key in seen:
            continue
        seen.add(key)
        out.append(_Block2D(bid, x, y, ix, iy))

    unique_ix = sorted({b.ix for b in out})
    unique_iy = sorted({b.iy for b in out})
    return out, [min_x + i * step_x for i in unique_ix], [min_y + j * step_y for j in unique_iy], step_x, step_y


def _choose_window(unique_indices: List[int], need: int, align: str) -> Tuple[int, int]:
    if not unique_indices:
        return 0, need
    imin = min(unique_indices)
    imax = max(unique_indices)
    total = imax - imin + 1
    if need >= total:
        return imin, total
    align_l = (align or "min").strip().lower()
    if align_l == "max":
        start = imax - need + 1
    elif align_l == "center":
        start = imin + (total - need) // 2
    else:
        start = imin
    return start, need


# ---------------------------- image I/O ----------------------------

def _ensure_dir(path: str) -> None:
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def _load_pixels_and_save_copies(
    src_path: str, width: int, height: int, outdir: Optional[str]
) -> Tuple[List[Tuple[int, int, int]], str, str]:
    """
    Возвращает:
      - pixels: список RGB-пикселей из уменьшенного изображения width x height
      - orig_path: путь к сохранённой точной копии исходника (ориг. разрешение/цвета)
      - resized_path: путь к сохранённой уменьшенной RGB-картинке (width x height)
    """
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:
        raise SystemExit("Pillow is required. Install: pip install Pillow") from exc

    base_name = os.path.splitext(os.path.basename(src_path))[0]
    outdir = outdir or os.path.dirname(src_path) or "."
    _ensure_dir(outdir)

    orig_path = os.path.join(outdir, f"{base_name}.orig.png")
    resized_path = os.path.join(outdir, f"{base_name}.resized_{width}x{height}.png")

    # 1) Сохраняем исходник без конверсий (макс. сохранение профиля/EXIF)
    with Image.open(src_path) as src:
        icc = src.info.get("icc_profile")
        exif = src.info.get("exif")
        # PNG сам по себе не всегда хранит EXIF, но не мешает попробовать
        save_kwargs = {}
        if icc:
            save_kwargs["icc_profile"] = icc
        if exif:
            save_kwargs["exif"] = exif
        src.save(orig_path, format="PNG", **save_kwargs)

    # 2) Готовим уменьшенную RGB-версию, по которой красим блоки, и сохраняем её
    with Image.open(src_path).convert("RGB") as img_rgb:
        img_small = img_rgb.resize((width, height), resample=Image.NEAREST)
        img_small.save(resized_path, format="PNG")
        pixels: List[Tuple[int, int, int]] = []
        for y in range(height):
            for x in range(width):
                r, g, b = img_small.getpixel((x, y))
                pixels.append((int(r), int(g), int(b)))

    return pixels, orig_path, resized_path


# ---------------------------- main logic (pure RGB only) ----------------------------

def main() -> None:
    # image_file = os.getenv("GRID_IMAGE_FILE") or os.path.join(os.path.dirname(__file__), "python.png")
    image_file = os.getenv("GRID_IMAGE_FILE") or os.path.join(os.path.dirname(__file__), "mars_python.jpg ")
    grid_id = _parse_int_opt(os.getenv("GRID_ID"))

    width = _parse_int(os.getenv("GRID_IMAGE_WIDTH"), 150)
    height = _parse_int(os.getenv("GRID_IMAGE_HEIGHT"), 150)

    block_type = os.getenv("GRID_IMAGE_BLOCK_TYPE", "LargeBlockArmorBlock")
    plane = os.getenv("GRID_IMAGE_PLANE", "xy").lower()
    align_x = os.getenv("GRID_IMAGE_ALIGN_X", "min").lower()
    align_y = os.getenv("GRID_IMAGE_ALIGN_Y", "min").lower()
    off_x = _parse_int(os.getenv("GRID_IMAGE_OFFSET_X"), 0)
    off_y = _parse_int(os.getenv("GRID_IMAGE_OFFSET_Y"), 0)
    flip_y = _parse_bool(os.getenv("GRID_IMAGE_FLIP_Y", "1"), True)
    flip_x = _parse_bool(os.getenv("GRID_IMAGE_FLIP_X"), False)

    batch_size = _parse_int(os.getenv("GRID_BLOCK_BATCH"), 50)
    play_sound_env = os.getenv("GRID_BLOCK_PLAY_SOUND")
    play_sound: Optional[bool] = None
    if play_sound_env is not None:
        play_sound = _parse_bool(play_sound_env, False)

    outdir = os.getenv("GRID_IMAGE_OUTDIR")  # None -> рядом с исходником

    # Загружаем пиксели и сохраняем обе версии для проверки
    pixels, saved_orig, saved_resized = _load_pixels_and_save_copies(image_file, width, height, outdir)

    try:
        client, grid = prepare_grid(grid_id)
    except RuntimeError as exc:
        msg = str(exc)
        if "No grids were found" in msg:
            print(
                "Не найдены гриды для указанного владельца. "
                "Запустите: python -m secontrol.examples_direct_connect.list_grids"
            )
            raise SystemExit(2)
        raise

    try:
        # Собираем блоки и строим индексацию
        blocks_xy = _filter_blocks_for_plane(grid.iter_blocks(), block_type=block_type, plane=plane)
        if not blocks_xy:
            raise SystemExit("No candidate blocks found with coordinates to paint on.")

        indexed, xs, ys, step_x, step_y = _index_blocks(blocks_xy)
        if not indexed:
            raise SystemExit("Failed to index grid blocks by coordinates.")

        unique_ix = sorted({b.ix for b in indexed})
        unique_iy = sorted({b.iy for b in indexed})

        start_ix, win_w = _choose_window(unique_ix, width, align_x)
        start_iy, win_h = _choose_window(unique_iy, height, align_y)
        start_ix += off_x
        start_iy += off_y

        grid_map: Dict[Tuple[int, int], int] = {(b.ix, b.iy): b.block_id for b in indexed}

        per_block_payloads: List[Dict[str, Any]] = []

        for py in range(height):
            iy = start_iy + (win_h - 1 - py) if flip_y else start_iy + py
            for px in range(width):
                ix = start_ix + (win_w - 1 - px) if flip_x else start_ix + px
                block_id = grid_map.get((ix, iy))
                if block_id is None:
                    continue
                r, g, b = pixels[py * width + px]

                # PURE RGB: строго 0..255, без преобразований
                per_block_payloads.append({
                    "blockId": int(block_id),
                    "rgb": {"r": int(r), "g": int(g), "b": int(b)},
                })

        if not per_block_payloads:
            raise SystemExit("No blocks matched the selected image window to paint.")

        total_commands = 0
        for chunk in _chunked(per_block_payloads, batch_size):
            payload: Dict[str, Any] = {
                "blocks": list(chunk),
                "space": "rgb",  # явный хинт парсеру на сервере
            }
            if play_sound is not None:
                payload["playSound"] = play_sound
            sent = grid.send_grid_command("paint_blocks", payload=payload)
            total_commands += sent

        print(f"Painted {len(per_block_payloads)} blocks in {total_commands} publish commands.")
        print(f"Saved original copy: {saved_orig}")
        print(f"Saved resized preview: {saved_resized}")
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
