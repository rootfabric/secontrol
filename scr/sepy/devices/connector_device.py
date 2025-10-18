"""Connector device implementation for Space Engineers grid control.

This module provides functionality to control ship connectors on SE grids,
including locking/unlocking and enabling/disabling connectors.
"""

from __future__ import annotations

from typing import Optional

from sepy.base_device import BaseDevice, DEVICE_TYPE_MAP


class ConnectorDevice(BaseDevice):
    device_type = "connector"

    def set_state(self, *, locked: Optional[bool] = None, enabled: Optional[bool] = None) -> int:
        state: dict[str, any] = {}
        if locked is not None:
            state["locked"] = bool(locked)
        if enabled is not None:
            state["enabled"] = bool(enabled)
        return self.send_command({
            "cmd": "connector_state",
            "state": state,
        })


DEVICE_TYPE_MAP[ConnectorDevice.device_type] = ConnectorDevice