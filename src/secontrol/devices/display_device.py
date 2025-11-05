"""Display device implementation for Space Engineers text panels (LCD, etc.)."""

from __future__ import annotations

from typing import Any

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP

# for image need research
# https://seimage.lucasteske.dev/

class DisplayDevice(BaseDevice):
    """High level helper around the Space Engineers text panels (LCD, displays)."""

    device_type = "textpanel"

    def handle_telemetry(self, telemetry: dict[str, Any]) -> None:  # noqa: D401 - simple assignment
        """Store the latest telemetry snapshot."""
        self.telemetry = telemetry

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------
    def set_text(self, text: str, append: bool = False) -> int:
        """Set the display text. If append is True, append to existing text."""
        return self.send_command({
            "cmd": "set_text",
            "text": text,
            "append": append,
        })

    def write_text(self, text: str, append: bool = False) -> int:
        """Alias for set_text (write_text for compatibility)."""
        return self.set_text(text, append)

    def display_text(self, text: str, append: bool = False) -> int:
        """Alias for set_text (display_text for compatibility)."""
        return self.set_text(text, append)

    def clear_text(self) -> int:
        """Clear all text from the display."""
        return self.send_command({"cmd": "clear_text"})

    def set_mode(self, mode: str) -> int:
        """Set the display mode: none/empty, text, image/images, program/script."""
        return self.send_command({
            "cmd": "set_mode",
            "mode": mode,
        })

    def set_style(
        self,
        *,
        font_size: float | None = None,
        font_color: str | list[float] | dict[str, float] | tuple[float, ...] | None = None,
        background_color: str | list[float] | dict[str, float] | tuple[float, ...] | None = None,
        alignment: str | None = None,
        text_padding: float | None = None,
    ) -> int:
        """Set display style properties."""
        payload = {"cmd": "set_style"}
        if font_size is not None:
            payload["fontSize"] = font_size
        if font_color is not None:
            payload["fontColor"] = self._normalize_color(font_color)
        if background_color is not None:
            payload["backgroundColor"] = self._normalize_color(background_color)
        if alignment is not None:
            payload["alignment"] = alignment.lower()
        if text_padding is not None:
            payload["textPadding"] = text_padding
        return self.send_command(payload)

    def set_images(self, images: list[str] | str | None = None, *, clear_first: bool = True) -> int:
        """Set display images from a list or single image string."""
        payload = {"cmd": "set_image"}
        if images is not None:
            if isinstance(images, list):
                payload["images"] = images
            else:
                payload["image"] = str(images)
        return self.send_command(payload)

    def set_program(self, program: str) -> int:
        """Set the display program/script."""
        return self.send_command({
            "cmd": "set_program",
            "script": program,
        })

    def upload_image(
        self,
        image_data: str,
        *,
        width: int | None = None,
        height: int | None = None,
        mode: str | None = None,
        image_id: str | None = None,
    ) -> int:
        """Upload a custom image (base64 encoded) to the display."""
        payload = {"cmd": "upload_image", "imageBase64": image_data}
        if width is not None:
            payload["width"] = width
        if height is not None:
            payload["height"] = height
        if mode is not None:
            payload["mode"] = mode.lower()
        if image_id is not None:
            payload["id"] = image_id
        return self.send_command(payload)

    def clear_uploaded_image(self) -> int:
        """Clear any uploaded custom image from the display."""
        return self.send_command({"cmd": "clear_upload"})

    def _normalize_color(self, color: str | list[float] | dict[str, float] | tuple[float, ...]) -> list[float]:
        """Normalize color to RGB array."""
        if isinstance(color, str):
            if color.startswith("#"):
                # Hex color
                hex_val = color.lstrip("#")
                if len(hex_val) == 6:
                    return [
                        int(hex_val[0:2], 16) / 255.0,
                        int(hex_val[2:4], 16) / 255.0,
                        int(hex_val[4:6], 16) / 255.0,
                    ]
            elif color.startswith("0x"):
                # Hex color
                hex_val = color[2:]
                if len(hex_val) == 6:
                    return [
                        int(hex_val[0:2], 16) / 255.0,
                        int(hex_val[2:4], 16) / 255.0,
                        int(hex_val[4:6], 16) / 255.0,
                    ]
            # Try as comma-separated values
            try:
                parts = [float(x.strip()) for x in color.replace(";", ",").split(",")]
                if len(parts) >= 3:
                    r, g, b = parts[0], parts[1], parts[2]
                    # Normalize if needed
                    if max(r, g, b) <= 1.0:
                        r, g, b = r * 255.0, g * 255.0, b * 255.0
                    return [r / 255.0, g / 255.0, b / 255.0]
            except ValueError:
                pass
        elif isinstance(color, (list, tuple)) and len(color) >= 3:
            r, g, b = color[0], color[1], color[2]
            # Normalize if needed
            if max(r, g, b) <= 1.0:
                r, g, b = r * 255.0, g * 255.0, b * 255.0
            return [r / 255.0, g / 255.0, b / 255.0]
        elif isinstance(color, dict):
            r = color.get("r", color.get("red", 255))
            g = color.get("g", color.get("green", 255))
            b = color.get("b", color.get("blue", 255))
            # Normalize if needed
            if max(r, g, b) <= 1.0:
                r, g, b = r * 255.0, g * 255.0, b * 255.0
            return [r / 255.0, g / 255.0, b / 255.0]
        # Default to white
        return [1.0, 1.0, 1.0]

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool | None:
        """Return the panel enabled state from telemetry, if known."""
        if not self.telemetry:
            return None
        value = self.telemetry.get("enabled")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        return None

    def get_text(self) -> str | None:
        """Return the current text from telemetry, if known."""
        if not self.telemetry:
            return None
        return self.telemetry.get("text")

    def get_length(self) -> int | None:
        """Return the length of the text from telemetry, if known."""
        if not self.telemetry:
            return None
        length = self.telemetry.get("length")
        if length is not None:
            try:
                return int(length)
            except (TypeError, ValueError):
                pass
        text = self.get_text()
        if text is not None:
            return len(text)
        return None

    def get_mode(self) -> str | None:
        """Return the display mode from telemetry: none, text, image, program."""
        if not self.telemetry:
            return None
        return self.telemetry.get("mode")

    def get_font_size(self) -> float | None:
        """Return the font size from telemetry."""
        if not self.telemetry:
            return None
        return self.telemetry.get("fontSize")

    def get_font_color(self) -> list[float] | None:
        """Return the font color as RGB list from telemetry."""
        if not self.telemetry:
            return None
        return self.telemetry.get("fontColor")

    def get_background_color(self) -> list[float] | None:
        """Return the background color as RGB list from telemetry."""
        if not self.telemetry:
            return None
        return self.telemetry.get("backgroundColor")

    def get_alignment(self) -> str | None:
        """Return the text alignment from telemetry: left, center, right."""
        if not self.telemetry:
            return None
        return self.telemetry.get("alignment")

    def get_text_padding(self) -> float | None:
        """Return the text padding from telemetry."""
        if not self.telemetry:
            return None
        return self.telemetry.get("textPadding")

    def get_script(self) -> str | None:
        """Return the script/program name from telemetry."""
        if not self.telemetry:
            return None
        return self.telemetry.get("script")

    def get_images_signature(self) -> str | None:
        """Return the images signature from telemetry."""
        if not self.telemetry:
            return None
        return self.telemetry.get("imagesSignature")

    def upload_rgb_grid(self, rows: list[str], *, grid_w: int, grid_h: int,
                        cell: int = 8, mode: str = "fit", image_id: str | None = None) -> int:
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
        return self.send_command(payload)

    def render_rgb_grid(self) -> int:
        return self.send_command({"cmd": "render_rgb_grid"})

    def clear_rgb_grid(self) -> int:
        return self.send_command({"cmd": "clear_rgb_grid"})


DEVICE_TYPE_MAP[DisplayDevice.device_type] = DisplayDevice

__all__ = ["DisplayDevice"]
