"""Wheel device implementation for Space Engineers grid control.

This module provides functionality to control suspension wheels on SE grids,
including setting propulsion and steering overrides, terminal properties, and telemetry.
"""

from __future__ import annotations

from typing import Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class WheelDevice(BaseDevice):
    device_type = "wheel"

    @staticmethod
    def _clamp_minus1_to_1(value: float) -> float:
        """Clamp value to range [-1.0, 1.0]."""
        return max(-1.0, min(1.0, float(value)))

    @staticmethod
    def _clamp_0_to_100(value: float) -> float:
        """Clamp value to range [0.0, 100.0]."""
        return max(0.0, min(100.0, float(value)))

    @staticmethod
    def _clamp_0_to_1000(value: float) -> float:
        """Clamp value to range [0.0, 1000.0]."""
        return max(0.0, min(1000.0, float(value)))

    @staticmethod
    def _clamp_0_to_pi_half(value: float) -> float:
        """Clamp value to range [0.0, π/2]."""
        import math
        return max(0.0, min(math.pi / 2, float(value)))

    # ----------------- Enable/Disable -----------------
    def enable(self) -> int:
        """Enable the wheel."""
        return self.send_command({"cmd": "enable"})

    def disable(self) -> int:
        """Disable the wheel."""
        return self.send_command({"cmd": "disable"})

    # ----------------- Propulsion/Steering Overrides -----------------
    def set_propulsion(self, propulsion: float) -> int:
        """Set propulsion override for the wheel (-1.0 to 1.0)."""
        clamped = self._clamp_minus1_to_1(propulsion)
        return self.send_command({
            "cmd": "propulsion",
            "state": {"propulsion": clamped}
        })

    def set_steering(self, steering: float) -> int:
        """Set steering override for the wheel (-1.0 to 1.0)."""
        clamped = self._clamp_minus1_to_1(steering)
        return self.send_command({
            "cmd": "steering",
            "state": {"steering": clamped}
        })

    def set_propulsion_and_steering(self, propulsion: float, steering: float) -> int:
        """Set both propulsion and steering overrides in one command."""
        propulsion_clamped = self._clamp_minus1_to_1(propulsion)
        steering_clamped = self._clamp_minus1_to_1(steering)
        return self.send_command({
            "cmd": "wheel_control",
            "state": {
                "propulsion": propulsion_clamped,
                "steering": steering_clamped
            }
        })

    # ----------------- Speed Limit -----------------
    def set_speed_limit(self, speed_kph: float) -> int:
        """Set speed limit in km/h (0.0 to 1000.0)."""
        clamped = self._clamp_0_to_1000(speed_kph)
        return self.send_command({
            "cmd": "speed",
            "state": {"speed": clamped}
        })

    # ----------------- Brake -----------------
    def set_brake(self, brake: bool) -> int:
        """Set brake state."""
        return self.send_command({
            "cmd": "brake",
            "state": {"brake": bool(brake)}
        })

    def brake_on(self) -> int:
        """Enable brake."""
        return self.set_brake(True)

    def brake_off(self) -> int:
        """Disable brake."""
        return self.set_brake(False)

    # ----------------- Propulsion/Steering Enabled -----------------
    def set_propulsion_enabled(self, enabled: bool) -> int:
        """Enable/disable propulsion."""
        return self.send_command({
            "cmd": "propulsion_enabled",
            "state": {"propulsion_enabled": bool(enabled)}
        })

    def set_steering_enabled(self, enabled: bool) -> int:
        """Enable/disable steering."""
        return self.send_command({
            "cmd": "steering_enabled",
            "state": {"steering_enabled": bool(enabled)}
        })

    # ----------------- Invert Steering/Propulsion -----------------
    def set_invert_steering(self, invert: bool) -> int:
        """Set steering inversion."""
        return self.send_command({
            "cmd": "invert_steer",
            "state": {"invert_steer": bool(invert)}
        })

    def set_invert_propulsion(self, invert: bool) -> int:
        """Set propulsion inversion."""
        return self.send_command({
            "cmd": "invert_propulsion",
            "state": {"invert_propulsion": bool(invert)}
        })

    # ----------------- Power/Strength/Friction -----------------
    def set_power(self, power: float) -> int:
        """Set power percentage (0.0 to 100.0)."""
        clamped = self._clamp_0_to_100(power)
        return self.send_command({
            "cmd": "power",
            "state": {"power": clamped}
        })

    def set_strength(self, strength: float) -> int:
        """Set strength percentage (0.0 to 100.0)."""
        clamped = self._clamp_0_to_100(strength)
        return self.send_command({
            "cmd": "strength",
            "state": {"strength": clamped}
        })

    def set_friction(self, friction: float) -> int:
        """Set friction percentage (0.0 to 100.0)."""
        clamped = self._clamp_0_to_100(friction)
        return self.send_command({
            "cmd": "friction",
            "state": {"friction": clamped}
        })

    # ----------------- Damping -----------------
    def set_damping(self, damping: float) -> int:
        """Set damping percentage (0.0 to 100.0)."""
        clamped = self._clamp_0_to_100(damping)
        return self.send_command({
            "cmd": "damping",
            "state": {"damping": clamped}
        })

    # ----------------- Height -----------------
    def set_height(self, height: float) -> int:
        """Set height offset in meters (-1.0 to 1.0)."""
        clamped = self._clamp_minus1_to_1(height)
        return self.send_command({
            "cmd": "height",
            "state": {"height": clamped}
        })

    # ----------------- Max Steer Angle -----------------
    def set_max_steer_angle(self, angle: float) -> int:
        """Set maximum steer angle in radians (0.0 to π/2)."""
        clamped = self._clamp_0_to_pi_half(angle)
        return self.send_command({
            "cmd": "maxsteer",
            "state": {"maxsteer": clamped}
        })

    # ----------------- Steer Speed/Return Speed -----------------
    def set_steer_speed(self, speed: float) -> int:
        """Set steering speed percentage (0.0 to 100.0)."""
        clamped = self._clamp_0_to_100(speed)
        return self.send_command({
            "cmd": "steerspeed",
            "state": {"steerspeed": clamped}
        })

    def set_steer_return_speed(self, speed: float) -> int:
        """Set steering return speed percentage (0.0 to 100.0)."""
        clamped = self._clamp_0_to_100(speed)
        return self.send_command({
            "cmd": "steerreturnspeed",
            "state": {"steerreturnspeed": clamped}
        })

    # ----------------- Normalize Propulsion Direction -----------------
    def normalize_propulsion_direction(self) -> int:
        """Normalize propulsion direction based on grid forward vector."""
        return self.send_command({"cmd": "normalize_direction"})

    # ----------------------- Telemetry helpers -----------------------
    def brake(self) -> bool:
        """Get current brake state."""
        return bool((self.telemetry or {}).get("brake", False))

    def propulsion_allowed(self) -> bool:
        """Get propulsion allowed state."""
        return bool((self.telemetry or {}).get("propulsionAllowed", True))

    def steering_allowed(self) -> bool:
        """Get steering allowed state."""
        return bool((self.telemetry or {}).get("steeringAllowed", True))

    def invert_propulsion(self) -> bool:
        """Get propulsion inversion state."""
        return bool((self.telemetry or {}).get("invertPropulsion", False))

    def invert_steering(self) -> bool:
        """Get steering inversion state."""
        return bool((self.telemetry or {}).get("invertSteer", False))

    def propulsion_override(self) -> float:
        """Get current propulsion override value."""
        return float((self.telemetry or {}).get("propulsionOverride", 0.0))

    def steering_override(self) -> float:
        """Get current steering override value."""
        return float((self.telemetry or {}).get("steeringOverride", 0.0))

    def power(self) -> float:
        """Get current power consumption."""
        return float((self.telemetry or {}).get("power", 0.0))

    def strength(self) -> float:
        """Get current strength value."""
        return float((self.telemetry or {}).get("strength", 0.0))

    def friction(self) -> float:
        """Get current friction value."""
        return float((self.telemetry or {}).get("friction", 0.0))

    def damping(self) -> float:
        """Get current damping value."""
        return float((self.telemetry or {}).get("damping", 0.0))

    def height(self) -> float:
        """Get current height offset."""
        return float((self.telemetry or {}).get("height", 0.0))

    def max_steer_angle(self) -> float:
        """Get maximum steer angle."""
        return float((self.telemetry or {}).get("maxSteerAngle", 0.0))

    def steer_angle(self) -> float:
        """Get current steer angle."""
        return float((self.telemetry or {}).get("steerAngle", 0.0))

    def suspension_travel(self) -> float:
        """Get suspension travel."""
        return float((self.telemetry or {}).get("suspensionTravel", 0.0))

    def speed_limit_kph(self) -> float:
        """Get speed limit in km/h."""
        return float((self.telemetry or {}).get("speedLimitKph", 0.0))

    def steer_speed(self) -> float:
        """Get steering speed."""
        return float((self.telemetry or {}).get("steerSpeed", -1.0))

    def steer_return_speed(self) -> float:
        """Get steering return speed."""
        return float((self.telemetry or {}).get("steerReturnSpeed", -1.0))

    def grid_speed_kph(self) -> float:
        """Get grid speed in km/h."""
        return float((self.telemetry or {}).get("gridSpeedKph", 0.0))


DEVICE_TYPE_MAP[WheelDevice.device_type] = WheelDevice
