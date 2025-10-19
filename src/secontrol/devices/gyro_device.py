"""Gyroscopic control device implementation for Space Engineers grid control.

This module provides functionality to control gyroscopes on SE grids,
including setting overrides for pitch, yaw, and roll rotation.
"""

from __future__ import annotations

from typing import Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class GyroDevice(BaseDevice):
    device_type = "gyro"

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(-1.0, min(1.0, float(x)))

    def set_override(self, *, pitch: float, yaw: float, roll: float, power: Optional[float] = None) -> int:
        p = self._clamp01(pitch)
        y = self._clamp01(yaw)
        r = self._clamp01(roll)

        csv = f"{p:.6f},{y:.6f},{r:.6f}"
        kv  = f"pitch={p:.6f};yaw={y:.6f};roll={r:.6f}"
        obj = {"pitch": p, "yaw": y, "roll": r}
        if power is not None:
            # если где-то ожидают power — отправим его тоже
            obj["power"] = float(power)

        sent = 0

        # A) Your current C# (если там строка с CSV — это оно)
        sent += self.send_command({"cmd": "override", "state": csv})

        return sent

    def enable(self) -> int:
        return self.send_command({"cmd": "enable", "state": ""})

    def disable(self) -> int:
        return self.send_command({"cmd": "disable", "state": ""})

    def clear_override(self) -> int:
        return self.send_command({"cmd": "clear_override", "state": ""})


DEVICE_TYPE_MAP[GyroDevice.device_type] = GyroDevice
