"""Ship grinder device wrapper."""

from __future__ import annotations

from sepy.base_device import DEVICE_TYPE_MAP
from .ship_tool_device import ShipToolDevice


class ShipGrinderDevice(ShipToolDevice):
    """Inventory-enabled helper for ship grinders."""

    device_type = "ship_grinder"

    def grinding_multiplier(self) -> float:
        return float((self.telemetry or {}).get("grindingMultiplier", 0.0))

    def grind_speed_multiplier(self) -> float:
        return float((self.telemetry or {}).get("grindSpeedMultiplier", 0.0))

    def help_others(self) -> bool:
        return bool((self.telemetry or {}).get("helpOthers", False))

    def set_help_others(self, enabled: bool) -> int:
        return self._send_boolean_command("help_others", "helpOthers", enabled)


DEVICE_TYPE_MAP[ShipGrinderDevice.device_type] = ShipGrinderDevice
