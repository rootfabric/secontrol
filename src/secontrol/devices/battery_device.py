"""Battery device implementation for Space Engineers grid control."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP, _coerce_bool


class BatteryDevice(BaseDevice):
    """Control helper for battery blocks."""

    device_type = "battery"

    # ----------------------- Telemetry helpers -----------------------
    def charge_mode(self) -> str:
        return str((self.telemetry or {}).get("chargeMode") or "Unknown")

    def terminal_on_off(self) -> Optional[bool]:
        telemetry = self.telemetry or {}
        if "terminalOnOff" not in telemetry:
            return None
        return _coerce_bool(telemetry.get("terminalOnOff"))

    def functional_enabled(self) -> Optional[bool]:
        telemetry = self.telemetry or {}
        if "functionalEnabled" not in telemetry:
            return None
        return _coerce_bool(telemetry.get("functionalEnabled"))

    def functional_status(self) -> dict[str, Any]:
        telemetry = self.telemetry or {}
        return {
            "enabled": self.is_enabled(),
            "enabledSource": telemetry.get("enabledSource"),
            "terminalOnOff": self.terminal_on_off(),
            "functionalEnabled": self.functional_enabled(),
            "isFunctional": _coerce_bool(telemetry.get("isFunctional", False)),
            "isWorking": _coerce_bool(telemetry.get("isWorking", False)),
            "chargeMode": self.charge_mode(),
            "currentStoredPowerMWh": telemetry.get("currentStoredPowerMWh", telemetry.get("currentStoredPower")),
            "maxStoredPowerMWh": telemetry.get("maxStoredPowerMWh", telemetry.get("maxStoredPower")),
            "currentInputMW": telemetry.get("currentInputMW", telemetry.get("currentInput")),
            "currentOutputMW": telemetry.get("currentOutputMW", telemetry.get("currentOutput")),
            "maxOutputMW": telemetry.get("maxOutputMW", telemetry.get("maxOutput")),
            "chargePercent": telemetry.get("chargePercent"),
        }

    # -------------------------- Commands ----------------------------
    def set_mode(self, mode: str) -> int:
        normalized = _normalize_mode(mode)
        return self.send_command({
            "cmd": "set_mode",
            "mode": normalized,
            "value": normalized,
            "state": {"mode": normalized},
        })

    def set_mode_verified(self, mode: str, *, timeout: float = 3.0) -> bool:
        expected = _canonical_mode(mode)
        current = _canonical_mode(self.charge_mode())
        if current == expected:
            return True
        return self._send_and_wait_for_fresh_state(
            lambda: self.set_mode(mode),
            lambda telemetry: _canonical_mode(telemetry.get("chargeMode")) == expected,
            timeout=timeout,
        )

    def set_enabled_verified(self, enabled: bool, *, timeout: float = 3.0) -> bool:
        value = bool(enabled)
        return self._send_and_wait_for_fresh_state(
            lambda: self.set_enabled(value),
            lambda telemetry: _coerce_bool(telemetry.get("enabled", False)) == value,
            timeout=timeout,
        )

    def enable_verified(self, *, timeout: float = 3.0) -> bool:
        return self.set_enabled_verified(True, timeout=timeout)

    def disable_verified(self, *, timeout: float = 3.0) -> bool:
        return self.set_enabled_verified(False, timeout=timeout)

    def set_auto(self, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        return self.set_mode_verified("auto", timeout=timeout) if verify else self.set_mode("auto")

    def set_recharge(self, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        return self.set_mode_verified("recharge", timeout=timeout) if verify else self.set_mode("recharge")

    def set_discharge(self, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        return self.set_mode_verified("discharge", timeout=timeout) if verify else self.set_mode("discharge")

    def set_semiauto(self, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        return self.set_mode_verified("semiauto", timeout=timeout) if verify else self.set_mode("semiauto")

    def _send_and_wait_for_fresh_state(
        self,
        send: Callable[[], int],
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float = 3.0,
    ) -> bool:
        before_timestamp = _timestamp(self.telemetry)
        self._telemetry_event.clear()

        sent = send()
        if sent <= 0:
            return False

        deadline = time.time() + max(0.0, float(timeout))
        attempt = 0

        while time.time() <= deadline:
            telemetry = self.telemetry or {}
            if _is_fresh(telemetry, before_timestamp) and predicate(telemetry):
                return True

            remaining = deadline - time.time()
            if remaining <= 0.0:
                break

            attempt += 1
            if attempt % 4 == 0:
                try:
                    self.update()
                except Exception:
                    pass

            self._telemetry_event.wait(timeout=min(0.35, max(0.02, remaining)))
            self._telemetry_event.clear()

        try:
            self.update()
            self._telemetry_event.wait(timeout=0.5)
        except Exception:
            pass

        telemetry = self.telemetry or {}
        return _is_fresh(telemetry, before_timestamp) and predicate(telemetry)


def _timestamp(telemetry: Optional[dict[str, Any]]) -> str:
    if not isinstance(telemetry, dict):
        return ""
    value = telemetry.get("timestamp")
    return "" if value is None else str(value)


def _is_fresh(telemetry: dict[str, Any], before_timestamp: str) -> bool:
    if not before_timestamp:
        return True
    return _timestamp(telemetry) != before_timestamp


def _normalize_mode(mode: str) -> str:
    canonical = _canonical_mode(mode)
    if canonical == "unknown":
        raise ValueError("mode must be 'auto', 'recharge', 'discharge' or 'semiauto'")
    return "semiauto" if canonical == "semiauto" else canonical


def _canonical_mode(mode: Any) -> str:
    normalized = str(mode or "").strip().lower().replace("-", "").replace("_", "")
    if normalized in {"auto", "automatic", "default"}:
        return "auto"
    if normalized in {"recharge", "charge", "charging"}:
        return "recharge"
    if normalized in {"discharge", "discharging"}:
        return "discharge"
    if normalized in {"semi", "semiauto", "balanced"}:
        return "semiauto"
    return "unknown"


DEVICE_TYPE_MAP[BatteryDevice.device_type] = BatteryDevice
