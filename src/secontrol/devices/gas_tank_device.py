"""Gas tank wrapper for oxygen and hydrogen tanks."""

from __future__ import annotations

import time
from typing import Any, Dict

from secontrol.base_device import DEVICE_TYPE_MAP, _coerce_bool, _safe_float
from secontrol.base_device import BaseDevice


class GasTankDevice(BaseDevice):
    """Expose telemetry and commands for oxygen/hydrogen tanks."""

    device_type = "gas_tank"

    # ----------------------- Telemetry helpers -----------------------
    def filled_ratio(self) -> float:
        return _as_float((self.telemetry or {}).get("filledRatio"), 0.0)

    def filled_percent(self) -> float:
        data = self.telemetry or {}
        value = data.get("filledPercent")
        if value is not None:
            return _as_float(value, 0.0)
        return self.filled_ratio() * 100.0

    def capacity(self) -> float:
        return _as_float((self.telemetry or {}).get("capacity"), 0.0)

    def stockpile(self) -> bool:
        return _coerce_bool((self.telemetry or {}).get("stockpile", False))

    def auto_refill(self) -> bool | None:
        data = self.telemetry or {}
        if "autoRefill" not in data:
            return None
        return _coerce_bool(data.get("autoRefill"))

    def terminal_on_off(self) -> bool | None:
        data = self.telemetry or {}
        if "terminalOnOff" not in data:
            return None
        return _coerce_bool(data.get("terminalOnOff"))

    def functional_enabled(self) -> bool | None:
        data = self.telemetry or {}
        if "functionalEnabled" not in data:
            return None
        return _coerce_bool(data.get("functionalEnabled"))

    def functional_status(self) -> Dict[str, Any]:
        data = self.telemetry or {}
        return {
            "enabled": bool(data.get("enabled", False)),
            "enabledSource": data.get("enabledSource"),
            "terminalOnOff": self.terminal_on_off(),
            "functionalEnabled": self.functional_enabled(),
            "isFunctional": bool(data.get("isFunctional", False)),
            "isWorking": bool(data.get("isWorking", False)),
            "stockpile": self.stockpile(),
            "filledRatio": self.filled_ratio(),
            "filledPercent": self.filled_percent(),
            "capacity": self.capacity(),
        }

    # -------------------------- Commands ----------------------------
    def set_stockpile(self, enabled: bool) -> int:
        """Enable or disable Stockpile mode.

        In the Russian UI this is the tank mode named "Накопитель".
        The payload is intentionally flat because older plugin builds parse
        flat boolean keys more reliably than nested state objects.
        """
        value = bool(enabled)
        return self.send_command({"cmd": "set_stockpile", "stockpile": value, "value": value})

    def set_stockpile_verified(self, enabled: bool, *, timeout: float = 3.0) -> bool:
        """Set Stockpile mode and confirm it through telemetry."""
        value = bool(enabled)
        if self.stockpile() == value:
            return True
        sent = self.set_stockpile(value)
        if sent <= 0:
            return False
        return self._wait_until(lambda: self.stockpile() == value, timeout=timeout)

    def enable_stockpile(self, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        """Turn on Stockpile / "Накопитель" mode."""
        if verify:
            return self.set_stockpile_verified(True, timeout=timeout)
        return self.set_stockpile(True)

    def disable_stockpile(self, *, verify: bool = True, timeout: float = 3.0) -> bool | int:
        """Turn off Stockpile / "Накопитель" mode."""
        if verify:
            return self.set_stockpile_verified(False, timeout=timeout)
        return self.set_stockpile(False)

    def toggle_stockpile(self) -> int:
        return self.send_command({"cmd": "toggle_stockpile"})

    def set_auto_refill(self, enabled: bool) -> int:
        value = bool(enabled)
        return self.send_command({"cmd": "set_auto_refill", "autoRefill": value, "value": value})

    def set_auto_refill_verified(self, enabled: bool, *, timeout: float = 3.0) -> bool:
        value = bool(enabled)
        current = self.auto_refill()
        if current is not None and current == value:
            return True
        sent = self.set_auto_refill(value)
        if sent <= 0:
            return False
        return self._wait_until(lambda: self.auto_refill() == value, timeout=timeout)

    def _wait_until(self, predicate, *, timeout: float = 3.0, poll: float = 0.15) -> bool:
        deadline = time.time() + max(0.0, float(timeout))
        attempt = 0
        while time.time() <= deadline:
            try:
                if predicate():
                    return True
            except Exception:
                pass

            attempt += 1
            force_update = attempt % 4 == 0
            try:
                self.wait_for_telemetry(
                    timeout=min(0.5, max(0.05, deadline - time.time())),
                    wait_for_new=True,
                    need_update=force_update,
                )
            except Exception:
                pass
            time.sleep(max(0.01, float(poll)))

        try:
            self.wait_for_telemetry(timeout=0.5, wait_for_new=False, need_update=True)
        except Exception:
            pass
        try:
            return bool(predicate())
        except Exception:
            return False


def _as_float(value: Any, default: float) -> float:
    parsed = _safe_float(value)
    return default if parsed is None else float(parsed)


DEVICE_TYPE_MAP[GasTankDevice.device_type] = GasTankDevice
