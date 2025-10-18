"""Reactor device implementation for Space Engineers grid control."""

from __future__ import annotations

from typing import Any, Dict

from sepy.base_device import DEVICE_TYPE_MAP
from sepy.devices.container_device import ContainerDevice


class ReactorDevice(ContainerDevice):
    """Expose telemetry and commands for reactor blocks."""

    device_type = "reactor"

    # ----------------------- Telemetry helpers -----------------------
    def current_output(self) -> float:
        return float((self.telemetry or {}).get("currentOutput", 0.0))

    def max_output(self) -> float:
        return float((self.telemetry or {}).get("maxOutput", 0.0))

    def output_ratio(self) -> float:
        return float((self.telemetry or {}).get("outputRatio", 0.0))

    def use_conveyor(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def functional_status(self) -> Dict[str, Any]:
        data = self.telemetry or {}
        return {
            "enabled": bool(data.get("enabled", False)),
            "isFunctional": bool(data.get("isFunctional", False)),
            "isWorking": bool(data.get("isWorking", False)),
        }

    # -------------------------- Commands ----------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({"cmd": "enable" if enabled else "disable"})

    def toggle_enabled(self) -> int:
        return self.send_command({"cmd": "toggle"})

    def set_use_conveyor(self, enabled: bool) -> int:
        return self.send_command({"cmd": "use_conveyor", "state": {"useConveyor": bool(enabled)}})


DEVICE_TYPE_MAP[ReactorDevice.device_type] = ReactorDevice
