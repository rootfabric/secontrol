"""Ore detector telemetry wrapper."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


def _cross(a: List[float], b: List[float]) -> List[float]:
    """Векторное произведение."""
    return [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]]


def _apply_quaternion(q: List[float], v: List[float]) -> List[float]:
    """Применить quaternion к вектору для поворота."""
    w, x, y, z = q
    qvec = [x, y, z]
    cross1 = _cross(qvec, v)
    cross2 = _cross(qvec, [c + w * vi for c, vi in zip(cross1, v)])
    return [v[0] + 2 * cross2[0], v[1] + 2 * cross2[1], v[2] + 2 * cross2[2]]


def _pick_radar_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Выбирает словарь радара из телеметрии, учитывая разные схемы."""
    rad = data.get("radar")
    if isinstance(rad, dict):
        return rad
    root_keys = set(data.keys())
    if {"contacts", "cellSize"} & root_keys:
        return data
    if {"contacts", "radius"} & root_keys:
        return data
    alt = data.get("voxel") or data.get("ore") or data.get("map")
    if isinstance(alt, dict):
        return alt
    return None


def _extract_ore_cells(radar: Dict[str, Any]) -> tuple[list[dict], int]:
    """Извлекает список ячеек руды и флаг усечения."""
    cells: list[dict] = []
    truncated = 0
    raw = radar.get("oreCells")
    if isinstance(raw, list):
        cells = [c for c in raw if isinstance(c, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("cells"), list):
        cells = [c for c in raw.get("cells", []) if isinstance(c, dict)]
    if not cells:
        for key in ("ore_cells", "cells", "ores"):
            alt = radar.get(key)
            if isinstance(alt, list):
                cells = [c for c in alt if isinstance(c, dict)]
                break
            if isinstance(alt, dict) and isinstance(alt.get("cells"), list):
                cells = [c for c in alt.get("cells", []) if isinstance(c, dict)]
                break
    trunc = radar.get("oreCellsTruncated")
    try:
        truncated = int(trunc) if trunc is not None else 0
    except (TypeError, ValueError):
        truncated = 0
    return cells, truncated


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
        include_voxels: bool = False,
        radius: Optional[float] = None,
        cell_size: Optional[float] = None,
        voxel_scan_hz: Optional[float] = None,
        voxel_step: Optional[int] = None,
        fullSolidScan: Optional[bool] = None,
        budget_ms_per_tick: Optional[float] = None,
        voxel_min_content: Optional[int] = None,
        contacts_hz: Optional[float] = None,
        full_scan_hz: Optional[float] = None,
        los_scan_hz: Optional[float] = None,
        max_los_rays_per_tick: Optional[int] = None,
        no_detector_cap_min: Optional[float] = None,
        no_detector_cap_max: Optional[float] = None,
        fast_scan: Optional[bool] = None,
        gridStep: Optional[float] = None,
        boundingBoxX: Optional[float] = None,
        boundingBoxY: Optional[float] = None,
        boundingBoxZ: Optional[float] = None,
        centerX: Optional[float] = None,
        centerY: Optional[float] = None,
        centerZ: Optional[float] = None,
        fastScanBudgetMs: Optional[float] = None,
        fastScanTileEdgeMax: Optional[float] = None,

    ) -> int:
        """Request a fresh radar scan from the ore detector with full config."""

        state: Dict[str, Any] = {
            "includePlayers": bool(include_players),
            "includeGrids": bool(include_grids),
            "includeVoxels": bool(include_voxels),
        }
        if radius is not None:
            state["radius"] = float(radius)
        if cell_size is not None:
            state["cellSize"] = float(cell_size)
        if voxel_scan_hz is not None:
            state["voxelScanHz"] = float(voxel_scan_hz)
        if voxel_step is not None:
            try:
                state["voxelStep"] = int(voxel_step)
            except (TypeError, ValueError):
                pass
        if fullSolidScan is not None:
            state["fullSolidScan"] = bool(fullSolidScan)

        if budget_ms_per_tick is not None:
            state["budgetMsPerTick"] = float(budget_ms_per_tick)
        if voxel_min_content is not None:
            try:
                state["voxelMinContent"] = int(voxel_min_content)
            except (TypeError, ValueError):
                pass
        if contacts_hz is not None:
            state["contactsHz"] = float(contacts_hz)
        if full_scan_hz is not None:
            state["fullScanHz"] = float(full_scan_hz)
        if los_scan_hz is not None:
            state["losScanHz"] = float(los_scan_hz)
        if max_los_rays_per_tick is not None:
            try:
                state["maxLosRaysPerTick"] = int(max_los_rays_per_tick)
            except (TypeError, ValueError):
                pass
        if no_detector_cap_min is not None:
            state["noDetectorCapMin"] = float(no_detector_cap_min)
        if no_detector_cap_max is not None:
            state["noDetectorCapMax"] = float(no_detector_cap_max)

        if fast_scan is not None:
            state["fast_scan"] = bool(fast_scan)
        if gridStep is not None:
            state["gridStep"] = float(gridStep)
        if fastScanBudgetMs is not None:
            state["fastScanBudgetMs"] = float(fastScanBudgetMs)
        if fastScanTileEdgeMax is not None:
            state["fastScanTileEdgeMax"] = float(fastScanTileEdgeMax)

        if boundingBoxX is not None:
            state["boundingBoxX"] = float(boundingBoxX)
        if boundingBoxY is not None:
            state["boundingBoxY"] = float(boundingBoxY)
        if boundingBoxZ is not None:
            state["boundingBoxZ"] = float(boundingBoxZ)
        if centerX is not None:
            state["boundingBoxX"] = float(centerX)
        if centerY is not None:
            state["boundingBoxY"] = float(centerY)
        if centerZ is not None:
            state["boundingBoxZ"] = float(centerZ)


        payload: Dict[str, Any] = {
            "cmd": "scan",
            "targetId": int(self.device_id),
            "state": state,
        }
        if self.name:
            payload["targetName"] = self.name
        print(payload)
        return self.send_command(payload)

    def cancel_scan(self) -> int:
        """Cancel the current radar scan."""
        payload: Dict[str, Any] = {
            "cmd": "scan",
            "targetId": int(self.device_id),
            "cancel": True,
        }
        if self.name:
            payload["targetName"] = self.name
        return self.send_command(payload)

    def monitor_ore(self, scan_interval: float = 10.0, config: Optional[Dict[str, Any]] = None):
        """Subscribe to telemetry and monitor ore updates, printing changes."""
        scan_config = config or {}

        client = getattr(self.grid, "redis", None)
        if client is None:
            raise RuntimeError("Redis client is not available for this device")

        print(f"Monitoring ore detector {self.device_id} named {self.name!r}")
        print(f"Telemetry key: {self.telemetry_key}")
        print(f"Scan interval: {scan_interval}s (Ctrl+C to exit)")

        last_rev: Optional[int] = None
        last_ore_count: Optional[int] = None
        pending_scan_seq: Optional[int] = None
        scan_answer_received = False

        answer_key = f"se:{self.grid.owner_id}:answer"

        def _on_answer(_key: str, payload: Any, event: str) -> None:
            nonlocal scan_answer_received, pending_scan_seq
            if event == "del":
                return
            data: Dict[str, Any] | None = None
            if isinstance(payload, dict):
                data = payload
            elif isinstance(payload, str):
                text = payload.strip()
                if text:
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = None

            if not isinstance(data, dict):
                return

            response_seq = data.get("seq")
            ok = data.get("ok", False)
            if response_seq == pending_scan_seq and ok:
                print(f"[ore detector] Scan response received for seq={response_seq}")
                scan_answer_received = True

        def _on_update(_device: "OreDetectorDevice", telemetry: Dict[str, Any], _source_event: str) -> None:
            nonlocal last_rev, last_ore_count, scan_answer_received
            print("Telemetry update received")  # Debug

            if not isinstance(telemetry, dict):
                return

            # Wait for scan answer before processing results
            if not scan_answer_received:
                print("[ore detector] Ignoring telemetry update until scan response")
                return

            radar = _pick_radar_dict(telemetry)
            ore_cells, _truncated = _extract_ore_cells(radar or {})

            rev_val = radar.get("revision") if radar else None
            try:
                rev = int(rev_val) if rev_val is not None else None
            except (TypeError, ValueError):
                rev = None

            ore_count_field = None
            try:
                ore_count_field = int(radar.get("oreCellCount")) if isinstance(radar, dict) and radar.get("oreCellCount") is not None else None
            except (TypeError, ValueError):
                ore_count_field = None

            contacts_count = len(radar.get("contacts", [])) if isinstance(radar, dict) else 0
            ore_effective = (ore_count_field if (ore_count_field is not None and not ore_cells) else len(ore_cells))

            last_rev = rev
            last_ore_count = ore_effective

            print(
                f"[ore detector] rev={rev}, contacts={contacts_count}, oreCells={ore_effective}"
            )

            if ore_cells:
                preview = []
                for c in ore_cells[:5]:
                    ore = c.get("ore") or c.get("material") or "?"
                    content = c.get("content")
                    idx = c.get("index")
                    preview.append(f"{ore}@{idx}:{content}")
                print(f"  Ores: {', '.join(preview)}{' (truncated)' if len(ore_cells) > 5 else ''}")
            elif ore_count_field:
                print(f"[ore detector] note: oreCells list missing, but oreCellCount={ore_count_field}")

        self.on("telemetry", _on_update)
        sub_answer = client.subscribe_to_key(answer_key, _on_answer)

        try:
            while True:
                scan_answer_received = False
                pending_scan_seq = self.scan(**scan_config)
                print(f"[ore detector] Sent scan command with seq={pending_scan_seq}, waiting for response...")
                # Wait for answer with timeout
                answer_timeout = 10.0  # seconds
                start_wait = time.time()
                while not scan_answer_received and (time.time() - start_wait) < answer_timeout:
                    time.sleep(0.1)
                if not scan_answer_received:
                    print(f"[ore detector] Timeout waiting for scan response, proceeding anyway")
                    scan_answer_received = True  # Continue anyway to not block indefinitely
                else:
                    print(f"[ore detector] Scan response confirmed, processing results")
                time.sleep(scan_interval)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                self.off("telemetry", _on_update)
            except Exception:
                pass
            try:
                sub_answer.close()
            except Exception:
                pass


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


DEVICE_TYPE_MAP[OreDetectorDevice.device_type] = OreDetectorDevice
