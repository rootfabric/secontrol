"""Large turret device wrapper with inventory support."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sepy.base_device import DEVICE_TYPE_MAP
from sepy.devices.container_device import ContainerDevice


class LargeTurretDevice(ContainerDevice):
    """Expose telemetry and commands for :interface:`IMyLargeTurretBase`."""

    device_type = "large_turret"

    # ----------------------- Telemetry helpers -----------------------
    def is_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("enabled", False))

    def ai_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("aiEnabled", False))

    def idle_rotation(self) -> bool:
        return bool((self.telemetry or {}).get("idleRotation", False))

    def range(self) -> float:
        return float((self.telemetry or {}).get("range", 0.0))

    def target(self) -> Optional[Dict[str, Any]]:
        data = self.telemetry or {}
        target = data.get("target")
        if isinstance(target, dict):
            return target
        return None

    # -------------------------- Commands ----------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({"cmd": "enable" if enabled else "disable"})

    def toggle_enabled(self) -> int:
        return self.send_command({"cmd": "toggle"})

    def set_idle_rotation(self, enabled: bool) -> int:
        return self.send_command({"cmd": "idle_rotation", "state": {"idleRotation": bool(enabled)}})

    def set_range(self, meters: float) -> int:
        return self.send_command({"cmd": "set_range", "state": {"range": float(meters)}})

    def shoot_once(self) -> int:
        return self.send_command({"cmd": "shoot_once"})

    def shoot_start(self) -> int:
        return self.send_command({"cmd": "shoot_on"})

    def shoot_stop(self) -> int:
        return self.send_command({"cmd": "shoot_off"})

    def reset_target(self) -> int:
        return self.send_command({"cmd": "reset_target"})


DEVICE_TYPE_MAP[LargeTurretDevice.device_type] = LargeTurretDevice
