"""Высокоуровневые утилиты для взаимодействия с Redis-шлюзом Space Engineers."""

from __future__ import annotations

# Import device module to register all device classes
from . import devices

from .base_device import BaseDevice, BlockInfo, DamageDetails, DamageSource, DeviceMetadata, get_device_class
from .common import close, get_all_grids, prepare_grid, resolve_grid_id, resolve_owner_id, resolve_player_id
from .grids import (
    DamageEvent,
    Grid,
    GridDevicesEvent,
    GridIntegrityChange,
    GridState,
    Grids,
    RemovedDeviceInfo,
)
from .redis_client import RedisEventClient
from ._version import __version__

__all__ = [
    "BaseDevice",
    "BlockInfo",
    "DamageDetails",
    "DamageEvent",
    "DamageSource",
    "DeviceMetadata",
    "GridDevicesEvent",
    "GridIntegrityChange",
    "Grid",
    "GridState",
    "Grids",
    "RedisEventClient",
    "RemovedDeviceInfo",
    "__version__",
    "close",
    "get_all_grids",
    "get_device_class",
    "prepare_grid",
    "resolve_grid_id",
    "resolve_owner_id",
    "resolve_player_id",
]
