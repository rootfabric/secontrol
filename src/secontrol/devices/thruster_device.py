"""Thruster device implementation for Space Engineers grid control.

This module provides functionality to control thrusters on SE grids,
including setting thrust overrides and enabling/disabling thrusters.
"""

from __future__ import annotations

from typing import Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class ThrusterDevice(BaseDevice):
    device_type = "thruster"

    def set_thrust(self, *, override: Optional[float] = None, enabled: Optional[bool] = None) -> int:
        sent = 0
        if enabled is not None:
            sent += self.send_command({"cmd": "enable" if enabled else "disable"})

        if override is not None:
            sent += self.send_command({"cmd": "override", "state": {"override": override}})

        if sent == 0:
            raise ValueError("set_thrust requires override or enabled")

        return sent

    def clear_override(self) -> int:
        return self.send_command({"cmd": "clear_override"})


DEVICE_TYPE_MAP[ThrusterDevice.device_type] = ThrusterDevice
