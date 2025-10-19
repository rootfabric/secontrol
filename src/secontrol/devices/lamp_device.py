"""Lamp device implementation for Space Engineers grid control."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


def _normalize_color_value(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive branch
        raise ValueError("color components must be numeric") from exc

    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        if numeric <= 100.0:
            numeric /= 100.0
        else:
            numeric /= 255.0
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


def _components_from_sequence(values: Sequence[Any]) -> list[float]:
    items = list(values)
    if len(items) != 3:
        raise ValueError("color must contain exactly three components")
    return [_normalize_color_value(component) for component in items]


def _components_from_mapping(values: Mapping[str, Any]) -> list[float]:
    r = values.get("r", values.get("red"))
    g = values.get("g", values.get("green"))
    b = values.get("b", values.get("blue"))
    if r is None or g is None or b is None:
        raise ValueError("color mapping must provide r/g/b components")
    return _components_from_sequence((r, g, b))


def _parse_color(value: Any) -> list[float]:
    if isinstance(value, Mapping):
        return _components_from_mapping(value)
    if isinstance(value, str):
        parts = [part for part in re.split(r"[;,\s]+", value.strip()) if part]
        return _components_from_sequence(parts)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return _components_from_sequence(value)
    raise TypeError("color must be provided as a mapping, sequence or string")


class LampDevice(BaseDevice):
    """High level helper around the Space Engineers lighting blocks."""

    device_type = "lamp"

    def handle_telemetry(self, telemetry: dict[str, Any]) -> None:  # noqa: D401 - simple assignment
        """Store the latest telemetry snapshot."""
        self.telemetry = telemetry

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------
    def enable(self) -> int:
        """Enable the lamp."""

        return self.send_command({"cmd": "enable"})

    def disable(self) -> int:
        """Disable the lamp."""

        return self.send_command({"cmd": "disable"})

    def set_enabled(self, enabled: bool) -> int:
        """Enable or disable the lamp depending on ``enabled``."""

        return self.enable() if enabled else self.disable()

    def set_color(
        self,
        *,
        rgb: Sequence[Any] | Mapping[str, Any] | str | None = None,
        color: Sequence[Any] | Mapping[str, Any] | str | None = None,
        red: Any | None = None,
        green: Any | None = None,
        blue: Any | None = None,
    ) -> int:
        """Change the lamp color using RGB values in the ``0.0`` – ``1.0`` range."""

        color_source = color if color is not None else rgb
        if color_source is not None:
            components = _parse_color(color_source)
        elif red is not None and green is not None and blue is not None:
            components = _components_from_sequence((red, green, blue))
        else:
            raise ValueError("provide rgb/color sequence or explicit red/green/blue components")

        return self.send_command({
            "cmd": "color",
            "color": components,
        })

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool | None:
        """Return the lamp enabled state from telemetry, if known."""

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

    def intensity(self) -> float | None:
        """Return the last reported intensity value."""

        return self._get_float_telemetry("intensity")

    def radius(self) -> float | None:
        """Return the last reported radius value."""

        return self._get_float_telemetry("radius")

    def color_rgb(self) -> tuple[float, float, float] | None:
        """Return the current lamp color as an RGB triplet, if available."""

        if not self.telemetry:
            return None
        raw_color = self.telemetry.get("color")
        if isinstance(raw_color, (list, tuple)) and len(raw_color) >= 3:
            try:
                return (float(raw_color[0]), float(raw_color[1]), float(raw_color[2]))
            except (TypeError, ValueError):  # pragma: no cover - defensive branch
                return None
        return None

    # ------------------------------------------------------------------
    def _get_float_telemetry(self, key: str) -> float | None:
        if not self.telemetry:
            return None
        value = self.telemetry.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive branch
            return None


DEVICE_TYPE_MAP[LampDevice.device_type] = LampDevice

__all__ = ["LampDevice"]
