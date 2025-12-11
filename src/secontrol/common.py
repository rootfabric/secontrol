"""Shared helpers for CLI utilities and examples_direct_connect."""

from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv

from .grids import Grid
from .redis_client import RedisEventClient

load_dotenv(find_dotenv(usecwd=True), override=False)


def _is_debug_enabled() -> bool:
    """Return True if debug prints should be enabled.

    Controlled by any of the env vars: SECONTROL_DEBUG, SE_DEBUG, SEC_DEBUG.
    Accepts 1/true/yes/on (case-insensitive).
    """
    import os as _os

    for name in ("SECONTROL_DEBUG", "SE_DEBUG", "SEC_DEBUG"):
        val = _os.getenv(name)
        if val is None:
            continue
        v = val.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
    return False


def resolve_owner_id() -> str:
    owner_id = os.getenv("REDIS_USERNAME")
    if not owner_id:
        raise RuntimeError(
            "Set the SE_OWNER_ID environment variable with your Space Engineers account id."
        )
    return owner_id


def resolve_player_id(owner_id: str) -> str:
    return os.getenv("SE_PLAYER_ID", owner_id)


def _is_subgrid(grid_info: dict) -> bool:
    """Best-effort detection whether a grid descriptor represents a sub-grid.

    Different Space Engineers bridges expose slightly different fields. We try several
    common markers and fall back to assuming it's a main grid when unsure.
    """
    if not isinstance(grid_info, dict):
        return False

    # 1) Explicit boolean flags
    for key in ("isSubgrid", "isSubGrid", "is_subgrid", "is_sub_grid"):
        val = grid_info.get(key)
        if isinstance(val, bool):
            return val is True
        if isinstance(val, (int, float)):
            return bool(val)

    # 2) Inverse of "isMainGrid" if present
    val = grid_info.get("isMainGrid")
    if isinstance(val, bool):
        return not val
    if isinstance(val, (int, float)):
        return not bool(val)

    # 3) Relationship by id: if main/root/top grid id differs from own id -> sub-grid
    own_id = grid_info.get("id")
    for rel in ("mainGridId", "rootGridId", "topGridId", "parentGridId", "parentId"):
        rel_id = grid_info.get(rel)
        if rel_id is not None and own_id is not None and str(rel_id) != str(own_id):
            return True

    # If no markers matched, treat as main grid
    return False


