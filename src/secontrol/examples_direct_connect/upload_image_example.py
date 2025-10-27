"""Example uploading custom images to LCD panels in Space Engineers."""

from __future__ import annotations

import base64
import pathlib
import time

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, prepare_grid


def load_image_as_base64(image_path: str | pathlib.Path) -> str:
    """Load an image file and return it as base64 encoded string."""
    path = pathlib.Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    with path.open("rb") as f:
        image_data = f.read()

    # Encode to base64
    encoded = base64.b64encode(image_data).decode('utf-8')
    return encoded


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    # Load example image (using one from the examples directory)
    image_file = pathlib.Path(__file__).parent / "python.png"
    if not image_file.exists():
        print(f"Example image not found: {image_file}")
        print("Please place an image file (e.g., python.png) in the examples directory.")
        return

    print(f"Loading image: {image_file}")
    try:
        base64_data = load_image_as_base64(image_file)
        print(f"Image loaded, base64 length: {len(base64_data)} characters")
    except Exception as e:
        print(f"Failed to load image: {e}")
        return

    client, grid = prepare_grid()

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

    print("\nUploading image to displays...")

    for display in displays:
        print(f"Uploading to {display.name}...")
        try:
            # Upload the image - this will automatically set mode to script with OutenemyImageDisplay
            command_id = display.upload_image(
                base64_data,
                width=None,  # Let the script determine size or use image natural size
                height=None,
                mode="fit",  # Options: fit, fill, stretch
                image_id=None  # Will generate SHA1 hash if not provided
            )
            print(f"  Command sent (ID: {command_id})")
        except Exception as e:
            print(f"  Failed to upload: {e}")
            continue

        # Wait a moment for the command to be processed
        time.sleep(0.5)

    print("\nImage uploaded to all displays!")
    print("You can now clear the uploaded image using display.clear_uploaded_image()")

    # Optional: Demonstrate clearing (commented out to keep the image visible)
    # print("\nClearing uploaded images in 5 seconds...")
    # time.sleep(5)
    # for display in displays:
    #     print(f"Clearing {display.name}...")
    #     try:
    #         command_id = display.clear_uploaded_image()
    #         print(f"  Clear sent (ID: {command_id})")
    #     except Exception as e:
    #         print(f"  Failed to clear: {e}")


if __name__ == "__main__":
    main()
