"""Shared helpers for inventory-enabled ship tools."""

from __future__ import annotations

from typing import Any, Dict

from .container_device import ContainerDevice


class ShipToolDevice(ContainerDevice):
    """Base class with convenience helpers for ship tools."""

    device_type = "ship_tool"

    # ----------------------- Telemetry helpers -----------------------
    def use_conveyor(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def required_power_input(self) -> float:
        return float((self.telemetry or {}).get("requiredPowerInput", 0.0))

    def power_consumption_multiplier(self) -> float:
        return float((self.telemetry or {}).get("powerConsumptionMultiplier", 0.0))

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

    # ------------------------- Utilities ----------------------------
    def _send_boolean_command(self, cmd: str, key: str, value: bool) -> int:
        return self.send_command({"cmd": cmd, "state": {key: bool(value)}})

    def _send_float_command(self, cmd: str, key: str, value: float) -> int:
        return self.send_command({"cmd": cmd, "state": {key: float(value)}})
