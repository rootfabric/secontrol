from __future__ import annotations

import pathlib
from typing import List
from PIL import Image

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, prepare_grid


def image_to_rgb_rows(path: str | pathlib.Path, grid_w: int = 64, grid_h: int = 36) -> List[str]:
    """
    Загружает изображение, приводит к RGB, ресайзит до grid_w x grid_h (Lanczos),
    возвращает список строк формата '#RRGGBB,#RRGGBB,...' длиной grid_w, всего grid_h строк.
    """
    path = pathlib.Path(path)
    with Image.open(path) as im:
        im = im.convert("RGB")
        im = im.resize((grid_w, grid_h), Image.LANCZOS)
        pixels = im.load()

        rows: List[str] = []
        for y in range(grid_h):
            row_colors = []
            for x in range(grid_w):
                r, g, b = pixels[x, y]
                row_colors.append(f"#{r:02X}{g:02X}{b:02X}")
            rows.append(",".join(row_colors))
        return rows


def send_rgb_grid(display: DisplayDevice, rows: list[str], *, grid_w: int, grid_h: int,
                  cell: int = 8, mode: str = "fit", image_id: str | None = None) -> int:
    """
    Шлёт на панель команду upload_rgb_grid.
    """
    payload = {
        "cmd": "upload_rgb_grid",
        "gridW": grid_w,
        "gridH": grid_h,
        "cell": cell,
        "mode": mode,
        "rows": rows,
    }
    if image_id:
        payload["id"] = image_id
    return display.send_command(payload)


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    # путь к картинке
    image_file = pathlib.Path(__file__).parent / "python.png"
    if not image_file.exists():
        print(f"Image not found: {image_file}")
        return

    grid_w, grid_h = 64, 36
    rows = image_to_rgb_rows(image_file, grid_w=grid_w, grid_h=grid_h)
    print(f"Prepared rows: {len(rows)} x {grid_w}")

    grid = prepare_grid()

    displays = grid.find_devices_by_type(DisplayDevice) or grid.find_devices_by_type("display")
    if not displays:
        print("No display devices found on this grid.")
        return

    for d in displays:
        print(f"Render to: {d.name} (ID: {d.device_id})")
        cmd_id = send_rgb_grid(d, rows, grid_w=grid_w, grid_h=grid_h, cell=8, mode="fit", image_id="demo_python")
        print(f"  command id: {cmd_id}")

    print("Done. If needed, you can re-render via {'cmd':'render_rgb_grid'}")


if __name__ == "__main__":
    main()
