"""Remote control device implementation for Space Engineers grid control.

This module provides functionality to control remote control blocks on SE grids,
including enabling autopilot and navigating to GPS coordinates.
"""

from __future__ import annotations

from typing import Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class RemoteControlDevice(BaseDevice):
    device_type = "remote_control"

    def enable_autopilot(self) -> int:
        return self.send_command({
            "cmd": "remote_control",
            "state": "autopilot_enabled",
            "targetId": int(self.device_id),
            "targetName": self.name or "Remote Control",
        })

    def goto(self, gps: str, *, speed: Optional[float] = None, gps_name: str = "Target") -> int:
        formatted = self._format_state(gps, speed=speed, gps_name=gps_name)
        payload = {
            "cmd": "remote_goto",
            "state": formatted,
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    @staticmethod
    def _format_state(target: str, *, speed: Optional[float], gps_name: str) -> str:
        target = target.strip()
        if target.upper().startswith("GPS:"):
            coords = target if target.endswith(":") else f"{target}:"
        else:
            clean = target.replace(",", " ")
            pieces = [p for p in clean.split() if p]
            if len(pieces) != 3:
                raise ValueError("target must contain three coordinates or GPS:... string")
            x, y, z = (float(p) for p in pieces)
            coords = f"GPS:{gps_name}:{x:.6f}:{y:.6f}:{z:.6f}:"
        options: list[str] = []
        if speed is not None:
            options.append(f"speed={speed:.2f}")
        if options:
            return coords + ";" + ";".join(options)
        return coords


DEVICE_TYPE_MAP[RemoteControlDevice.device_type] = RemoteControlDevice
