"""Ship drill device wrapper."""

from __future__ import annotations

from sepy.base_device import DEVICE_TYPE_MAP
from .ship_tool_device import ShipToolDevice


class ShipDrillDevice(ShipToolDevice):
    """Inventory-enabled helper for ship drills."""

    device_type = "ship_drill"

    def harvest_ratio(self) -> float:
        return float((self.telemetry or {}).get("harvestRatio", 0.0))

    def cut_out_depth(self) -> float:
        return float((self.telemetry or {}).get("cutOutDepth", 0.0))

    def drill_radius(self) -> float:
        return float((self.telemetry or {}).get("drillRadius", 0.0))

    def drill_power_consumption(self) -> float:
        return float((self.telemetry or {}).get("drillPowerConsumption", 0.0))

    def collect_stone(self) -> bool:
        return bool((self.telemetry or {}).get("collectStone", False))

    def set_collect_stone(self, enabled: bool) -> int:
        return self._send_boolean_command("collect_stone", "collectStone", enabled)

    def set_cut_depth(self, depth: float) -> int:
        return self._send_float_command("cut_depth", "cutDepth", depth)

    def set_drill_radius(self, radius: float) -> int:
        return self._send_float_command("drill_radius", "drillRadius", radius)


DEVICE_TYPE_MAP[ShipDrillDevice.device_type] = ShipDrillDevice
