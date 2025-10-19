"""Thruster device implementation for Space Engineers grid control.

This module provides functionality to control thrusters on SE grids,
including setting thrust overrides and enabling/disabling thrusters.
"""

from __future__ import annotations

from typing import Optional

from sepy.base_device import BaseDevice, DEVICE_TYPE_MAP


class ThrusterDevice(BaseDevice):
    device_type = "thruster"

    def set_thrust(self, *, override: Optional[float] = None, enabled: Optional[bool] = None) -> int:
        payload: dict[str, any] = {
            "cmd": "thruster_control",
            "state": {},
        }
        if override is not None:
            payload["state"]["override"] = override
        if enabled is not None:
            payload["state"]["enabled"] = bool(enabled)
        return self.send_command(payload)


DEVICE_TYPE_MAP[ThrusterDevice.device_type] = ThrusterDevice
