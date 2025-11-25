from __future__ import annotations

from typing import Optional, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


Vector3 = Tuple[float, float, float]


class RemoteControlDevice(BaseDevice):
    device_type = "remote_control"

    # ------------------------------------------------------------------
    # Команды управления автопилотом
    # ------------------------------------------------------------------

    def enable(self) -> int:
        return self.send_command({
            "cmd": "remote_control",
            "state": "autopilot_enable",
            "targetId": int(self.device_id),
            "targetName": self.name or "Remote Control",
        })

    def set_mode(self, mode: str = "oneway") -> int:
        return self.send_command({
            "cmd": "set_mode",
            "mode": mode,  # "patrol", "circle", "oneway"
            "targetId": int(self.device_id),
            "targetName": self.name or "Remote Control",
        })

    def disable(self) -> int:
        return self.send_command({
            "cmd": "remote_control",
            "state": "autopilot_disable",
            "targetId": int(self.device_id),
            "targetName": self.name or "Remote Control",
        })

    def goto(
        self,
        gps: str,
        *,
        speed: Optional[float] = None,
        gps_name: str = "Target",
        dock: bool = False,
    ) -> int:
        formatted = self._format_state(gps, speed=speed, gps_name=gps_name, dock=dock)
        payload = {
            "cmd": "goto",
            "state": formatted,
            "targetId": int(self.device_id),
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def set_collision_avoidance(self, enabled: bool) -> int:
        return self.send_command({
            "cmd": "collision_avoidance",
            "enabled": enabled,
            "targetId": int(self.device_id),
            "targetName": self.name or "Remote Control",
        })

    # ------------------------------------------------------------------
    # ОРИЕНТАЦИЯ REMOTE CONTROL
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_vec3_from_obj(obj: object) -> Optional[Vector3]:
        """Парсит вектор (x,y,z) из dict или списка/кортежа длиной 3."""
        if isinstance(obj, dict):
            try:
                x = float(obj.get("x", 0.0))
                y = float(obj.get("y", 0.0))
                z = float(obj.get("z", 0.0))
                return (x, y, z)
            except (TypeError, ValueError):
                return None
        if isinstance(obj, (list, tuple)) and len(obj) == 3:
            try:
                x = float(obj[0])
                y = float(obj[1])
                z = float(obj[2])
                return (x, y, z)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _parse_vec3_from_string(text: object) -> Optional[Vector3]:
        """Парсит 'x,y,z' → (x,y,z)."""
        if not isinstance(text, str):
            return None
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            return None
        try:
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])
            return (x, y, z)
        except ValueError:
            return None

    @staticmethod
    def _cross(a: Vector3, b: Vector3) -> Vector3:
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def get_orientation_vectors_world(self) -> Tuple[Vector3, Vector3, Vector3]:
        """Возвращает (forward, up, right) REMOTE CONTROL в мировых координатах.

        Приоритет источников:
          1) telemetry["orientation"]["forward"/"up"/"right"/"left"]
          2) telemetry["forward"] / telemetry["up"] (строки "x,y,z")
          3) если right/left отсутствуют — right = up × forward
        """
        t = self.telemetry or {}

        forward: Optional[Vector3] = None
        up: Optional[Vector3] = None
        right: Optional[Vector3] = None

        # -------- 1) Новый формат: orientation.* --------
        ori = t.get("orientation")
        if isinstance(ori, dict):
            f_obj = ori.get("forward")
            u_obj = ori.get("up")
            r_obj = ori.get("right")
            l_obj = ori.get("left")

            if f_obj is not None:
                forward = self._parse_vec3_from_obj(f_obj)
            if u_obj is not None:
                up = self._parse_vec3_from_obj(u_obj)

            # right либо напрямую, либо из left (разворачиваем знак)
            if r_obj is not None:
                right = self._parse_vec3_from_obj(r_obj)
            elif l_obj is not None:
                left_vec = self._parse_vec3_from_obj(l_obj)
                if left_vec is not None:
                    right = (-left_vec[0], -left_vec[1], -left_vec[2])

        # -------- 2) Старый формат: строки "forward"/"up" --------
        if forward is None:
            f_str = t.get("forward")
            v = self._parse_vec3_from_string(f_str)
            if v is not None:
                forward = v

        if up is None:
            u_str = t.get("up")
            v = self._parse_vec3_from_string(u_str)
            if v is not None:
                up = v

        # -------- 3) Фолбэк, если всё совсем плохо --------
        if forward is None:
            forward = (0.0, 0.0, 1.0)
        if up is None:
            up = (0.0, 1.0, 0.0)

        # -------- 4) Строим right, если его нет --------
        if right is None:
            right = self._cross(up, forward)

        return forward, up, right

    # ------------------------------------------------------------------
    # Вспомогательный формат для remote_goto
    # ------------------------------------------------------------------

    @staticmethod
    def _format_state(
        target: str,
        *,
        speed: Optional[float],
        gps_name: str,
        dock: bool,
    ) -> str:
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
        if dock:
            # флажок для докинга, будет распознан на стороне плагина
            options.append("dock")

        if options:
            return coords + ";" + ";".join(options)
        return coords


DEVICE_TYPE_MAP[RemoteControlDevice.device_type] = RemoteControlDevice
