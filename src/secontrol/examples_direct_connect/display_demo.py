# """
# Example: Sending text to an LCD/display panel in Space Engineers.
#
# This script demonstrates how to send text to a display block (like an LCD panel)
# using grid commands. Display panels show text in the game world and can be
# used for information displays, status reports, etc.
#
# The script can either:
# - Use DISPLAY_BLOCK_ID environment variable to target a specific block by ID
# - Auto-select the first available LCD panel on the grid if no ID is provided
#
# Requirements:
# - Redis bridge connection must be active
# - Set environment variables:
#   - REDIS_USERNAME: Your Space Engineers owner ID
#   - SE_PLAYER_ID (optional): Player ID to use (defaults to owner ID)
#   - SE_GRID_ID (optional): Specific grid ID to target
#   - DISPLAY_BLOCK_ID (optional): Specific block entity ID of the LCD panel
#   - DISPLAY_TEXT (optional): Text to display (default: "Hello from Python!")
#   - DISPLAY_APPEND (optional): Set to 1 to append text instead of replacing (default: 0)
#
# Usage:
#   python display_demo.py
#
# Commands supported:
# - set_text: Sets the text on the display (default)
# - display_text: Alias for set_text
# - write_text: Alias for set_text
# - clear_text: Clears all text (when DISPLAY_TEXT is empty)
# """
#
# from __future__ import annotations
#
# import os
#
# from secontrol.base_device import BlockInfo
# from secontrol.common import close, prepare_grid
#
#
# def find_display_blocks(grid) -> list[BlockInfo]:
#     """Find all LCD/text panel blocks on the grid."""
#     display_blocks = []
#     for block in grid.iter_blocks():
#         subtype_str = (block.subtype or "").lower()
#         type_str = (block.block_type or "").lower()
#
#         # Common LCD/text panel subtypes
#         if ("textpanel" in subtype_str or
#             "text_panel" in subtype_str or
#             "lcd" in subtype_str or
#             "display" in subtype_str or
#             subtype_str.startswith("large") and "text" in subtype_str or
#             subtype_str.startswith("small") and "text" in subtype_str):
#             display_blocks.append(block)
#     return display_blocks
#
#
# def select_display_block(display_blocks: list[BlockInfo]) -> BlockInfo | None:
#     """Select which display block to use."""
#     if not display_blocks:
#         print("No LCD/text panel blocks found on the grid.")
#         return None
#
#     if len(display_blocks) == 1:
#         block = display_blocks[0]
#         print(f"Using the only LCD panel found: {block.name} (ID: {block.block_id})")
#         return block
#
#     print(f"Found {len(display_blocks)} LCD panels:")
#     for i, block in enumerate(display_blocks, 1):
#         name = block.name or f"Block_{block.block_id}"
#         print(f"  {i}. {name} (ID: {block.block_id})")
#
#     # Auto-select the first one for automation
#     block = display_blocks[0]
#     print(f"Auto-selected first LCD panel: {block.name} (ID: {block.block_id})")
#     return block
#
#
# def main() -> None:
#     text = os.getenv("DISPLAY_TEXT", "Hello from Python!")
#     append = os.getenv("DISPLAY_APPEND", "0").strip().lower() in ("1", "true", "yes", "on")
#
#     print(f"Text to display: {repr(text)}")
#     print(f"Append mode: {append}")
#
#     try:
#         client, grid = prepare_grid("126722876679139690")
#     except RuntimeError as exc:
#         msg = str(exc)
#         if "No grids were found" in msg:
#             print(
#                 "No grids were found for the provided owner ID. "
#                 "Run: python -m secontrol.examples_direct_connect.list_grids"
#             )
#             raise SystemExit(2)
#         raise
#
#     try:
#         # Check if specific block ID is provided
#         block_id_env = os.getenv("DISPLAY_BLOCK_ID")
#         if block_id_env:
#             try:
#                 block_id = int(block_id_env)
#                 block = grid.get_block(block_id)
#                 if block is None:
#                     print(f"Block with ID {block_id} not found on the grid.")
#                     return
#                 print(f"Using specified block ID: {block_id} ({block.name or 'Unnamed'})")
#             except ValueError:
#                 print(f"Invalid DISPLAY_BLOCK_ID: {block_id_env}. Must be numeric.")
#                 return
#         else:
#             # Auto-find display blocks
#             display_blocks = find_display_blocks(grid)
#             block = select_display_block(display_blocks)
#             if block is None:
#                 return
#             block_id = block.block_id
#
#         # Determine command - clear if text is empty, otherwise set_text
#         if not text.strip():
#             command = "clear_text"
#             payload = {"blockId": block_id}
#             print(f"Sending '{command}' command to block {block_id} (clearing text)...")
#         else:
#             command = "set_text"
#             payload = {
#                 "blockId": block_id,
#                 "text": text,
#                 "append": append
#             }
#             action = "appending to" if append else "setting"
#             print(f"Sending '{command}' command to block {block_id} ({action} text)...")
#
#         # Send the command
#         sent = grid.send_grid_command(command, payload=payload)
#         if sent > 0:
#             print("Text command sent successfully!")
#             print(f"Command '{command}' published to {sent} channel(s)")
#         else:
#             print("Failed to send text command (no channels received it)")
#
#     finally:
#         close(client, grid)
#
#
# if __name__ == "__main__":
#     main()


