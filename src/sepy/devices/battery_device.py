"""Battery device implementation for Space Engineers grid control."""

from __future__ import annotations

from sepy.base_device import BaseDevice, DEVICE_TYPE_MAP


class BatteryDevice(BaseDevice):
    """Control helper for battery blocks."""

    device_type = "battery"

    def set_mode(self, mode: str) -> int:
        if mode not in {"auto", "recharge", "discharge"}:
            raise ValueError("mode must be 'auto', 'recharge' or 'discharge'")
        return self.send_command({
            "cmd": "battery_mode",
            "state": {"mode": mode},
        })


DEVICE_TYPE_MAP[BatteryDevice.device_type] = BatteryDevice
