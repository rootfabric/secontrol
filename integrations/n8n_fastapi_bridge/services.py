"""Redis helpers exposed through FastAPI endpoints."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, status

from secontrol.base_device import Grid
from secontrol.redis_client import RedisEventClient

from .auth import UserAccount
from .models import CommandRequest, DeviceSummary, GridSummary, TelemetryResponse


class RedisManager:
    """Lazily creates RedisEventClient instances based on user configuration."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clients: Dict[tuple[str | None, str | None, str | None], RedisEventClient] = {}

    def get_client(self, user: UserAccount) -> RedisEventClient:
        url = user.redis_url or os.getenv("REDIS_URL")
        username = user.redis_username or os.getenv("REDIS_USERNAME")
        password = user.redis_password or os.getenv("REDIS_PASSWORD")
        key = (url, username, password)
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                kwargs: Dict[str, Any] = {}
                if username:
                    kwargs["username"] = username
                if password:
                    kwargs["password"] = password
                client = RedisEventClient(url=url, **kwargs)
                self._clients[key] = client
            return client

    def close(self) -> None:
        with self._lock:
            for client in self._clients.values():
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()


class BridgeService:
    def __init__(self, redis_manager: RedisManager) -> None:
        self._redis_manager = redis_manager

    # ------------------------------------------------------------------
    def list_grids(self, user: UserAccount, include_subgrids: bool = True) -> List[GridSummary]:
        client = self._redis_manager.get_client(user)
        try:
            descriptors = client.list_grids(user.owner_id, exclude_subgrids=not include_subgrids)
        except Exception as exc:  # pragma: no cover - network failures are environment specific
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        result: List[GridSummary] = []
        for descriptor in descriptors:
            grid_id = _extract_grid_id(descriptor)
            if not grid_id:
                continue
            info = client.get_json(f"se:{user.owner_id}:grid:{grid_id}:gridinfo")
            info_dict = info if isinstance(info, dict) else {}
            name = _coalesce_name(info_dict, descriptor)
            is_subgrid = _resolve_is_subgrid(info_dict, descriptor)
            tags = _extract_tags(info_dict, descriptor)
            summary = GridSummary(
                id=str(grid_id),
                ownerId=str(user.owner_id),
                name=name,
                isSubgrid=is_subgrid,
                descriptor=descriptor if isinstance(descriptor, dict) else {"raw": descriptor},
                info=info_dict,
                tags=tags,
            )
            result.append(summary)
        return result

    # ------------------------------------------------------------------
    def list_devices(self, user: UserAccount, grid_id: str) -> List[DeviceSummary]:
        return self._with_grid(user, grid_id, lambda grid: self._snapshot_devices(user, grid))

    # ------------------------------------------------------------------
    def list_all_devices(self, user: UserAccount) -> List[DeviceSummary]:
        grids = self.list_grids(user, include_subgrids=True)
        devices: List[DeviceSummary] = []
        for grid in grids:
            devices.extend(self.list_devices(user, grid.id))
        return devices

    # ------------------------------------------------------------------
    def get_device(self, user: UserAccount, grid_id: str, device_id: str) -> DeviceSummary:
        summaries = self._with_grid(user, grid_id, lambda grid: self._snapshot_devices(user, grid))
        for summary in summaries:
            if summary.id == str(device_id):
                return summary
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    # ------------------------------------------------------------------
    def get_device_telemetry(self, user: UserAccount, grid_id: str, device_id: str) -> TelemetryResponse:
        def _fetch(grid: Grid) -> TelemetryResponse:
            device = grid.get_device_any(device_id)
            if device is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
            telemetry = device.telemetry
            if telemetry is None:
                telemetry = grid.redis.get_json(device.telemetry_key) or {}
            summary = self._device_to_summary(user, grid, device, telemetry)
            timestamp = _extract_timestamp(telemetry)
            return TelemetryResponse(device=summary, telemetry=telemetry or {}, updatedAt=timestamp)

        return self._with_grid(user, grid_id, _fetch)

    # ------------------------------------------------------------------
    def send_grid_command(self, user: UserAccount, grid_id: str, command: CommandRequest) -> int:
        def _execute(grid: Grid) -> int:
            payload = command.payload or {}
            extras = command.extra_params
            try:
                sent = grid.send_grid_command(command.cmd, state=command.state, payload=payload, **extras)
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
            return sent

        return self._with_grid(user, grid_id, _execute)

    # ------------------------------------------------------------------
    def send_device_command(
        self,
        user: UserAccount,
        grid_id: str,
        device_id: str,
        command: CommandRequest,
    ) -> int:
        def _execute(grid: Grid) -> int:
            device = grid.get_device_any(device_id)
            if device is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
            payload = command.command_dict()
            try:
                return device.send_command(payload)
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        return self._with_grid(user, grid_id, _execute)

    # ------------------------------------------------------------------
    def _snapshot_devices(self, user: UserAccount, grid: Grid) -> List[DeviceSummary]:
        devices: List[DeviceSummary] = []
        for device in grid.devices.values():
            telemetry = device.telemetry
            if telemetry is None:
                telemetry = grid.redis.get_json(device.telemetry_key) or {}
            devices.append(self._device_to_summary(user, grid, device, telemetry))
        return devices

    # ------------------------------------------------------------------
    def _device_to_summary(
        self,
        user: UserAccount,
        grid: Grid,
        device,
        telemetry: Optional[Dict[str, Any]],
    ) -> DeviceSummary:
        metadata: Dict[str, Any] = {}
        device_meta = getattr(device, "metadata", None)
        if device_meta is not None:
            metadata = {
                "deviceId": getattr(device_meta, "device_id", None),
                "deviceType": getattr(device_meta, "device_type", None),
                "telemetryKey": getattr(device_meta, "telemetry_key", None),
                "gridId": getattr(device_meta, "grid_id", None),
                "raw": getattr(device_meta, "extra", {}),
            }
        capabilities = _infer_capabilities(device, telemetry)
        command_channel = None
        try:
            command_channel = device.command_channel()
        except Exception:
            pass
        summary = DeviceSummary(
            id=str(getattr(device, "device_id", "")),
            gridId=str(getattr(device, "grid_id", grid.grid_id)),
            ownerId=str(user.owner_id),
            deviceType=getattr(device, "device_type", None),
            name=getattr(device, "name", None),
            telemetry=telemetry or {},
            capabilities=capabilities,
            commandChannel=command_channel,
            metadata=metadata,
        )
        return summary

    # ------------------------------------------------------------------
    def _with_grid(self, user: UserAccount, grid_id: str, func: Callable[[Grid], Any]):
        client = self._redis_manager.get_client(user)
        grid = Grid(client, user.owner_id, str(grid_id), user.player_id or user.owner_id)
        try:
            return func(grid)
        finally:
            try:
                grid.close()
            except Exception:
                pass


