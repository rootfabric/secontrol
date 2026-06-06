"""Beacon device helper for Space Engineers grid control."""

from __future__ import annotations

from typing import Any

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class BeaconDevice(BaseDevice):
    """Control helper for beacon blocks."""

    device_type = "beacon"

    @property
    def radius(self) -> float:
        """Current beacon broadcast radius in meters."""

        value = (self.telemetry or {}).get("radius", 0.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @property
    def hud_text(self) -> str:
        """Current beacon HUD label."""

        value = (self.telemetry or {}).get("hudText", "")
        return "" if value is None else str(value)

    def set_radius(self, radius: float) -> int:
        """Set beacon broadcast radius in meters."""

        radius = float(radius)
        if radius < 0.0:
            radius = 0.0
        return self.send_command({"cmd": "set_radius", "radius": radius})

    def set_hud_text(self, text: Any) -> int:
        """Set beacon HUD label. Empty string clears the label."""

        return self.send_command({"cmd": "set_text", "text": "" if text is None else str(text)})

    def configure(self, *, radius: float | None = None, hud_text: Any | None = None) -> int:
        """Set radius and/or HUD label. Returns total number of published commands."""

        sent = 0
        if radius is not None:
            sent += self.set_radius(radius)
        if hud_text is not None:
            sent += self.set_hud_text(hud_text)
        return sent


DEVICE_TYPE_MAP[BeaconDevice.device_type] = BeaconDevice
