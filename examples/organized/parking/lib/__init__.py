"""Модуль парковки и стыковки дронов/кораблей.

Комплексное решение для автоматической парковки:
- Вычисление точки парковки по геометрии коннекторов
- Пошаговый подлёт к базе
- Точная стыковка через iterative approach
- Проверка статуса коннекторов
- Управление парковкой грида
"""

from __future__ import annotations

from .helpers import (
    _vec, _parse_vector, _normalize, _cross, _add, _sub, _scale, _dot, _dist,
    Basis,
    get_connector_status,
    is_already_docked,
    is_parking_possible,
    STATUS_UNCONNECTED, STATUS_READY_TO_LOCK, STATUS_CONNECTED,
)
from .docking import (
    DockingConfig,
    DockingResult,
    calculate_park_point,
    fly_to,
    dock_by_connector_vector,
    final_approach_and_dock,
    try_dock,
    dock_procedure,
)
from .parking import (
    park_grid,
    unpark_grid,
    prepare_for_parking,
    finalize_parking,
    undock_ship,
)
from .calc_point import (
    calculate_connector_forward_point,
    calculate_connector_forward_point_by_name,
)

__all__ = [
    # Helpers
    "_vec", "_parse_vector", "_normalize", "_cross", "_add", "_sub", "_scale", "_dot", "_dist",
    "Basis",
    "get_connector_status",
    "is_already_docked",
    "is_parking_possible",
    "STATUS_UNCONNECTED", "STATUS_READY_TO_LOCK", "STATUS_CONNECTED",
    # Docking
    "DockingConfig",
    "DockingResult",
    "calculate_park_point",
    "fly_to",
    "dock_by_connector_vector",
    "try_dock",
    "dock_procedure",
    # Parking
    "park_grid",
    "unpark_grid",
    "prepare_for_parking",
    "finalize_parking",
    "undock_ship",
    # Calc point
    "calculate_connector_forward_point",
    "calculate_connector_forward_point_by_name",
]
