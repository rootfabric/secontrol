"""Artillery device wrapper with weapon support."""

from __future__ import annotations

from secontrol.devices.weapon_device import WeaponDevice


class ArtilleryDevice(WeaponDevice):
    """Expose telemetry and commands for artillery weapons."""

    device_type = "artillery"
