"""Radio antenna device helper for Space Engineers grid control."""

from __future__ import annotations

from typing import Any

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class AntennaDevice(BaseDevice):
    """Control helper for radio antenna blocks."""

    device_type = "antenna"

    @property
    def radius(self) -> float:
        """Current antenna broadcast radius in meters."""

        value = (self.telemetry or {}).get("radius", (self.telemetry or {}).get("broadcastRadius", 0.0))
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @property
    def hud_text(self) -> str:
        """Current antenna HUD label."""

        value = (self.telemetry or {}).get("hudText", (self.telemetry or {}).get("antennaText", ""))
        return "" if value is None else str(value)

    @property
    def enable_broadcasting(self) -> bool | None:
        """Whether antenna broadcasting is enabled, if reported by telemetry."""

        telemetry = self.telemetry or {}
        if "enableBroadcasting" not in telemetry:
            return None
        return bool(telemetry.get("enableBroadcasting"))

    @property
    def is_broadcasting(self) -> bool | None:
        """Whether antenna is currently broadcasting, if reported by telemetry."""

        telemetry = self.telemetry or {}
        if "isBroadcasting" not in telemetry:
            return None
        return bool(telemetry.get("isBroadcasting"))

    def set_radius(self, radius: float) -> int:
        """Set antenna broadcast radius in meters."""

        radius = float(radius)
        if radius < 0.0:
            radius = 0.0
        return self.send_command({"cmd": "set_radius", "radius": radius})

    def set_hud_text(self, text: Any) -> int:
        """Set antenna HUD label. Empty string clears the label."""

        return self.send_command({"cmd": "set_text", "text": "" if text is None else str(text)})

    def set_broadcasting(self, enabled: bool) -> int:
        """Enable or disable antenna broadcasting."""

        return self.send_command({"cmd": "set_broadcasting", "enabled": bool(enabled)})

    def configure(
        self,
        *,
        radius: float | None = None,
        hud_text: Any | None = None,
        broadcasting: bool | None = None,
    ) -> int:
        """Set radius, HUD label and/or broadcasting flag."""

        sent = 0
        if radius is not None:
            sent += self.set_radius(radius)
        if hud_text is not None:
            sent += self.set_hud_text(hud_text)
        if broadcasting is not None:
            sent += self.set_broadcasting(broadcasting)
        return sent


DEVICE_TYPE_MAP[AntennaDevice.device_type] = AntennaDevice
DEVICE_TYPE_MAP["radio_antenna"] = AntennaDevice