"""Example using the DisplayDevice class with enhanced display functions."""

from __future__ import annotations

import datetime
import time

from secontrol.devices.display_device import DisplayDevice
from secontrol.common import resolve_owner_id, prepare_grid


def demo_display_functions(display: DisplayDevice):
    """Demonstrate various display functions."""
    print(f"Testing display: {display.name} (ID: {display.device_id})")

    # Set text with different modes
    print("1. Setting text...")
    display.set_text("Hello World!")
    time.sleep(1)

    # Append text
    print("2. Appending text...")
    display.set_text(" This is append!", append=True)
    time.sleep(1)

    # Set mode to text
    print("3. Setting mode to text...")
    display.set_mode("text")
    time.sleep(1)

    # Set style properties
    print("4. Setting style (font size, color, alignment)...")
    display.set_style(
        font_size=2.0,
        font_color="#FF0000",  # Red
        background_color="#000000",  # Black
        alignment="center",
        text_padding=0.1
    )
    time.sleep(1)

    # Set mode to images
    print("5. Setting mode to images...")
    display.set_mode("image")
    # Note: Actual images would require valid image IDs
    time.sleep(1)

    # Set back to text mode with program
    print("6. Setting mode to program...")
    display.set_mode("program")
    display.set_program("Square")  # Example program name
    time.sleep(1)

    # Clear text
    print("7. Clearing text...")
    display.clear_text()
    time.sleep(1)

    # Display telemetry info
    print("8. Reading telemetry...")
    enabled = display.is_enabled()
    text = display.get_text()
    mode = display.get_mode()
    font_size = display.get_font_size()
    font_color = display.get_font_color()
    alignment = display.get_alignment()
    script = display.get_script()

    print(f"   Enabled: {enabled}")
    print(f"   Text: {repr(text)}")
    print(f"   Mode: {mode}")
    print(f"   Font size: {font_size}")
    print(f"   Font color: {font_color}")
    print(f"   Alignment: {alignment}")
    print(f"   Script: {script}")

    print("9. Setting colorful greeting...")
    display.set_mode("text")
    display.set_style(
        font_size=1.5,
        font_color="#00FF00",  # Green
        background_color="#000080",  # Navy blue
        alignment="left"
    )
    display.set_text("", append=False)  # Clear first
    time.sleep(1)
    display.set_text("Display Demo Complete!", append=False)


def main() -> None:
    owner_id = resolve_owner_id()
    print(f"Owner ID: {owner_id}")

    client, grid = prepare_grid()

    try:
        # Find display devices
        displays = grid.find_devices_by_type(DisplayDevice)
        if not displays:
            displays = grid.find_devices_by_type("display")  # Try alias

        if not displays:
            displays = grid.find_devices_by_type("textpanel")  # Direct type

        if not displays:
            print("No display devices found. Available devices:")
            for dev in grid.devices.values():
                print(f"  - {dev.device_type}: {dev.name}")
            return

        print(f"Found {len(displays)} display device(s):")
        for i, disp in enumerate(displays, 1):
            print(f"  {i}. {disp.name} (ID: {disp.device_id})")

        # Test each display device
        for display in displays:
            demo_display_functions(display)
            print("--- Waiting before next display ---")
            time.sleep(3)

        print("Demo complete. Displays will show their final state.")

    except Exception as e:
        print(f"Error during demo: {e}")
        import traceback
        traceback.print_exc()

    finally:
        from secontrol.common import close
        close(client, grid)



if __name__ == "__main__":
    main()