def get_all_grids(existing_client: RedisEventClient | str | None = None,
    grid_id: str | None = None, exclude_subgrids: bool = True) -> list[tuple[str, str]]:
    """Получить список всех гридов для owner_id.

    Возвращает список кортежей (grid_id, grid_name) для всех подходящих гридов.
    По умолчанию исключает суб-гриды.
    """
    if isinstance(existing_client, str) and grid_id is None:
        existing_client = None

    if isinstance(existing_client, RedisEventClient):
        client = existing_client
    else:
        client = RedisEventClient()

    owner_id = resolve_owner_id()

    grids = client.list_grids(owner_id, exclude_subgrids=False)
    if not grids:
        return []

    result = []
    for g in grids:
        grid_id = g.get("id")
        if not grid_id:
            continue
        grid_id = str(grid_id)

        # Получаем gridinfo для проверки суб-грида и имени
        gridinfo = {}
        if exclude_subgrids:
            gridinfo_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
            gridinfo = client.get_json(gridinfo_key) or {}

        # Проверяем, является ли суб-гридом
        is_sub = False
        if exclude_subgrids and isinstance(gridinfo, dict):
            is_sub = _is_subgrid(gridinfo)
        if exclude_subgrids and is_sub:
            continue

        # Извлекаем имя грида
        grid_name = None
        for source in (g, gridinfo):
            if not isinstance(source, dict):
                continue
            for key in ("name", "gridName", "displayName", "DisplayName"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    grid_name = value
                    break
            if grid_name:
                break
        if not grid_name:
            grid_name = f"Grid_{grid_id}"

        result.append((grid_id, grid_name))

    return result


def _resolve_grid_identifier(client: RedisEventClient, owner_id: str, identifier: str) -> str:
    """Resolve grid identifier which can be either ID or name."""
    # If identifier consists only of digits, treat as grid ID
    if identifier.isdigit():
        return identifier

    # Otherwise, treat as grid name and search for matching grid
    all_grids = get_all_grids(client, exclude_subgrids=True)
    matching_grids = [(gid, name) for gid, name in all_grids if name == identifier]

    # If no exact match, try partial case-insensitive match
    if not matching_grids:
        matching_grids = [(gid, name) for gid, name in all_grids if identifier.lower() in name.lower()]

    if not matching_grids:
        available_names = [name for _, name in all_grids]
        raise ValueError(
            f"No grid found containing '{identifier}' in name. Available grid names: {available_names}"
        )

    if len(matching_grids) > 1:
        grid_ids = [gid for gid, _ in matching_grids]
        matched_names = [name for _, name in matching_grids]
        raise ValueError(
            f"Multiple grids found containing '{identifier}': {matched_names} (IDs: {grid_ids}). Use a more specific name or grid ID."
        )

    grid_id, matched_name = matching_grids[0]
    return grid_id


def resolve_grid_id(client: RedisEventClient, owner_id: str) -> str:
    grid_id = os.getenv("SE_GRID_ID")
    if grid_id:
        return grid_id

    grids = client.list_grids(owner_id, exclude_subgrids=False)
    if not grids:
        raise RuntimeError(
            "No grids were found for the provided owner id. "
            "Run 'python -m secontrol.examples_direct_connect.list_grids' to inspect available grids."
        )

    # Take the first basic grid (non-subgrid), never fall back to sub-grids
    # Load detailed gridinfo for each grid to check isSubgrid flag
    non_sub = []
    for g in grids:
        grid_id = g.get("id")
        if not grid_id:
            continue
        gridinfo_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
        gridinfo = client.get_json(gridinfo_key)
        is_sub = False
        if isinstance(gridinfo, dict):
            is_sub = bool(gridinfo.get("isSubgrid"))
        # print(f"Grid {grid_id} {g.get('name')}: is_subgrid={is_sub}")
        if not is_sub:
            non_sub.append(g)
    if not non_sub:
        raise RuntimeError(
            "No basic grids (non-subgrids) were found for the provided owner id. "
            "Run 'python -m secontrol.examples_direct_connect.list_grids' to inspect available grids."
        )
    first_grid = non_sub[0]
    grid_id = str(first_grid.get("id"))
    if _is_debug_enabled():
        total = len(grids)
        filtered = len(non_sub)
        postfix = " (filtered sub-grids)" if non_sub else ""
        print(
            f"[examples_direct_connect] SE_GRID_ID is not set; using the first available grid{postfix}:",
            f"{grid_id} ({first_grid.get('name', 'unnamed')})",
            f"— candidates: {filtered}/{total}" if non_sub else f"— total: {total}",
        )
    print(f"Resolved grid: {grid_id} ({first_grid.get('name', 'unnamed')})",)
    return grid_id


def prepare_grid(
    existing_client: RedisEventClient | str | None = None,
    grid_id: str | None = None,
) -> Grid:
    """Создаёт и возвращает :class:`Grid` с готовыми подписками.

    Функция поддерживает несколько стилей вызова:

    - ``prepare_grid()`` — автоматический выбор грида.
    - ``prepare_grid("<grid_id>")`` — передача идентификатора грида первой позицией.
    - ``prepare_grid("<grid_name>")`` — передача имени грида первой позицией (поиск по имени).
    - ``prepare_grid(existing_client)`` — повторное использование готового :class:`RedisEventClient`.
    - ``prepare_grid(existing_client, grid_id)`` — явное указание грида при повторном использовании клиента.

    Возвращаемый объект ``Grid`` хранит ссылку на использованный ``RedisEventClient`` в поле
    :attr:`Grid.redis`. Если клиент был создан внутри ``prepare_grid``, вызов :func:`close`
    также закроет и Redis-подключение. При переданном внешнем клиенте ответственность за его
    закрытие остаётся на вызывающем коде.
    """

    if isinstance(existing_client, str) and grid_id is None:
        grid_id = existing_client
        existing_client = None

    owns_client = False
    if isinstance(existing_client, RedisEventClient):
        client = existing_client
    else:
        client = RedisEventClient()
        owns_client = True

    try:
        owner_id = resolve_owner_id()
        if grid_id is not None:
            resolved_grid_id = _resolve_grid_identifier(client, owner_id, grid_id)
            # Get the name for display
            all_grids = get_all_grids(client, exclude_subgrids=True)
            grid_name = next((name for gid, name in all_grids if gid == resolved_grid_id), f"Grid_{resolved_grid_id}")
            print(f"Resolved grid '{grid_id}' to: {resolved_grid_id} ({grid_name})")
        else:
            resolved_grid_id = resolve_grid_id(client, owner_id)
        player_id = resolve_player_id(owner_id)

        grid = Grid(client, owner_id, resolved_grid_id, player_id)
        setattr(grid, "_owns_redis_client", owns_client)
        return grid
    except Exception:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass
        raise


def close(grid: Grid) -> None:
    """Закрывает подписки грида и, при необходимости, Redis-подключение."""

    grid.close()
    owns_client = getattr(grid, "_owns_redis_client", True)
    if owns_client:
        try:
            grid.redis.close()
        except Exception:
            pass


__all__ = [
    "Grid",
    "RedisEventClient",
    "close",
    "get_all_grids",
    "prepare_grid",
    "resolve_grid_id",
    "resolve_owner_id",
    "resolve_player_id",
]
