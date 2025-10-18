"""Conveyor sorter wrapper with filter management helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from sepy.base_device import DEVICE_TYPE_MAP
from .container_device import ContainerDevice


def _normalize_filter(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, dict):
        payload = dict(entry)
    elif isinstance(entry, str):
        payload = {}
        if '/' in entry:
            type_part, subtype = entry.split('/', 1)
            payload["type"] = type_part
            payload["subtype"] = subtype
        else:
            payload["type"] = entry
    elif isinstance(entry, (tuple, list)) and entry:
        payload = {"type": entry[0]}
        if len(entry) > 1:
            payload["subtype"] = entry[1]
        if len(entry) > 2:
            payload["allSubtypes"] = bool(entry[2])
    else:
        raise ValueError(f"Unsupported filter format: {entry!r}")

    if "type" not in payload or not payload["type"]:
        raise ValueError(f"Filter entry must include a type identifier: {entry!r}")

    payload.setdefault("subtype", payload.get("subType", ""))
    payload["type"] = str(payload["type"])
    payload["subtype"] = str(payload.get("subtype", ""))
    payload["allSubtypes"] = bool(payload.get("allSubtypes", False))
    return {"type": payload["type"], "subtype": payload["subtype"], "allSubtypes": payload["allSubtypes"]}


class ConveyorSorterDevice(ContainerDevice):
    """Expose telemetry and commands for conveyor sorters."""

    device_type = "conveyor_sorter"

    # ----------------------- Telemetry helpers -----------------------
    def is_whitelist(self) -> bool:
        return bool((self.telemetry or {}).get("isWhitelist", False))

    def mode(self) -> str:
        return str((self.telemetry or {}).get("mode", "")).lower()

    def drain_all(self) -> bool:
        return bool((self.telemetry or {}).get("drainAll", False))

    def filters(self) -> List[Dict[str, Any]]:
        filt = (self.telemetry or {}).get("filters")
        if isinstance(filt, list):
            return [entry for entry in filt if isinstance(entry, dict)]
        return []

    # -------------------------- Commands ----------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({"cmd": "enable" if enabled else "disable"})

    def toggle_enabled(self) -> int:
        return self.send_command({"cmd": "toggle"})

    def set_whitelist(self, enabled: bool = True) -> int:
        return self.send_command({"cmd": "set_whitelist", "state": {"whitelist": bool(enabled)}})

    def set_blacklist(self) -> int:
        return self.send_command({"cmd": "set_blacklist"})

    def set_drain_all(self, enabled: bool) -> int:
        return self.send_command({"cmd": "set_drain_all", "state": {"drainAll": bool(enabled)}})

    def clear_filters(self) -> int:
        return self.send_command({"cmd": "clear_filters"})

    def add_filters(self, filters: Iterable[Any]) -> int:
        payload = [_normalize_filter(entry) for entry in filters]
        if not payload:
            return 0
        return self.send_command({"cmd": "add_filters", "state": {"filters": payload}})

    def remove_filters(self, filters: Iterable[Any]) -> int:
        payload = [_normalize_filter(entry) for entry in filters]
        if not payload:
            return 0
        return self.send_command({"cmd": "remove_filters", "state": {"filters": payload}})

    def set_filters(self, filters: Iterable[Any], *, whitelist: bool | None = None) -> int:
        payload = [_normalize_filter(entry) for entry in filters]
        if not payload:
            return 0
        state: Dict[str, Any] = {"filters": payload}
        if whitelist is not None:
            state["mode"] = "whitelist" if whitelist else "blacklist"
        return self.send_command({"cmd": "set_filters", "state": state})


DEVICE_TYPE_MAP[ConveyorSorterDevice.device_type] = ConveyorSorterDevice
