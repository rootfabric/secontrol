"""Cockpit device implementation for the Space Engineers Python API."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from sepy.base_device import DEVICE_TYPE_MAP
from sepy.devices.container_device import ContainerDevice


def _extract_vector(data: Optional[Dict[str, Any]], key: str) -> Dict[str, float]:
    vector = data.get(key) if isinstance(data, dict) else None
    if not isinstance(vector, dict):
        return {"x": 0.0, "y": 0.0, "z": 0.0, "length": 0.0}
    return {
        "x": float(vector.get("x", 0.0)),
        "y": float(vector.get("y", 0.0)),
        "z": float(vector.get("z", 0.0)),
        "length": float(vector.get("length") or 0.0),
    }


class CockpitDevice(ContainerDevice):
    """Wrapper around a cockpit block with inventory support."""

    device_type = "cockpit"

    # ----------------------- Telemetry helpers -----------------------
    def is_enabled(self) -> bool:
        return bool((self.telemetry or {}).get("enabled", False))

    def is_under_control(self) -> bool:
        return bool((self.telemetry or {}).get("isUnderControl", False))

    def has_pilot(self) -> bool:
        return bool((self.telemetry or {}).get("hasPilot", False))

    def pilot(self) -> Optional[Dict[str, Any]]:
        data = self.telemetry or {}
        if not data.get("hasPilot") and not data.get("pilotEntityId"):
            return None
        return {
            "entityId": data.get("pilotEntityId"),
            "identityId": data.get("pilotIdentityId"),
            "name": data.get("pilotName"),
            "oxygen": data.get("pilotOxygenLevel"),
            "energy": data.get("pilotEnergyLevel"),
            "hydrogen": data.get("pilotHydrogenLevel"),
        }

    def ship_mass(self) -> Dict[str, float]:
        telemetry = self.telemetry if isinstance(self.telemetry, dict) else {}
        mass = telemetry.get("shipMass") if isinstance(telemetry, dict) else {}
        if not isinstance(mass, dict):
            mass = {}
        return {
            "total": float(mass.get("total", 0.0)),
            "base": float(mass.get("base", 0.0)),
            "physical": float(mass.get("physical", 0.0)),
        }

    def linear_velocity(self) -> Dict[str, float]:
        return _extract_vector(self.telemetry, "linearVelocity")

    def angular_velocity(self) -> Dict[str, float]:
        return _extract_vector(self.telemetry, "angularVelocity")

    def gravity(self) -> Dict[str, Dict[str, float]]:
        telemetry = self.telemetry if isinstance(self.telemetry, dict) else {}
        gravity = telemetry.get("gravity") if isinstance(telemetry, dict) else {}
        if not isinstance(gravity, dict):
            gravity = {}
        return {
            "natural": _extract_vector(gravity, "natural"),
            "artificial": _extract_vector(gravity, "artificial"),
            "total": _extract_vector(gravity, "total"),
        }

    def inventories(self) -> Iterable[Dict[str, Any]]:
        data = self.telemetry or {}
        inv = data.get("inventories")
        if isinstance(inv, list):
            return [entry for entry in inv if isinstance(entry, dict)]
        return []

    # -------------------------- Commands ----------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({"cmd": "enable" if enabled else "disable"})

    def toggle_enabled(self) -> int:
        return self.send_command({"cmd": "toggle"})

    def set_handbrake(self, engaged: bool) -> int:
        return self.send_command({"cmd": "handbrake", "state": {"handBrake": bool(engaged)}})

    def set_dampeners(self, enabled: bool) -> int:
        return self.send_command({"cmd": "dampeners", "state": {"dampeners": bool(enabled)}})

    def set_control_thrusters(self, enabled: bool) -> int:
        return self.send_command({"cmd": "control_thrusters", "state": {"controlThrusters": bool(enabled)}})

    def set_control_wheels(self, enabled: bool) -> int:
        return self.send_command({"cmd": "control_wheels", "state": {"controlWheels": bool(enabled)}})

    def set_main_cockpit(self, is_main: bool = True) -> int:
        return self.send_command({"cmd": "set_main", "state": {"isMain": bool(is_main)}})


DEVICE_TYPE_MAP[CockpitDevice.device_type] = CockpitDevice
