"""Battery device implementation for Space Engineers grid control."""

from __future__ import annotations

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class BatteryDevice(BaseDevice):
    """Control helper for battery blocks."""

    device_type = "battery"

    def set_mode(self, mode: str) -> int:
        mode = mode.strip().lower()
        if mode not in {"auto", "recharge", "discharge", "semiauto", "semi-auto", "semi"}:
            raise ValueError("mode must be 'auto', 'recharge', 'discharge' or 'semiauto'")
        if mode == "semi-auto" or mode == "semi":
            mode = "semiauto"
        return self.send_command({
            "cmd": "set_mode",
            "state": {"mode": mode},
        })


DEVICE_TYPE_MAP[BatteryDevice.device_type] = BatteryDevice
