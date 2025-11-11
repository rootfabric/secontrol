"""Device registry and discovery helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Iterable

try:  # Python 3.10+
    from importlib.metadata import entry_points
except ImportError:  # pragma: no cover - Python <3.10 compatibility
    from importlib_metadata import entry_points  # type: ignore

from secontrol.base_device import DEVICE_TYPE_MAP

# Import rover device
from .rover_device import RoverDevice


__all__ = [
    "DEVICE_TYPE_MAP",
    "load_builtin_devices",
    "load_external_plugins",
    "RoverDevice",
]

_BUILTIN_MODULES = [
    "ai_device",
    "assembler_device",
    "battery_device",
    "cockpit_device",
    "connector_device",
    "container_device",
    "conveyor_sorter_device",
    "display_device",
    "gas_generator_device",
    "gyro_device",
    "lamp_device",
    "large_turret_device",
    "projector_device",
    "reactor_device",
    "refinery_device",
    "remote_control_device",
    "ship_drill_device",
    "ship_grinder_device",
    "ship_tool_device",
    "ship_welder_device",
    "thruster_device",
    "weapon_device",
    "wheel_device",
]

_loaded_builtin = False


def load_builtin_devices() -> None:
    """Import bundled device modules so they register themselves."""

    global _loaded_builtin
    if _loaded_builtin:
        return
    for module in _BUILTIN_MODULES:
        import_module(f"{__name__}.{module}")
    _loaded_builtin = True


def load_external_plugins(groups: Iterable[str] | None = None) -> None:
    """Load additional device plugins via entry points."""

    selected_groups = tuple(groups or ("secontrol.devices",))
    eps = entry_points()
    for group in selected_groups:
        for entry_point in eps.select(group=group):
            entry_point.load()


# Ensure built-in devices are registered by default.
load_builtin_devices()

