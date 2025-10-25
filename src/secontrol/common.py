"""Shared helpers for CLI utilities and examples_direct_connect."""

from __future__ import annotations

import os
from typing import Tuple

from dotenv import find_dotenv, load_dotenv

from .base_device import Grid
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


def resolve_grid_id(client: RedisEventClient, owner_id: str) -> str:
    grid_id = os.getenv("SE_GRID_ID")
    if grid_id:
        return grid_id

    grids = client.list_grids(owner_id)
    if not grids:
        raise RuntimeError(
            "No grids were found for the provided owner id. "
            "Run 'python -m secontrol.examples_direct_connect.list_grids' to inspect available grids."
        )

    first_grid = grids[0]
    grid_id = str(first_grid.get("id"))
    if _is_debug_enabled():
        print(
            "[examples_direct_connect] SE_GRID_ID is not set; using the first available grid:",
            f"{grid_id} ({first_grid.get('name', 'unnamed')})",
        )
    return grid_id


def prepare_grid(
    existing_client: RedisEventClient | str | None = None,
    grid_id: str | None = None,
) -> Tuple[RedisEventClient, Grid]:
    """Create :class:`RedisEventClient` and :class:`Grid` instances for examples_direct_connect.

    Parameters
    - existing_client: Optional pre-initialized :class:`RedisEventClient` instance to reuse.
      For convenience, you may also pass a ``str`` grid id here positionally, e.g.
      ``prepare_grid("<grid_id>")``.
    - grid_id: Optional grid id to target explicitly. When not provided, falls back to
      :func:`resolve_grid_id`, which uses ``SE_GRID_ID`` if set, otherwise the first grid.
    """

    # Allow calling styles:
    # - prepare_grid()                                 -> auto grid selection
    # - prepare_grid(grid_id)                          -> first positional is grid id
    # - prepare_grid(existing_client)                  -> reuse client
    # - prepare_grid(existing_client, grid_id)         -> reuse client and explicit grid
    # Normalize arguments accordingly.
    if isinstance(existing_client, str) and grid_id is None:
        grid_id = existing_client
        existing_client = None

    client = (existing_client if isinstance(existing_client, RedisEventClient) else None) or RedisEventClient()
    try:
        owner_id = resolve_owner_id()
        resolved_grid_id = grid_id or resolve_grid_id(client, owner_id)
        player_id = resolve_player_id(owner_id)

        grid = Grid(client, owner_id, resolved_grid_id, player_id)
        return client, grid
    except Exception:
        # Ensure we don't leak the client we created on failure
        if existing_client is None:
            try:
                client.close()
            except Exception:
                pass
        raise


def close(client: RedisEventClient, grid: Grid) -> None:
    """Close both the grid subscription and the Redis connection."""

    grid.close()
    client.close()


__all__ = [
    "Grid",
    "RedisEventClient",
    "close",
    "prepare_grid",
    "resolve_grid_id",
    "resolve_owner_id",
    "resolve_player_id",
]