def _extract_grid_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("gridId", "grid_id", "id", "entityId"):
            value = payload.get(key)
            if value:
                return str(value)
    if isinstance(payload, (list, tuple)) and payload:
        return _extract_grid_id(payload[0])
    if payload:
        return str(payload)
    return None


def _coalesce_name(*candidates: Any) -> Optional[str]:
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("name", "gridName", "displayName", "DisplayName"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return None


def _resolve_is_subgrid(info: Dict[str, Any], descriptor: Dict[str, Any]) -> bool:
    for source in (info, descriptor):
        if not isinstance(source, dict):
            continue
        for key in ("isSubgrid", "isSubGrid", "is_subgrid"):
            value = source.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
        if source.get("isMainGrid") is False:
            return True
    return False


def _extract_tags(info: Dict[str, Any], descriptor: Dict[str, Any]) -> List[str]:
    raw = None
    for source in (info, descriptor):
        if isinstance(source, dict):
            raw = source.get("tags")
            if raw:
                break
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, (str, int, float))]
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
        return [part for part in parts if part]
    return [str(raw)]


def _infer_capabilities(device, telemetry: Optional[Dict[str, Any]]) -> List[str]:
    methods = {
        "enable": "enable",
        "disable": "disable",
        "toggle": "toggle",
        "turn_on": "turn_on",
        "turn_off": "turn_off",
        "set_enabled": "set_enabled",
        "set_color": "set_color",
        "set_intensity": "set_intensity",
        "set_radius": "set_radius",
        "set_power": "set_power",
        "set_custom_data": "set_custom_data",
    }
    capabilities: List[str] = []
    for attr, name in methods.items():
        if callable(getattr(device, attr, None)):
            capabilities.append(name)
    capabilities.append("send_command")
    if telemetry:
        for key in ("enabled", "intensity", "power", "radius", "color", "customData"):
            if key in telemetry and f"state:{key}" not in capabilities:
                capabilities.append(f"state:{key}")
    return list(dict.fromkeys(capabilities))


def _extract_timestamp(telemetry: Optional[Dict[str, Any]]) -> Optional[datetime]:
    if not telemetry:
        return None
    for key in ("ts", "timestamp", "updatedAt", "lastUpdate", "last_update"):
        value = telemetry.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            # Telemetry often uses milliseconds
            timestamp = float(value)
            if timestamp > 1e12:
                timestamp /= 1000.0
            return datetime.fromtimestamp(timestamp, tz=UTC)
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                continue
            # Accept ISO 8601 forms including trailing Z
            if candidate.endswith("Z"):
                candidate = candidate[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                continue
    return None


__all__ = [
    "BridgeService",
    "RedisManager",
]
