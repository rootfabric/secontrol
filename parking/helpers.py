"""Вспомогательные функции для парковки: математика, вектора, статус коннекторов."""

from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice
from secontrol.devices.connector_device import ConnectorDevice

# ---- Connector status constants ------------------------------------------
STATUS_UNCONNECTED = "Unconnected"
STATUS_READY_TO_LOCK = "Connectable"
STATUS_CONNECTED = "Connected"


# ---- Math helpers --------------------------------------------------------


def _vec(value: Sequence[float]) -> Tuple[float, float, float]:
    """Convert sequence to (x, y, z) tuple."""
    return float(value[0]), float(value[1]), float(value[2])


def _parse_vector(value: object) -> Optional[Tuple[float, float, float]]:
    """Parse vector from GPS string, dict or list/tuple."""
    if isinstance(value, str):
        parts = value.split(':')
        if len(parts) >= 5 and parts[0] == 'GPS':
            return float(parts[2]), float(parts[3]), float(parts[4])
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return _vec((value["x"], value["y"], value["z"]))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return _vec(value)
    return None


def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Normalize vector."""
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-6:
        return 0.0, 0.0, 1.0
    return v[0] / length, v[1] / length, v[2] / length


def _cross(a: Tuple[float, float, float],
           b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Cross product."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _add(a, b): return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _sub(a, b): return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _scale(v, s): return v[0] * s, v[1] * s, v[2] * s


def _dot(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class Basis:
    """Forward / Up / Right basis for a block in world space."""

    def __init__(self, forward: Tuple[float, float, float],
                 up: Tuple[float, float, float]):
        self.forward = _normalize(forward)
        raw_up = _normalize(up)
        right = _cross(self.forward, raw_up)
        self.right = _normalize(right)
        self.up = _normalize(_cross(self.right, self.forward))


# ---- Connector status functions ------------------------------------------


def get_connector_status(connector: ConnectorDevice) -> str:
    """Get current status of connector."""
    tel = connector.telemetry or {}
    return tel.get("connectorStatus") or "unknown"


def is_already_docked(connector: ConnectorDevice) -> bool:
    """Check if the connector is already docked (connected)."""
    status = get_connector_status(connector)
    return status == STATUS_CONNECTED


def is_parking_possible(connector: ConnectorDevice) -> bool:
    """Check if parking (docking) is possible on this connector."""
    status = get_connector_status(connector)
    return status in [STATUS_UNCONNECTED, STATUS_READY_TO_LOCK]
