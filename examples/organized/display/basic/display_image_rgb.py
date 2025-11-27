"""Example sending an image to LCD panels using RGB grid in Space Engineers."""

from __future__ import annotations

import pathlib
from typing import List

try:
    from PIL import Image, ImageDraw
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("Warning: Pillow not installed. Install with: pip install Pillow")
    print("Using fallback image generation without PIL.")

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, prepare_grid


if HAS_PILLOW:
    def create_simple_gradient_image(width: int = 64, height: int = 36) -> Image.Image:
        """Create a simple color gradient image for demonstration."""
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)

        for y in range(height):
            for x in range(width):
                # Create a gradient from red to blue
                r = int(255 * (x / width))
                g = int(255 * (y / height))
                b = int(255 * ((width - x) / width))
                draw.point((x, y), fill=(r, g, b))

        return img

    def image_to_rgb_rows(image: Image.Image, grid_w: int = 64, grid_h: int = 36) -> List[str]:
        """
        Convert PIL Image to RGB grid rows format.
        Returns list of strings in format '#RRGGBB,#RRGGBB,...'
        """
        # Convert to RGB and resize
        img = image.convert("RGB")
        img = img.resize((grid_w, grid_h), Image.LANCZOS)
        pixels = img.load()

        rows: List[str] = []
        for y in range(grid_h):
            row_colors = []
            for x in range(grid_w):
                r, g, b = pixels[x, y]
                row_colors.append(f"#{r:02X}{g:02X}{b:02X}")
            rows.append(",".join(row_colors))
        return rows
else:
    # Fallback implementation without PIL
    def create_simple_gradient_image(width: int = 64, height: int = 36) -> List[List[tuple[int, int, int]]]:
        """Create a simple color gradient as list of pixels (fallback without PIL)."""
        pixels = []
        for y in range(height):
            row = []
            for x in range(width):
                # Create a gradient from red to blue
                r = int(255 * (x / width))
                g = int(255 * (y / height))
                b = int(255 * ((width - x) / width))
                row.append((r, g, b))
            pixels.append(row)
        return pixels

    def image_to_rgb_rows(image_pixels: List[List[tuple[int, int, int]]], grid_w: int = 64, grid_h: int = 36) -> List[str]:
        """
        Convert pixel list to RGB grid rows format (fallback without PIL).
        """
        rows: List[str] = []
        for y in range(grid_h):
            row_colors = []
            for x in range(grid_w):
                r, g, b = image_pixels[y][x]
                row_colors.append(f"#{r:02X}{g:02X}{b:02X}")
            rows.append(",".join(row_colors))
        return rows


def main() -> None:


    # Try to load an image file, or create a gradient if not found
    image_file = pathlib.Path(__file__).parent / "C:\secontrol\examples\examples_direct_connect\mars_python.orig.png"
    if image_file.exists():
        print(f"Loading image from file: {image_file}")
        img = Image.open(image_file)
    else:
        print("Image file not found, creating a simple gradient image...")
        img = create_simple_gradient_image()

    # Convert to RGB grid
    grid_w, grid_h = 64, 36  # You can adjust these values
    rows = image_to_rgb_rows(img, grid_w=grid_w, grid_h=grid_h)
    print(f"Converted image to RGB grid: {grid_h} rows x {grid_w} columns")

    grid = prepare_grid("DroneBase")

    # Find display devices
    displays = grid.find_devices_by_type(DisplayDevice)
    if not displays:
        displays = grid.find_devices_by_type("display")  # Try alias

    if not displays:
        print("No display devices found on this grid.")
        return

    print(f"Found {len(displays)} display device(s):")
    for i, display in enumerate(displays, 1):
        print(f"  {i}. {display.name} (ID: {display.device_id})")

    print("\nSending RGB grid to displays...")

    for display in displays:
        print(f"Sending to {display.name}...")
        try:
            # Upload and render the RGB grid
            command_id = display.upload_rgb_grid(
                rows,
                grid_w=grid_w,
                grid_h=grid_h,
                cell=8,  # Pixel size
                mode="fit",  # fit, fill, stretch
                image_id="example_image"
            )
            print(f"  Upload command sent (ID: {command_id})")

            # Render it
            render_id = display.render_rgb_grid()
            print(f"  Render command sent (ID: {render_id})")

        except Exception as e:
            print(f"  Failed: {e}")
            continue

    print("\nImage sent to all displays!")
    print("To clear the image, you can use display.clear_rgb_grid()")


if __name__ == "__main__":
    main()
