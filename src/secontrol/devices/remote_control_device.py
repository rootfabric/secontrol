from __future__ import annotations

from typing import Optional, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


Vec3 = Tuple[float, float, float]


class RemoteControlDevice(BaseDevice):
    device_type = "remote_control"

    # ------------------------------------------------------------------
    # ВСПОМОГАТЕЛЬНЫЕ ГЕТТЕРЫ СОСТОЯНИЯ
    # ------------------------------------------------------------------
    def _get_state_dict(self) -> dict:
        """
        Аккуратно достаём словарь состояния из BaseDevice.
        Пытаемся использовать self.state или self._state, чтобы не падать,
        если в BaseDevice имя поля отличается.
        """
        state = getattr(self, "state", None)
        if isinstance(state, dict):
            return state

        state2 = getattr(self, "_state", None)
        if isinstance(state2, dict):
            return state2

        return {}

    @staticmethod
    def _vec_from_obj(obj: object) -> Vec3:
        if not isinstance(obj, dict):
            return (0.0, 0.0, 0.0)
        try:
            x = float(obj.get("x", 0.0))
            y = float(obj.get("y", 0.0))
            z = float(obj.get("z", 0.0))
            return (x, y, z)
        except Exception:
            return (0.0, 0.0, 0.0)

    @staticmethod
    def _vec_from_str(text: object) -> Vec3:
        if text is None:
            return (0.0, 0.0, 0.0)
        try:
            parts = [p.strip() for p in str(text).split(",")]
            if len(parts) != 3:
                return (0.0, 0.0, 0.0)
            x = float(parts[0])
            y = float(parts[1])
            z = float(parts[2])
            return (x, y, z)
        except Exception:
            return (0.0, 0.0, 0.0)

    @staticmethod
    def _cross(a: Vec3, b: Vec3) -> Vec3:
        ax, ay, az = a
        bx, by, bz = b
        return (
            ay * bz - az * by,
            az * bx - ax * bz,
            ax * by - ay * bx,
        )

    # ------------------------------------------------------------------
    # ОРИЕНТАЦИЯ В МИРОВЫХ КООРДИНАТАХ (для автопилота/выравнивания)
    # ------------------------------------------------------------------
    def get_orientation_vectors_world(self) -> Tuple[Vec3, Vec3, Vec3]:
        """
        Возвращает (forward, up, right) в мировых координатах, взятые из телеметрии
        Remote Control.

        Ожидаемые источники:
          1) telemetry["orientation"]["forward"/"up"/"left"]
          2) поля telemetry["forward"] и telemetry["up"] (строки "X,Y,Z")

        Если есть только forward/up — right вычисляется как up × forward.
        Если что-то не найдено, вектора могут быть (0,0,0) — это повод
        выкинуть ошибку наверху и не пытаться выравниваться вслепую.
        """
        state = self._get_state_dict()

        forward: Vec3 = (0.0, 0.0, 0.0)
        up: Vec3 = (0.0, 0.0, 0.0)
        right: Vec3 = (0.0, 0.0, 0.0)

        # 1) Пытаемся взять orientation.{forward,up,left}
        ori = state.get("orientation")
        if isinstance(ori, dict):
            f_obj = ori.get("forward")
            u_obj = ori.get("up")
            l_obj = ori.get("left")

            if f_obj is not None:
                forward = self._vec_from_obj(f_obj)
            if u_obj is not None:
                up = self._vec_from_obj(u_obj)
            if l_obj is not None:
                left = self._vec_from_obj(l_obj)
                # В SE Right = -Left
                right = (-left[0], -left[1], -left[2])

        # 2) Фолбэк на строковые поля "forward"/"up"
        if forward == (0.0, 0.0, 0.0):
            f_str = state.get("forward")
            if f_str:
                forward = self._vec_from_str(f_str)

        if up == (0.0, 0.0, 0.0):
            u_str = state.get("up")
            if u_str:
                up = self._vec_from_str(u_str)

        # 3) Если right всё ещё нулевой, но есть forward/up — считаем up × forward
        if right == (0.0, 0.0, 0.0) and forward != (0.0, 0.0, 0.0) and up != (0.0, 0.0, 0.0):
            right = self._cross(up, forward)

        return forward, up, right

    # ------------------------------------------------------------------
    # КОМАНДЫ АВТОПИЛОТА / РЕЖИМОВ
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
            "cmd": "remote_goto",
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
    # ФОРМАТИРОВАНИЕ STATE ДЛЯ remote_goto (GPS + speed + dock)
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
            # флажок для докинга, разбирается на стороне плагина (TryParseRemoteGotoState)
            options.append("dock")

        if options:
            return coords + ";" + ";".join(options)
        return coords


DEVICE_TYPE_MAP[RemoteControlDevice.device_type] = RemoteControlDevice
