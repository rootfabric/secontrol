"""Helpers for controllable weapon blocks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from secontrol.base_device import DEVICE_TYPE_MAP

from .container_device import ContainerDevice


class WeaponDevice(ContainerDevice):
    """Expose telemetry and commands for controllable ship weapons."""

    device_type = "weapon"

    # -------------------------- Telemetry helpers -------------------------
    def _telemetry_bool(self, *keys: str, default: bool = False) -> bool:
        data = self.telemetry or {}
        for key in keys:
            if key in data and data[key] is not None:
                return bool(data[key])
        return bool(default)

    def _telemetry_number(
        self,
        *keys: str,
        default: Optional[float] = None,
        cast: type[float | int] = float,
    ) -> Optional[float | int]:
        data = self.telemetry or {}
        for key in keys:
            if key in data and data[key] is not None:
                try:
                    return cast(data[key])  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
        return default

    def is_functional(self) -> bool:
        return self._telemetry_bool("isFunctional", "functional", default=True)

    def is_working(self) -> bool:
        return self._telemetry_bool("isWorking", "working", default=False)

    def is_shooting(self) -> bool:
        return self._telemetry_bool("isShooting", "shooting", "isShootingManual")

    def is_reloading(self) -> bool:
        return self._telemetry_bool("isReloading", "reloading")

    def use_conveyor(self) -> bool:
        return self._telemetry_bool("useConveyorSystem", "useConveyor")

    def ammo_status(self) -> Dict[str, Optional[float | int]]:
        """Return aggregated ammo information from telemetry."""

        current = self._telemetry_number(
            "currentAmmo",
            "ammoCount",
            "currentMagazineAmmo",
            "remainingAmmo",
            cast=float,
        )
        maximum = self._telemetry_number(
            "maxAmmo",
            "maxMagazineAmmo",
            "maxAmmoAmount",
            cast=float,
        )
        magazines = self._telemetry_number(
            "magazines",
            "magazineCount",
            "ammoInventoryCount",
            cast=float,
        )
        return {
            "current": current,
            "maximum": maximum,
            "magazines": magazines,
        }

    def heat_ratio(self) -> Optional[float]:
        value = self._telemetry_number("heatRatio", "heatLevel", cast=float)
        return None if value is None else float(value)

    def rate_of_fire(self) -> float:
        value = self._telemetry_number(
            "rateOfFire",
            "shootRate",
            "shotsPerMinute",
            cast=float,
            default=0.0,
        )
        return float(value or 0.0)

    def reload_time_remaining(self) -> float:
        value = self._telemetry_number(
            "reloadTimeRemaining",
            "reloadTimeLeft",
            "timeUntilReady",
            cast=float,
            default=0.0,
        )
        return float(value or 0.0)

    def time_since_last_shot(self) -> float:
        value = self._telemetry_number(
            "timeSinceLastShot",
            "timeFromLastShot",
            cast=float,
            default=0.0,
        )
        return float(value or 0.0)

    # ---------------------------- Commands --------------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({"cmd": "enable" if enabled else "disable"})

    def toggle_enabled(self) -> int:
        return self.send_command({"cmd": "toggle"})

    def set_use_conveyor(self, enabled: bool) -> int:
        return self.send_command(
            {"cmd": "use_conveyor", "state": {"useConveyor": bool(enabled)}}
        )

    def shoot_once(self) -> int:
        return self.send_command({"cmd": "shoot_once"})

    def shoot_start(self) -> int:
        return self.send_command({"cmd": "shoot_on"})

    def shoot_stop(self) -> int:
        return self.send_command({"cmd": "shoot_off"})

    def set_shooting(self, enabled: bool) -> int:
        return self.shoot_start() if enabled else self.shoot_stop()


class InteriorTurretDevice(WeaponDevice):
    """Telemetry helpers for interior turrets."""

    device_type = "interior_turret"

    def ai_enabled(self) -> bool:
        return self._telemetry_bool("aiEnabled", "ai")

    def idle_rotation(self) -> bool:
        return self._telemetry_bool("idleRotation", "idleRotate")

    def range(self) -> float:
        value = self._telemetry_number("range", "maxRange", cast=float, default=0.0)
        return float(value or 0.0)

    def target(self) -> Optional[Dict[str, Any]]:
        data = self.telemetry or {}
        target = data.get("target")
        if isinstance(target, dict):
            return target
        return None

    def set_idle_rotation(self, enabled: bool) -> int:
        return self.send_command(
            {"cmd": "idle_rotation", "state": {"idleRotation": bool(enabled)}}
        )

    def set_range(self, meters: float) -> int:
        return self.send_command({"cmd": "set_range", "state": {"range": float(meters)}})

    def reset_target(self) -> int:
        return self.send_command({"cmd": "reset_target"})


DEVICE_TYPE_MAP[WeaponDevice.device_type] = WeaponDevice
DEVICE_TYPE_MAP[InteriorTurretDevice.device_type] = InteriorTurretDevice
