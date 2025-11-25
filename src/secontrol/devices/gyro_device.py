"""Gyroscopic control device implementation for Space Engineers grid control.

This module provides functionality to control gyroscopes on SE grids,
including setting overrides for pitch, yaw, and roll rotation.
"""

from __future__ import annotations

from typing import Optional, Sequence

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class GyroDevice(BaseDevice):
    device_type = "gyro"

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(-1.0, min(1.0, float(x)))

    @staticmethod
    def _parse_vector(vector: object) -> tuple[float, float, float]:
        if isinstance(vector, dict):
            try:
                return (
                    float(vector.get("x", 0.0)),
                    float(vector.get("y", 0.0)),
                    float(vector.get("z", 0.0)),
                )
            except (TypeError, ValueError):
                pass

        if isinstance(vector, Sequence) and not isinstance(vector, (str, bytes, bytearray)) and len(vector) == 3:
            try:
                return (float(vector[0]), float(vector[1]), float(vector[2]))
            except (TypeError, ValueError):
                pass

        raise ValueError("vector must be a mapping with x/y/z or a 3-length sequence")

    def set_override(self, *, pitch: float, yaw: float, roll: float, power: Optional[float] = None) -> int:
        p = self._clamp01(pitch)
        y = self._clamp01(yaw)
        r = self._clamp01(roll)

        csv = f"{p:.6f},{y:.6f},{r:.6f}"
        kv  = f"pitch={p:.6f};yaw={y:.6f};roll={r:.6f}"
        obj = {"pitch": p, "yaw": y, "roll": r}
        if power is not None:
            # если где-то ожидают power — отправим его тоже
            obj["power"] = float(power)

        sent = 0

        # A) Your current C# (если там строка с CSV — это оно)
        sent += self.send_command({"cmd": "override", "state": csv})

        return sent

    def align_vector(self, vector: object, *, command: str = "align_vector") -> int:
        """Выравнивает корабль по заданному мировому вектору.

        Метод отправляет встроенную команду гироскопа ``align_vector`` (или её
        синоним ``aim_vector``), которая обрабатывается на стороне плагина
        сервера SE. Принимает вектор в виде dict с ключами ``x``,
        ``y``, ``z`` либо любой последовательности из трёх чисел.
        """

        if command not in {"align_vector", "aim_vector"}:
            raise ValueError("command must be 'align_vector' or 'aim_vector'")

        x, y, z = self._parse_vector(vector)
        if abs(x) < 1e-6 and abs(y) < 1e-6 and abs(z) < 1e-6:
            raise ValueError("vector must be non-zero")

        payload = {
            "cmd": command,
            "x": x,
            "y": y,
            "z": z,
            # Дополнительно дублируем в человекочитаемой строке и объекте,
            # чтобы работали любые варианты парсинга на стороне плагина.
            "state": f"{x:.6f},{y:.6f},{z:.6f}",
            "vector": {"x": x, "y": y, "z": z},
        }

        return self.send_command(payload)

    def aim_vector(self, vector: object) -> int:
        """Синоним :py:meth:`align_vector` с командой ``aim_vector``."""

        return self.align_vector(vector, command="aim_vector")

    def enable(self) -> int:
        return self.send_command({"cmd": "enable", "state": ""})

    def disable(self) -> int:
        return self.send_command({"cmd": "disable", "state": ""})

    def clear_override(self) -> int:
        return self.send_command({"cmd": "clear_override", "state": ""})


DEVICE_TYPE_MAP[GyroDevice.device_type] = GyroDevice
