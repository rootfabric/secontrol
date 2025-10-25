"""
Paint a small image onto a grid by coloring armor blocks like pixels.

What it does
- Loads an image (default: `python.png` in this folder)
- Resizes it to a small grid (default: 10x10)
- Maps image pixels to grid blocks using block local coordinates
- Sends paint commands with per-block RGB colors

Environment variables
- GRID_IMAGE_FILE           Path to image (default: ./python.png)
- GRID_IMAGE_WIDTH          Target width in pixels (default: 10)
- GRID_IMAGE_HEIGHT         Target height in pixels (default: 10)
- GRID_IMAGE_BLOCK_TYPE     Block subtype/type to use (default: LargeBlockArmorBlock)
- GRID_IMAGE_PLANE          One of: xy, xz, yz (default: xy)
- GRID_IMAGE_ALIGN_X        One of: min, center, max (default: min)
- GRID_IMAGE_ALIGN_Y        One of: min, center, max (default: min)
- GRID_IMAGE_OFFSET_X       Integer index offset for X (default: 0)
- GRID_IMAGE_OFFSET_Y       Integer index offset for Y (default: 0)
- GRID_IMAGE_FLIP_Y         Flip image vertically so row 0 is top (default: 1)
- GRID_IMAGE_FLIP_X         Flip image horizontally (default: 0)
- GRID_BLOCK_BATCH          Batch size for paint_blocks command (default: 50)
- GRID_BLOCK_PLAY_SOUND     1/0 to play paint sound (default: unset)
- GRID_IMAGE_COLOR_SPACE    rgb | hsv | auto (default: auto)
  In auto mode, near-grey colors (including white) are sent in HSV with s=0 to avoid tinting.
  Tweak threshold via GRID_IMAGE_GREY_EPS (default: 3)
  Additional HSV controls:
  - GRID_IMAGE_S_EPS        Minimal saturation to consider non-grey (default: 0.02)
  - GRID_IMAGE_WHITE_MIN    Min channel value [0..255] to force v=1 for white (default: 250)
  - GRID_IMAGE_HUE_ZERO     Calibrate hue baseline [0..1], maps to mask 0 (default: 0.5)
  - GRID_IMAGE_SWAP_RB      1/0 optional quick test to swap R and B before conversion (default: 0)

Note: requires Pillow (pip install Pillow)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from secontrol.common import close, prepare_grid


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


def _parse_float(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _median(values: Sequence[float]) -> float:
    if not values:
        return 1.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def _detect_step(sorted_values: Sequence[float]) -> float:
    # Take positive diffs, drop zeros and near-zeros
    diffs = []
    for a, b in zip(sorted_values, sorted_values[1:]):
        d = b - a
        if d > 1e-6:
            diffs.append(d)
    if not diffs:
        return 1.0
    # Use median for robustness against outliers
    return _median(diffs)


def _unique_sorted(values: Iterable[float]) -> List[float]:
    # Round to micro precision to collapse float noise
    rounded = sorted({round(float(v), 6) for v in values})
    return rounded


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


def _filter_blocks_for_plane(blocks: Iterable[Any], *, block_type: Optional[str], plane: str) -> List[Tuple[int, float, float]]:
    result: List[Tuple[int, float, float]] = []
    want_type = (block_type or "").strip().lower() or None
    for b in blocks:
        bid = getattr(b, "block_id", None)
        if not isinstance(bid, int) or bid <= 0:
            continue
        if want_type:
            # Compare against subtype or type lowered
            bt = (getattr(b, "subtype", None) or getattr(b, "block_type", None) or "").strip().lower()
            if bt != want_type:
                continue
        coords = _project_block_xy_plane(b, plane)
        if coords is None:
            continue
        x, y = coords
        result.append((bid, float(x), float(y)))
    return result


def _index_blocks(blocks_xy: List[Tuple[int, float, float]]) -> Tuple[List[_Block2D], List[float], List[float], float, float]:
    if not blocks_xy:
        return [], [], [], 1.0, 1.0

    xs = _unique_sorted(x for _, x, _ in blocks_xy)
    ys = _unique_sorted(y for _, _, y in blocks_xy)

    step_x = _detect_step(xs)
    step_y = _detect_step(ys)
    min_x = xs[0]
    min_y = ys[0]

    # Build index map; use rounding to nearest integer index based on detected step
    out: List[_Block2D] = []
    seen: set[Tuple[int, int]] = set()
    for bid, x, y in blocks_xy:
        ix = int(round((x - min_x) / step_x))
        iy = int(round((y - min_y) / step_y))
        key = (ix, iy)
        if key in seen:
            # Prefer first occurrence; duplicates are unexpected but possible due to rounding
            continue
        seen.add(key)
        out.append(_Block2D(bid, x, y, ix, iy))

    # Recompute unique ix/iy present
    unique_ix = sorted({b.ix for b in out})
    unique_iy = sorted({b.iy for b in out})
    return out, [min_x + i * step_x for i in unique_ix], [min_y + j * step_y for j in unique_iy], step_x, step_y


def _choose_window(unique_indices: List[int], need: int, align: str) -> Tuple[int, int]:
    if not unique_indices:
        return 0, need
    # Assume indices are contiguous (or nearly so). Use min/center/max alignment on the range [min..max].
    imin = min(unique_indices)
    imax = max(unique_indices)
    total = imax - imin + 1
    if need >= total:
        return imin, total
    align_l = align.strip().lower() if align else "min"
    if align_l == "max":
        start = imax - need + 1
    elif align_l == "center":
        start = imin + (total - need) // 2
    else:
        start = imin
    return start, need


def _load_image_pixels(path: str, width: int, height: int) -> List[Tuple[int, int, int]]:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise SystemExit(
            "Pillow is required to load/resize images. Install with: pip install Pillow"
        ) from exc

    img = Image.open(path).convert("RGB")
    img = img.resize((width, height), resample=Image.NEAREST)
    pixels: List[Tuple[int, int, int]] = []
    for y in range(height):
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            pixels.append((int(r), int(g), int(b)))
    return pixels



def main() -> None:
    image_file = os.getenv("GRID_IMAGE_FILE") or os.path.join(
        os.path.dirname(__file__), "python.png"
        # os.path.dirname(__file__), "1.jpg"
    )
    # grid_id = _parse_int(os.getenv("GRID_ID"), "135949329737827451")
    grid_id = _parse_int(os.getenv("GRID_ID"), None)
    width = _parse_int(os.getenv("GRID_IMAGE_WIDTH"), 25)
    height = _parse_int(os.getenv("GRID_IMAGE_HEIGHT"), 25)
    block_type = os.getenv("GRID_IMAGE_BLOCK_TYPE", "LargeBlockArmorBlock")
    plane = os.getenv("GRID_IMAGE_PLANE", "xy").lower()
    align_x = os.getenv("GRID_IMAGE_ALIGN_X", "min").lower()
    align_y = os.getenv("GRID_IMAGE_ALIGN_Y", "min").lower()
    off_x = _parse_int(os.getenv("GRID_IMAGE_OFFSET_X"), 0)
    off_y = _parse_int(os.getenv("GRID_IMAGE_OFFSET_Y"), 0)
    flip_y = _parse_bool(os.getenv("GRID_IMAGE_FLIP_Y", "1"), True)
    flip_x = _parse_bool(os.getenv("GRID_IMAGE_FLIP_X"), False)
    color_space = os.getenv("GRID_IMAGE_COLOR_SPACE", "auto").strip().lower()
    grey_eps = _parse_int(os.getenv("GRID_IMAGE_GREY_EPS"), 3)
    s_eps = _parse_float(os.getenv("GRID_IMAGE_S_EPS"), 0.02)
    white_min = _parse_int(os.getenv("GRID_IMAGE_WHITE_MIN"), 250)
    hue_zero_text = os.getenv("GRID_IMAGE_HUE_ZERO", "0.5")
    try:
        hue_zero = float(hue_zero_text)
    except Exception:
        hue_zero = 0.5
    swap_rb = _parse_bool(os.getenv("GRID_IMAGE_SWAP_RB"), False)

    # Batch and sound
    chunk_env = os.getenv("GRID_BLOCK_BATCH")
    try:
        batch_size = int(chunk_env) if chunk_env else 50
    except ValueError:
        batch_size = 50
    play_sound_env = os.getenv("GRID_BLOCK_PLAY_SOUND")
    play_sound: Optional[bool] = None
    if play_sound_env is not None:
        play_sound = _parse_bool(play_sound_env, False)

    # Load and resize the image, flatten to row-major list of RGB pixels
    pixels = _load_image_pixels(image_file, width, height)

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
        # Re-raise unexpected runtime errors to aid debugging
        raise
    try:
        # Gather candidate blocks and build 2D index
        blocks_xy = _filter_blocks_for_plane(grid.iter_blocks(), block_type=block_type, plane=plane)
        if not blocks_xy:
            raise SystemExit("No candidate blocks found with coordinates to paint on.")

        indexed, xs, ys, step_x, step_y = _index_blocks(blocks_xy)
        if not indexed:
            raise SystemExit("Failed to index grid blocks by coordinates.")

        # Remap to discrete indices present
        unique_ix = sorted({b.ix for b in indexed})
        unique_iy = sorted({b.iy for b in indexed})

        # Choose a window of width x height within available indices
        start_ix, win_w = _choose_window(unique_ix, width, align_x)
        start_iy, win_h = _choose_window(unique_iy, height, align_y)
        start_ix += off_x
        start_iy += off_y

        # Build a lookup from (ix, iy) to block id for quick access
        grid_map: Dict[Tuple[int, int], int] = {(b.ix, b.iy): b.block_id for b in indexed}

        # Prepare paint payload per batch
        per_block_payloads: List[Dict[str, Any]] = []

        for py in range(height):
            # Map image row index to grid iy
            if flip_y:
                iy = start_iy + (win_h - 1 - py)
            else:
                iy = start_iy + py
            for px in range(width):
                if flip_x:
                    ix = start_ix + (win_w - 1 - px)
                else:
                    ix = start_ix + px
                block_id = grid_map.get((ix, iy))
                if block_id is None:
                    continue  # skip missing positions
                r, g, b = pixels[py * width + px]
                if swap_rb:
                    r, b = b, r
                if color_space == "hsv":
                    # Convert to HSV with components in [0..1] as expected by the bridge
                    import colorsys

                    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
                    h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
                    # Calibrate hue baseline so that server mapping hMask = h - 0.5 lands at desired zero
                    h = (h + (0.5 - (hue_zero % 1.0))) % 1.0
                    # If near-grey or very low saturation, clamp to s=0; for near-white, force v=1
                    if (max(r, g, b) - min(r, g, b)) <= grey_eps or s < s_eps:
                        s = 0.0
                        if max(r, g, b) >= white_min:
                            v = 1.0
                    per_block_payloads.append({
                        "blockId": int(block_id),
                        "hsv": {"h": float(h), "s": float(s), "v": float(v)},
                    })
                elif color_space == "rgb":
                    # Default: explicit per-block RGB object to avoid parser quirks
                    per_block_payloads.append({
                        "blockId": int(block_id),
                        "rgb": {"r": int(r), "g": int(g), "b": int(b)},
                    })
                else:
                    # auto: if near-grey (including white), force HSV with s=0 (to avoid pink tint)
                    maxc = max(r, g, b)
                    minc = min(r, g, b)
                    if (maxc - minc) <= grey_eps:
                        v = maxc / 255.0
                        per_block_payloads.append({
                            "blockId": int(block_id),
                            "hsv": {"h": 0.0, "s": 0.0, "v": float(v)},
                        })
                    else:
                        per_block_payloads.append({
                            "blockId": int(block_id),
                            "rgb": {"r": int(r), "g": int(g), "b": int(b)},
                        })

        if not per_block_payloads:
            raise SystemExit("No blocks matched the selected image window to paint.")

        total_commands = 0
        for chunk in _chunked(per_block_payloads, batch_size):
            payload: Dict[str, Any] = {"blocks": list(chunk)}
            if play_sound is not None:
                payload["playSound"] = play_sound
            sent = grid.send_grid_command("paint_blocks", payload=payload)
            total_commands += sent

        print(
            f"Painted {len(per_block_payloads)} blocks in {total_commands} publish commands."
        )
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
