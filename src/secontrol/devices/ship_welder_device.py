"""Ship welder device wrapper."""

from __future__ import annotations

from secontrol.base_device import DEVICE_TYPE_MAP
from .ship_tool_device import ShipToolDevice


class ShipWelderDevice(ShipToolDevice):
    """Inventory-enabled helper for ship welders."""

    device_type = "ship_welder"

    def welding_multiplier(self) -> float:
        return float((self.telemetry or {}).get("weldingMultiplier", 0.0))

    def weld_speed_multiplier(self) -> float:
        return float((self.telemetry or {}).get("weldSpeedMultiplier", 0.0))

    def help_others(self) -> bool:
        return bool((self.telemetry or {}).get("helpOthers", False))

    def show_area(self) -> bool:
        return bool((self.telemetry or {}).get("showArea", False))

    def set_help_others(self, enabled: bool) -> int:
        return self._send_boolean_command("help_others", "helpOthers", enabled)

    def set_show_area(self, enabled: bool) -> int:
        return self._send_boolean_command("show_area", "showArea", enabled)


DEVICE_TYPE_MAP[ShipWelderDevice.device_type] = ShipWelderDevice
