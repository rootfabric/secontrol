"""Высокоуровневые утилиты для взаимодействия с Redis-шлюзом Space Engineers."""

from __future__ import annotations

from .base_device import BaseDevice, BlockInfo, DeviceMetadata, Grid, get_device_class
from .common import close, prepare_grid, resolve_grid_id, resolve_owner_id, resolve_player_id
from .redis_client import RedisEventClient

__all__ = [
    "BaseDevice",
    "BlockInfo",
    "DeviceMetadata",
    "Grid",
    "RedisEventClient",
    "close",
    "get_device_class",
    "prepare_grid",
    "resolve_grid_id",
    "resolve_owner_id",
    "resolve_player_id",
]

__version__ = "0.1.0"
