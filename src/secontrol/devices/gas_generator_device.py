"""Gas/Oxygen generator wrapper with inventory helpers."""

from __future__ import annotations

from typing import Any, Dict

from secontrol.base_device import DEVICE_TYPE_MAP
from secontrol.devices.container_device import ContainerDevice


class GasGeneratorDevice(ContainerDevice):
    """Expose telemetry and commands for gas and oxygen generators."""

    device_type = "gas_generator"

    # ----------------------- Telemetry helpers -----------------------
    def fill_ratio(self) -> float:
        return float((self.telemetry or {}).get("filledRatio", 0.0))

    def production_capacity(self) -> float:
        return float((self.telemetry or {}).get("productionCapacity", 0.0))

    def current_output(self) -> float:
        return float((self.telemetry or {}).get("currentOutput", 0.0))

    def max_output(self) -> float:
        return float((self.telemetry or {}).get("maxOutput", 0.0))

    def use_conveyor(self) -> bool:
        return bool((self.telemetry or {}).get("useConveyorSystem", False))

    def auto_refill(self) -> bool:
        return bool((self.telemetry or {}).get("autoRefill", False))

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

    def set_auto_refill(self, enabled: bool) -> int:
        return self.send_command({"cmd": "auto_refill", "state": {"autoRefill": bool(enabled)}})

    def refill_bottles(self) -> int:
        return self.send_command({"cmd": "refill_bottles"})


DEVICE_TYPE_MAP[GasGeneratorDevice.device_type] = GasGeneratorDevice
