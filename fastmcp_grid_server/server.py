"""FastMCP server exposing Space Engineers grid and device operations.

The server authenticates against the Space Engineers Redis gateway and exposes
all grid and device helpers from :mod:`secontrol` as MCP tools.  LLM clients can
list grids, inspect telemetry, and execute device commands using structured
inputs with detailed descriptions.
"""
from __future__ import annotations

import atexit
import dataclasses
import inspect
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Dict

from fastmcp import Context, FastMCP

from secontrol.base_device import BaseDevice, Grid
from secontrol.devices import DEVICE_TYPE_MAP  # ensures built-ins are registered
from secontrol.redis_client import RedisEventClient


_GRID_METHOD_BLACKLIST = {"close", "on", "off", "subscribe_to_damage"}
_DEVICE_METHOD_BLACKLIST = {"close", "on", "off"}


@dataclasses.dataclass
class SessionState:
    """Holds Redis connection details for an MCP session."""

    client: RedisEventClient
    owner_id: str
    player_id: str
    redis_url: str | None = None

    def close(self) -> None:
        """Close the underlying Redis client."""
        try:
            self.client.close()
        except Exception:
            pass


class RedisSessionManager:
    """Tracks Redis connections per MCP session id."""

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def set_session(self, session_id: str, state: SessionState) -> None:
        with self._lock:
            previous = self._sessions.pop(session_id, None)
            if previous is not None:
                previous.close()
            self._sessions[session_id] = state

    def require(self, session_id: str) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
        if state is None:
            raise RuntimeError(
                "Нет активного подключения к Redis. Сначала вызовите инструмент "
                "`authenticate_redis`."
            )
        return state

    def clear(self, session_id: str) -> bool:
        with self._lock:
            state = self._sessions.pop(session_id, None)
        if state is None:
            return False
        state.close()
        return True

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for state in sessions:
            state.close()


_sessions = RedisSessionManager()
atexit.register(_sessions.close_all)


