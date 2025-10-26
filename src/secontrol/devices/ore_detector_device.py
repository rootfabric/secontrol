"""Ore detector telemetry wrapper."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class OreDetectorDevice(BaseDevice):
    """Expose voxel radar telemetry produced by ore detectors."""

    device_type = "ore_detector"

    def __init__(self, grid, metadata) -> None:  # noqa: D401 - BaseDevice initialises common state
        super().__init__(grid, metadata)
        self._radar: Dict[str, Any] | None = None
        self._contacts: List[Dict[str, Any]] = []
        self._ore_cells: List[Dict[str, Any]] = []
        self._ore_cells_truncated: int = 0

    def handle_telemetry(self, telemetry: Dict[str, Any]) -> None:
        self.telemetry = telemetry

        radar = telemetry.get("radar")
        if isinstance(radar, dict):
            self._radar = radar
            contacts = radar.get("contacts")
            if isinstance(contacts, list):
                self._contacts = [c for c in contacts if isinstance(c, dict)]
            else:
                self._contacts = []

            ore_cells = radar.get("oreCells")
            if isinstance(ore_cells, list):
                self._ore_cells = [c for c in ore_cells if isinstance(c, dict)]
            else:
                self._ore_cells = []

            truncated = radar.get("oreCellsTruncated")
            try:
                self._ore_cells_truncated = int(truncated)
            except (TypeError, ValueError):
                self._ore_cells_truncated = 0
        else:
            self._radar = None
            self._contacts = []
            self._ore_cells = []
            self._ore_cells_truncated = 0

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        return bool((self.telemetry or {}).get("enabled", False))

    def is_working(self) -> bool:
        return bool((self.telemetry or {}).get("isWorking", False))

    def broadcast(self) -> Optional[bool]:
        value = (self.telemetry or {}).get("broadcast")
        if isinstance(value, bool):
            return value
        return None

    def radar_snapshot(self) -> Dict[str, Any]:
        return dict(self._radar or {})

    def contacts(self) -> List[Dict[str, Any]]:
        return list(self._contacts)

    def ore_cells(self) -> List[Dict[str, Any]]:
        return list(self._ore_cells)

    def ore_cells_truncated(self) -> int:
        return self._ore_cells_truncated

    def scan_radius(self) -> Optional[float]:
        return _to_float((self._radar or {}).get("radius"))

    def cell_size(self) -> Optional[float]:
        return _to_float((self._radar or {}).get("cellSize"))

    def last_los_update(self) -> Optional[float]:
        return _to_float((self._radar or {}).get("lastLosUpdateSec"))

    def revision(self) -> Optional[int]:
        radar = self._radar or {}
        try:
            return int(radar.get("revision"))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def scan(
        self,
        *,
        include_players: bool = True,
        include_grids: bool = True,
        include_voxels: bool = True,
        radius: Optional[float] = None,
        cell_size: Optional[float] = None,
    ) -> int:
        """Request a fresh radar scan from the ore detector."""

        state: Dict[str, Any] = {
            "includePlayers": bool(include_players),
            "includeGrids": bool(include_grids),
            "includeVoxels": bool(include_voxels),
        }
        if radius is not None:
            state["radius"] = float(radius)
        if cell_size is not None:
            state["cellSize"] = float(cell_size)

        payload: Dict[str, Any] = {
            "cmd": "scan",
            "targetId": int(self.device_id),
            "state": state,
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


DEVICE_TYPE_MAP[OreDetectorDevice.device_type] = OreDetectorDevice
