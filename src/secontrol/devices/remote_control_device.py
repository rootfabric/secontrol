from __future__ import annotations

from typing import Any, Optional, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


Vector3 = Tuple[float, float, float]


class RemoteControlDevice(BaseDevice):
    device_type = "remote_control"
    supports_enabled = False

    def enable(self) -> int:
        """Compatibility alias: enable Remote Control autopilot, not block power."""
        return self.autopilot_enable()

    def disable(self) -> int:
        """Compatibility alias: disable Remote Control autopilot, not block power."""
        return self.autopilot_disable()

    def set_enabled(self, enabled: bool) -> int:
        return self.set_autopilot(bool(enabled))

    def toggle_enabled(self) -> int:
        return self.set_autopilot(not self.autopilot_enabled())

    def block_enable(self) -> int:
        raise NotImplementedError("Remote Control does not expose a terminal On/Off switch")

    def block_disable(self) -> int:
        raise NotImplementedError("Remote Control does not expose a terminal On/Off switch")

    def is_block_enabled(self) -> bool:
        return True

    def autopilot_enable(self) -> int:
        return self.send_command(self._remote_control_payload("autopilot_enable"))

    def autopilot_disable(self) -> int:
        return self.send_command(self._remote_control_payload("autopilot_disable"))

    def set_autopilot(self, enabled: bool) -> int:
        return self.autopilot_enable() if bool(enabled) else self.autopilot_disable()

    start_autopilot = autopilot_enable
    stop_autopilot = autopilot_disable

    def set_mode(self, mode: str = "oneway") -> int:
        mode = str(mode).strip().lower()
        if mode not in {"patrol", "circle", "oneway"}:
            raise ValueError("mode must be 'patrol', 'circle' or 'oneway'")
        return self.send_command(self._command_payload("set_mode", mode=mode))

    def gyro_control_on(self) -> int:
        return self.send_command(self._remote_control_payload("gyro_control_on"))

    def gyro_control_off(self) -> int:
        return self.send_command(self._remote_control_payload("gyro_control_off"))

    def handbrake_on(self) -> int:
        return self.send_command(self._remote_control_payload("handbrake_on"))

    def handbrake_off(self) -> int:
        return self.send_command(self._remote_control_payload("handbrake_off"))

    def dampeners_on(self) -> int:
        return self.send_command(self._remote_control_payload("dampeners_on"))

    def dampeners_off(self) -> int:
        return self.send_command(self._remote_control_payload("dampeners_off"))

    def thrusters_on(self) -> int:
        return self.send_command(self._remote_control_payload("thrusters_on"))

    def thrusters_off(self) -> int:
        return self.send_command(self._remote_control_payload("thrusters_off"))

    def wheels_on(self) -> int:
        return self.send_command(self._remote_control_payload("wheels_on"))

    def wheels_off(self) -> int:
        return self.send_command(self._remote_control_payload("wheels_off"))

    def planetary_autopilot_on(self) -> int:
        return self.send_command(self._remote_control_payload("planetary_autopilot_on"))

    def planetary_autopilot_off(self) -> int:
        return self.send_command(self._remote_control_payload("planetary_autopilot_off"))

    def goto(self, gps: str, *, speed: Optional[float] = None, gps_name: str = "Target", dock: bool = False) -> int:
        formatted = self._format_state(gps, speed=speed, gps_name=gps_name, dock=dock)
        return self.send_command(self._command_payload("remote_goto", state=formatted))

    def set_collision_avoidance(self, enabled: bool) -> int:
        return self.send_command(self._command_payload("collision_avoidance", state={"enabled": bool(enabled)}, enabled=bool(enabled)))

    def set_precision_mode(self, enabled: bool) -> int:
        return self.send_command(self._command_payload("precision_mode", state={"enabled": bool(enabled)}, enabled=bool(enabled)))

    def is_functional(self) -> bool:
        return True

    def is_working(self) -> bool:
        return True

    def autopilot_enabled(self) -> bool:
        telemetry = self.telemetry or {}
        for key in ("autopilotEnabled", "autoPilotEnabled", "autopilot"):
            if key in telemetry:
                return self._as_bool(telemetry.get(key))
        return False

    def ensure_ready_for_autopilot(self, *, timeout: float = 3.0, enable_thrusters: bool = True, enable_gyros: bool = True, enable_dampeners: bool = True) -> bool:
        if enable_thrusters:
            self.thrusters_on()
        if enable_gyros:
            self.gyro_control_on()
        if enable_dampeners:
            self.dampeners_on()
        try:
            self.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
        except Exception:
            pass
        return True

    def _command_payload(self, cmd: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"cmd": cmd, "targetId": int(self.device_id), "targetName": self.name or "Remote Control"}
        payload.update(extra)
        return payload

    def _remote_control_payload(self, state: str) -> dict[str, Any]:
        return self._command_payload("remote_control", state=state)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}
        return bool(value)

    @staticmethod
    def _parse_vec3_from_obj(obj: object) -> Optional[Vector3]:
        if isinstance(obj, dict):
            try:
                return (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)), float(obj.get("z", 0.0)))
            except (TypeError, ValueError):
                return None
        if isinstance(obj, (list, tuple)) and len(obj) == 3:
            try:
                return (float(obj[0]), float(obj[1]), float(obj[2]))
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _parse_vec3_from_string(text: object) -> Optional[Vector3]:
        if not isinstance(text, str):
            return None
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            return None
        try:
            return (float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError:
            return None

    @staticmethod
    def _cross(a: Vector3, b: Vector3) -> Vector3:
        return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

    def get_orientation_vectors_world(self) -> Tuple[Vector3, Vector3, Vector3]:
        telemetry = self.telemetry or {}
        forward: Optional[Vector3] = None
        up: Optional[Vector3] = None
        right: Optional[Vector3] = None
        orientation = telemetry.get("orientation")
        if isinstance(orientation, dict):
            forward = self._parse_vec3_from_obj(orientation.get("forward"))
            up = self._parse_vec3_from_obj(orientation.get("up"))
            right = self._parse_vec3_from_obj(orientation.get("right"))
            if right is None:
                left = self._parse_vec3_from_obj(orientation.get("left"))
                if left is not None:
                    right = (-left[0], -left[1], -left[2])
        if forward is None:
            forward = self._parse_vec3_from_string(telemetry.get("forward"))
        if up is None:
            up = self._parse_vec3_from_string(telemetry.get("up"))
        if forward is None:
            forward = (0.0, 0.0, 1.0)
        if up is None:
            up = (0.0, 1.0, 0.0)
        if right is None:
            right = self._cross(up, forward)
        return forward, up, right

    @staticmethod
    def _format_state(target: str, *, speed: Optional[float], gps_name: str, dock: bool) -> str:
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
            options.append(f"speed={float(speed):.2f}")
        if dock:
            options.append("dock")
        return coords + (";" + ";".join(options) if options else "")


DEVICE_TYPE_MAP[RemoteControlDevice.device_type] = RemoteControlDevice