def _extract_grid_id(payload: Mapping[str, Any]) -> str | None:
    for key in ("grid_id", "gridId", "id", "GridId", "entity_id", "entityId"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _extract_grid_name(descriptor: Mapping[str, Any], info: Mapping[str, Any] | None) -> str | None:
    sources: Sequence[Mapping[str, Any]] = tuple(
        filter(None, (descriptor, info))  # type: ignore[arg-type]
    )
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("name", "gridName", "displayName", "DisplayName"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    fallback = descriptor.get("id") or descriptor.get("gridId")
    if fallback is not None:
        return f"Grid_{fallback}"
    return None


def _json_safe(value: Any, *, max_depth: int = 6) -> Any:
    """Convert arbitrary values to JSON-serialisable structures."""

    if max_depth <= 0:
        return str(value)

    if dataclasses.is_dataclass(value):
        return {
            key: _json_safe(val, max_depth=max_depth - 1)
            for key, val in dataclasses.asdict(value).items()
        }
    if isinstance(value, BaseDevice):
        return {
            "device_id": value.device_id,
            "device_type": value.device_type,
            "name": value.name,
            "enabled": value.is_enabled(),
            "telemetry": _json_safe(value.telemetry, max_depth=max_depth - 1),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(val, max_depth=max_depth - 1)
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _json_safe(item, max_depth=max_depth - 1)
            for item in value
        ]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _build_method_specs(
    cls: type,
    *,
    blacklist: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Collect method signatures and docstrings for a class."""

    specs: dict[str, dict[str, str]] = {}
    blocked = blacklist or set()
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_") or name in blocked:
            continue
        try:
            signature = str(inspect.signature(member))
        except (TypeError, ValueError):
            continue
        doc = inspect.getdoc(member) or "Описание недоступно."
        specs[name] = {"signature": signature, "doc": doc}
    return specs


_GRID_METHOD_SPECS = _build_method_specs(Grid, blacklist=_GRID_METHOD_BLACKLIST)
_BASE_DEVICE_METHOD_SPECS = _build_method_specs(BaseDevice, blacklist=_DEVICE_METHOD_BLACKLIST)
_DEVICE_METHOD_SPECS: dict[str, dict[str, dict[str, str]]] = {
    device_type: _build_method_specs(device_cls, blacklist=_DEVICE_METHOD_BLACKLIST)
    for device_type, device_cls in sorted(DEVICE_TYPE_MAP.items())
}


@contextmanager
def _grid_session(state: SessionState, grid_id: str) -> Iterator[Grid]:
    """Yield a temporary :class:`Grid` instance tied to the session."""

    owner = state.owner_id
    descriptor = {"id": grid_id}
    info = state.client.get_json(f"se:{owner}:grid:{grid_id}:gridinfo")
    name = _extract_grid_name(descriptor, info if isinstance(info, Mapping) else None)
    grid = Grid(state.client, owner, grid_id, state.player_id, name=name)
    try:
        yield grid
    finally:
        try:
            grid.close()
        except Exception:
            pass


def _describe_device(device: BaseDevice, *, include_metadata: bool, include_telemetry: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "device_id": device.device_id,
        "device_type": device.device_type,
        "name": device.name,
        "enabled": device.is_enabled(),
    }
    if include_metadata:
        data["metadata"] = _json_safe(device.metadata)
    if include_telemetry:
        data["telemetry"] = _json_safe(device.telemetry)
    return data


def _ensure_sequence(value: Any, *, name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    raise TypeError(f"Параметр {name} должен быть списком, получено {type(value).__name__}")


def _ensure_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Параметр {name} должен быть объектом с именованными аргументами")


def create_server() -> FastMCP:
    """Configure and return the FastMCP server instance."""

    server = FastMCP(name="secontrol-grid-server")

    def require_session(ctx: Context) -> SessionState:
        return _sessions.require(ctx.session_id)

    @server.tool(
        name="authenticate_redis",
        description=(
            "Подключается к Space Engineers Redis по логину и паролю. \n"
            "После успешной авторизации все остальные инструменты используют "
            "эту сессию. Параметр `player_id` опционален и по умолчанию равен "
            "логину."
        ),
    )
    def authenticate_redis(
        username: str,
        password: str,
        ctx: Context,
        redis_url: str | None = None,
        player_id: str | None = None,
    ) -> dict[str, Any]:
        client = RedisEventClient(url=redis_url, username=username, password=password)
        try:
            client.client.ping()
        except Exception as exc:  # pragma: no cover - network/redis error
            client.close()
            raise RuntimeError(f"Не удалось подключиться к Redis: {exc}") from exc

        resolved_player = player_id or username
        state = SessionState(client=client, owner_id=username, player_id=resolved_player, redis_url=redis_url)
        _sessions.set_session(ctx.session_id, state)
        return {
            "message": "Авторизация выполнена.",
            "owner_id": username,
            "player_id": resolved_player,
            "redis_url": redis_url,
        }

    @server.tool(
        name="disconnect_redis",
        description="Разрывает подключение Redis для текущей MCP-сессии.",
    )
    def disconnect_redis(ctx: Context) -> dict[str, Any]:
        cleared = _sessions.clear(ctx.session_id)
        if cleared:
            return {"message": "Подключение закрыто."}
        return {"message": "Активное подключение отсутствовало."}

    @server.tool(
        name="list_grids",
        description=(
            "Возвращает все доступные гриды для авторизованного владельца. "
            "Можно отключить фильтрацию суб-гридов и включить детальную информацию из `gridinfo`."
        ),
    )
    def list_grids(
        ctx: Context,
        include_subgrids: bool = False,
        include_info: bool = True,
    ) -> list[dict[str, Any]]:
        state = require_session(ctx)
        descriptors = state.client.list_grids(state.owner_id, exclude_subgrids=not include_subgrids)
        results: list[dict[str, Any]] = []
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping):
                continue
            grid_id = _extract_grid_id(descriptor)
            if grid_id is None:
                continue
            info: Mapping[str, Any] | None = None
            if include_info:
                raw_info = state.client.get_json(f"se:{state.owner_id}:grid:{grid_id}:gridinfo")
                if isinstance(raw_info, Mapping):
                    info = raw_info
            results.append(
                {
                    "grid_id": grid_id,
                    "name": _extract_grid_name(descriptor, info),
                    "descriptor": _json_safe(dict(descriptor)),
                    "gridinfo": _json_safe(dict(info)) if info else None,
                }
            )
        return results

    @server.tool(
        name="describe_grid_methods",
        description="Список всех поддерживаемых методов грида с сигнатурами и описанием.",
    )
    def describe_grid_methods() -> dict[str, dict[str, str]]:
        return _json_safe(_GRID_METHOD_SPECS)  # type: ignore[return-value]

    @server.tool(
        name="list_device_types",
        description="Перечисляет зарегистрированные типы устройств и количество методов для каждого.",
    )
    def list_device_types() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for device_type, specs in _DEVICE_METHOD_SPECS.items():
            items.append(
                {
                    "device_type": device_type,
                    "method_count": len(specs) + len(_BASE_DEVICE_METHOD_SPECS),
                }
            )
        return sorted(items, key=lambda item: item["device_type"])

    @server.tool(
        name="describe_device_methods",
        description=(
            "Возвращает список методов устройства. Можно указать `device_type` для конкретного типа,"
            " либо оставить пустым и получить базовые методы для всех устройств."
        ),
    )
    def describe_device_methods(device_type: str | None = None) -> dict[str, Any]:
        if device_type is None:
            return {
                "base": _json_safe(_BASE_DEVICE_METHOD_SPECS),
                "available_types": sorted(_DEVICE_METHOD_SPECS.keys()),
            }
        specs = _DEVICE_METHOD_SPECS.get(device_type)
        if specs is None:
            raise ValueError(f"Неизвестный тип устройства: {device_type}")
        return {
            "base": _json_safe(_BASE_DEVICE_METHOD_SPECS),
            "specific": _json_safe(specs),
        }

    @server.tool(
        name="get_grid_state",
        description=(
            "Загружает грид, возвращает метаданные, признаки суб-грида и краткую информацию по устройствам и блокам."
        ),
    )
    def get_grid_state(
        grid_id: str,
        ctx: Context,
        include_devices: bool = True,
        include_telemetry: bool = False,
        include_metadata: bool = False,
        include_blocks: bool = False,
    ) -> dict[str, Any]:
        state = require_session(ctx)
        with _grid_session(state, grid_id) as grid:
            grid_data: dict[str, Any] = {
                "grid_id": grid.grid_id,
                "name": grid.name,
                "is_subgrid": grid.is_subgrid,
                "metadata": _json_safe(grid.metadata) if include_metadata else None,
            }
            if include_devices:
                devices_summary = [
                    _describe_device(device, include_metadata=include_metadata, include_telemetry=include_telemetry)
                    for device in grid.devices.values()
                ]
                grid_data["devices"] = devices_summary
            if include_blocks:
                grid_data["blocks"] = _json_safe({bid: block for bid, block in grid.blocks.items()})
            else:
                grid_data["block_count"] = len(grid.blocks)
        return grid_data

    @server.tool(
        name="list_grid_devices",
        description="Возвращает устройства выбранного грида с опциональной телеметрией и метаданными.",
    )
    def list_grid_devices(
        grid_id: str,
        ctx: Context,
        include_metadata: bool = False,
        include_telemetry: bool = True,
    ) -> list[dict[str, Any]]:
        state = require_session(ctx)
        with _grid_session(state, grid_id) as grid:
            return [
                _describe_device(device, include_metadata=include_metadata, include_telemetry=include_telemetry)
                for device in grid.devices.values()
            ]

    @server.tool(
        name="get_device_snapshot",
        description=(
            "Возвращает состояние конкретного устройства (метаданные, телеметрия, флаги)."
        ),
    )
    def get_device_snapshot(
        grid_id: str,
        device_id: str,
        ctx: Context,
        include_metadata: bool = True,
        include_telemetry: bool = True,
    ) -> dict[str, Any]:
        state = require_session(ctx)
        with _grid_session(state, grid_id) as grid:
            device = grid.get_device_any(device_id)
            if device is None:
                raise ValueError(f"Устройство {device_id} не найдено на гриде {grid_id}")
            return _describe_device(device, include_metadata=include_metadata, include_telemetry=include_telemetry)

    @server.tool(
        name="call_grid_method",
        description=(
            "Вызывает любой метод грида из библиотеки `secontrol`. \n"
            "Передавайте позиционные аргументы в `args`, именованные в `kwargs`."
        ),
    )
    def call_grid_method(
        grid_id: str,
        method: str,
        ctx: Context,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if method in _GRID_METHOD_BLACKLIST or method.startswith("_"):
            raise ValueError(f"Метод {method} недоступен для удалённого вызова")
        if method not in _GRID_METHOD_SPECS:
            raise ValueError(
                f"Метод {method} не найден в списке поддерживаемых. Используйте describe_grid_methods()."
            )

        state = require_session(ctx)
        with _grid_session(state, grid_id) as grid:
            target = getattr(grid, method, None)
            if target is None or not callable(target):
                raise ValueError(f"Метод {method} отсутствует у грида")
            result = target(*_ensure_sequence(args, name="args"), **_ensure_mapping(kwargs, name="kwargs"))
            return {"result": _json_safe(result)}

    @server.tool(
        name="call_device_method",
        description=(
            "Вызывает метод устройства. Доступны как базовые методы (enable/disable и т.п.), "
            "так и специализированные для конкретного типа."
        ),
    )
    def call_device_method(
        grid_id: str,
        device_id: str,
        method: str,
        ctx: Context,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        include_metadata: bool = False,
        include_telemetry: bool = True,
    ) -> dict[str, Any]:
        if method in _DEVICE_METHOD_BLACKLIST or method.startswith("_"):
            raise ValueError(f"Метод {method} недоступен для удалённого вызова")

        state = require_session(ctx)
        with _grid_session(state, grid_id) as grid:
            device = grid.get_device_any(device_id)
            if device is None:
                raise ValueError(f"Устройство {device_id} не найдено на гриде {grid_id}")
            available = _DEVICE_METHOD_SPECS.get(device.device_type, {})
            if method not in available and method not in _BASE_DEVICE_METHOD_SPECS:
                raise ValueError(
                    f"Метод {method} не найден у устройства типа {device.device_type}. "
                    "Вызовите describe_device_methods для подсказки."
                )
            target = getattr(device, method, None)
            if target is None or not callable(target):
                raise ValueError(f"Метод {method} отсутствует у устройства")
            result = target(*_ensure_sequence(args, name="args"), **_ensure_mapping(kwargs, name="kwargs"))
            snapshot = _describe_device(device, include_metadata=include_metadata, include_telemetry=include_telemetry)
            return {"result": _json_safe(result), "device": snapshot}

    return server


def run() -> None:
    """Entry point for running the server via ``python -m``."""

    create_server().run()


if __name__ == "__main__":  # pragma: no cover - manual execution path
    run()
