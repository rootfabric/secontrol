"""Shared helpers for CLI utilities and examples_direct_connect."""

from __future__ import annotations

import os
from typing import Tuple

from dotenv import find_dotenv, load_dotenv

from .base_device import Grid
from .redis_client import RedisEventClient

load_dotenv(find_dotenv(usecwd=True), override=False)


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
    print(
        "[examples_direct_connect] SE_GRID_ID is not set; using the first available grid:",
        f"{grid_id} ({first_grid.get('name', 'unnamed')})",
    )
    return grid_id


def prepare_grid(existing_client: RedisEventClient | None = None) -> Tuple[RedisEventClient, Grid]:
    """Create :class:`RedisEventClient` and :class:`Grid` instances for examples_direct_connect."""

    client = existing_client or RedisEventClient()
    owner_id = resolve_owner_id()
    grid_id = resolve_grid_id(client, owner_id)
    player_id = resolve_player_id(owner_id)

    grid = Grid(client, owner_id, grid_id, player_id)
    return client, grid


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
