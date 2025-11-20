"""Implementations for AI-enabled blocks from the se-grid-controller plugin."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP

VectorLike = Sequence[float] | Mapping[str, Any]


def _normalize_vector(position: VectorLike | str) -> dict[str, float]:
    """Convert a position specification to ``{"x", "y", "z"}`` mapping."""

    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError("coordinate components must be numeric") from exc

    if isinstance(position, str):
        stripped = position.strip()
        if not stripped:
            raise ValueError("coordinate string must not be empty")
        if stripped.upper().startswith("GPS:"):
            stripped = stripped[4:]
        stripped = stripped.strip(":")
        parts = [p for p in stripped.replace(",", ":").split(":") if p]
        if len(parts) < 3:
            raise ValueError("coordinate string must contain three components")
        x, y, z = (_as_float(part) for part in parts[-3:])
        return {"x": x, "y": y, "z": z}

    if isinstance(position, Mapping):
        missing = [axis for axis in ("x", "y", "z") if axis not in position]
        if missing:
            raise ValueError(
                "position mapping must contain x/y/z keys (missing: {})".format(", ".join(missing))
            )
        return {axis: _as_float(position[axis]) for axis in ("x", "y", "z")}

    if isinstance(position, Sequence):
        if len(position) < 3:
            raise ValueError("position sequence must contain at least three values")
        return {
            "x": _as_float(position[0]),
            "y": _as_float(position[1]),
            "z": _as_float(position[2]),
        }

    raise TypeError("position must be a sequence, mapping or string")


class AiFunctionalBlockDevice(BaseDevice):
    """Base helper for AI-enabled functional blocks."""

    def _send_ai_command(self, cmd: str, state: MutableMapping[str, Any] | None = None) -> int:
        payload: dict[str, Any] = {"cmd": cmd}
        if state:
            payload["state"] = state
        return self.send_command(payload)

    def set_property(self, name: str, value: Any, *, target: str | None = None) -> int:
        if not name:
            raise ValueError("property name must be non-empty")
        state: dict[str, Any] = {"property": name, "value": value}
        if target:
            state["target"] = target
        return self._send_ai_command("set_property", state)

    def set_bool(self, name: str, value: bool, *, target: str | None = None) -> int:
        return self.set_property(name, bool(value), target=target)

    def set_int(self, name: str, value: int, *, target: str | None = None) -> int:
        state: dict[str, Any] = {"property": name, "value": int(value)}
        if target:
            state["target"] = target
        return self._send_ai_command("set_int", state)

    def set_float(self, name: str, value: float, *, target: str | None = None) -> int:
        state: dict[str, Any] = {"property": name, "value": float(value)}
        if target:
            state["target"] = target
        return self._send_ai_command("set_double", state)

    def set_string(self, name: str, value: str, *, target: str | None = None) -> int:
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        state: dict[str, Any] = {"property": name, "value": value}
        if target:
            state["target"] = target
        return self._send_ai_command("set_string", state)

    def set_vector(self, name: str, position: VectorLike | str, *, target: str | None = None) -> int:
        state: dict[str, Any] = {"property": name, "value": _normalize_vector(position)}
        if target:
            state["target"] = target
        return self._send_ai_command("set_property", state)

    def invoke(self, method: str, *args: Any, target: str | None = None) -> int:
        if not method:
            raise ValueError("method name must be non-empty")
        state: dict[str, Any] = {"method": method}
        if args:
            state["args"] = list(args)
        if target:
            state["target"] = target
        return self._send_ai_command("invoke", state)


class AiMissionBlockDevice(AiFunctionalBlockDevice):
    """Shared helpers for AI mission/autopilot blocks."""

    def select_mission(self, mission_id: int) -> int:
        return self._send_ai_command("mission_select", {"missionId": int(mission_id)})

    def start_mission(self) -> int:
        return self._send_ai_command("mission_enable")

    def stop_mission(self) -> int:
        return self._send_ai_command("mission_disable")

    def reset_mission(self) -> int:
        return self._send_ai_command("mission_reset")

    def enable_autopilot(self) -> int:
        return self._send_ai_command("autopilot_enable")

    def disable_autopilot(self) -> int:
        return self._send_ai_command("autopilot_disable")

    def pause_autopilot(self) -> int:
        return self._send_ai_command("autopilot_pause")

    def resume_autopilot(self) -> int:
        return self._send_ai_command("autopilot_resume")

    def clear_waypoints(self) -> int:
        return self._send_ai_command("clear_waypoints")

    def add_waypoint(
        self,
        position: VectorLike | str,
        *,
        speed: float | None = None,
        name: str | None = None,
    ) -> int:
        state: dict[str, Any] = {"position": _normalize_vector(position)}
        if speed is not None:
            state["speed"] = float(speed)
        if name:
            state["name"] = name
        return self._send_ai_command("add_waypoint", state)

    def set_speed_limit(self, value: float) -> int:
        return self._send_ai_command("set_speed_limit", {"value": float(value)})

    def set_collision_avoidance(self, enabled: bool) -> int:
        return self._send_ai_command("set_collision_avoidance", {"value": bool(enabled)})

    def set_terrain_follow(self, enabled: bool) -> int:
        return self._send_ai_command("set_terrain_follow", {"value": bool(enabled)})

    def set_mode(self, mode: str) -> int:
        if not mode:
            raise ValueError("mode must be a non-empty string")
        return self._send_ai_command("set_mode", {"mode": mode})


class AiTaskDevice(AiFunctionalBlockDevice):
    """Base helper for combat/utility AI task blocks."""

    def set_target(
        self,
        *,
        entity_id: int | None = None,
        position: VectorLike | str | None = None,
        raw: str | None = None,
    ) -> int:
        if entity_id is None and position is None and not raw:
            raise ValueError("provide entity_id, position or raw target definition")

        state: dict[str, Any] = {}
        if entity_id is not None:
            state["entityId"] = int(entity_id)
        if position is not None:
            state["position"] = _normalize_vector(position)
        if raw:
            state["value"] = raw
        return self._send_ai_command("set_target", state)

    def clear_target(self) -> int:
        return self._send_ai_command("clear_target")

    def set_mode(self, mode: str) -> int:
        if not mode:
            raise ValueError("mode must be a non-empty string")
        return self._send_ai_command("set_mode", {"mode": mode})


class AiBehaviorDevice(AiFunctionalBlockDevice):
    """Wrapper for the AI Behavior block."""

    device_type = "ai_behavior"

    def set_behavior(self, behavior: str) -> int:
        if not behavior:
            raise ValueError("behavior name must be non-empty")
        return self._send_ai_command("set_behavior", {"behavior": behavior})

    def start_behavior(self) -> int:
        return self._send_ai_command("behavior_start")

    def stop_behavior(self) -> int:
        return self._send_ai_command("behavior_stop")


class AiRecorderDevice(AiFunctionalBlockDevice):
    """Wrapper for the AI Recorder block."""

    device_type = "ai_recorder"

    def start_recording(self) -> int:
        return self._send_ai_command("recorder_start")

    def stop_recording(self) -> int:
        return self._send_ai_command("recorder_stop")

    def play_recording(self) -> int:
        return self._send_ai_command("recorder_play")

    def clear_recording(self) -> int:
        return self._send_ai_command("recorder_clear")


from __future__ import annotations

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class AiBehaviorDevice(BaseDevice):
    """
    Обёртка для AI Behavior (Task) блока.

    Ожидается, что в телеметрии type соответствует строке "ai_behavior"
    (это должно быть настроено на стороне плагина / конфигов устройств).
    """
    device_type = "ai_behavior"

    def set_behavior(self, behavior: str) -> int:
        """
        Выбор профиля поведения (Behavior profile) для AI Behavior блока.
        """
        payload = {
            "cmd": "set_behavior",
            "state": behavior,
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def start_behavior(self) -> int:
        """
        Включить AI Behavior (аналог кнопки 'Enable AI Behavior' в терминале).
        """
        payload = {
            "cmd": "behavior_start",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def stop_behavior(self) -> int:
        """
        Выключить AI Behavior.
        """
        payload = {
            "cmd": "behavior_stop",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)


DEVICE_TYPE_MAP[AiBehaviorDevice.device_type] = AiBehaviorDevice


class AiMoveGroundDevice(AiMissionBlockDevice):
    """Wrapper for the AI Basic Move (Ground) block."""

    device_type = "ai_move_ground"


class AiFlightAutopilotDevice(AiMissionBlockDevice):
    """Wrapper for the AI Flight Autopilot block."""

    device_type = "ai_flight_autopilot"


class AiOffensiveDevice(AiTaskDevice):
    """Wrapper for the AI Offensive block."""

    device_type = "ai_offensive"


class AiDefensiveDevice(AiTaskDevice):
    """Wrapper for the AI Defensive block."""

    device_type = "ai_defensive"


DEVICE_TYPE_MAP[AiMoveGroundDevice.device_type] = AiMoveGroundDevice
DEVICE_TYPE_MAP[AiFlightAutopilotDevice.device_type] = AiFlightAutopilotDevice
DEVICE_TYPE_MAP[AiOffensiveDevice.device_type] = AiOffensiveDevice
DEVICE_TYPE_MAP[AiDefensiveDevice.device_type] = AiDefensiveDevice
DEVICE_TYPE_MAP[AiBehaviorDevice.device_type] = AiBehaviorDevice
DEVICE_TYPE_MAP[AiRecorderDevice.device_type] = AiRecorderDevice


from __future__ import annotations

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class AiFlightAutopilotDevice(BaseDevice):
    """
    Обёртка для AI Flight (Move) блока, который управляет движением грида.

    Ожидается, что type в телеметрии соответствует "ai_flight_autopilot"
    (это задаётся на стороне плагина через конфиг устройства).
    """
    device_type = "ai_flight_autopilot"

    # --- Precision Mode (Docking) ---

    def enable_precision(self) -> int:
        """
        Включить Precision Mode (Docking) на AI Flight блоке.
        """
        payload = {
            "cmd": "precision_on",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def disable_precision(self) -> int:
        """
        Выключить Precision Mode (Docking).
        """
        payload = {
            "cmd": "precision_off",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    # --- Collision Avoidance ---

    def enable_collision_avoidance(self) -> int:
        """
        Включить Collision Avoidance для AI Flight.
        """
        payload = {
            "cmd": "collision_avoidance_on",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def disable_collision_avoidance(self) -> int:
        """
        Выключить Collision Avoidance.
        """
        payload = {
            "cmd": "collision_avoidance_off",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    # --- AI Behavior ON/OFF для move-блока ---

    def start_behavior(self) -> int:
        """
        Включить AI Behavior именно на AI Flight (Move) блоке.
        Обычно его надо включать вместе с AI Behavior (Task).
        """
        payload = {
            "cmd": "behavior_start",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def stop_behavior(self) -> int:
        """
        Выключить AI Behavior на AI Flight.
        """
        payload = {
            "cmd": "behavior_stop",
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)


DEVICE_TYPE_MAP[AiFlightAutopilotDevice.device_type] = AiFlightAutopilotDevice
