"""Scan visible GPS/HUD markers, strong signals, beacons and antenna broadcasts.

Usage:
    python examples/organized/radar/basic/scan_visible_markers.py --grid skynet-farpost0
    python examples/organized/radar/basic/scan_visible_markers.py --grid agent1 --radius 50000
    python examples/organized/radar/basic/scan_visible_markers.py --grid agent1 --strong-only
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

from secontrol.common import close, prepare_grid
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice


def marker_position(marker: Dict[str, Any]) -> Optional[List[float]]:
    pos = marker.get("position")
    if isinstance(pos, dict):
        try:
            return [float(pos["x"]), float(pos["y"]), float(pos["z"])]
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(pos, (list, tuple)) and len(pos) >= 3:
        try:
            return [float(pos[0]), float(pos[1]), float(pos[2])]
        except (TypeError, ValueError):
            return None
    return None


def marker_name(marker: Dict[str, Any]) -> str:
    for key in ("name", "text", "description"):
        value = marker.get(key)
        if value not in (None, ""):
            return str(value)
    return f"id={marker.get('id', '?')}"


def filtered_markers(markers: Iterable[Dict[str, Any]], *, strong_only: bool) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        if strong_only and marker.get("type") != "strong_signal":
            continue
        result.append(marker)
    return result


def print_markers(markers: List[Dict[str, Any]]) -> None:
    if not markers:
        print("No visible markers found.")
        return

    print(f"\n{'=' * 110}")
    print(f"  RESULTS: {len(markers)} visible marker(s)")
    print(f"{'=' * 110}")
    print(f"  {'Type':<16} {'Source':<10} {'Distance':>10}  {'Position':<34} Name")
    print(f"  {'-' * 16} {'-' * 10} {'-' * 10}  {'-' * 34} {'-' * 30}")

    for marker in markers:
        pos = marker_position(marker)
        name = marker_name(marker)
        marker_type = str(marker.get("type", "?"))
        source = str(marker.get("source", "?"))
        try:
            distance = float(marker.get("distance"))
            distance_text = f"{distance:9.0f}m"
        except (TypeError, ValueError):
            distance_text = "?"

        if pos:
            position_text = f"({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})"
        else:
            position_text = "(no position)"

        print(f"  {marker_type:<16} {source:<10} {distance_text:>10}  {position_text:<34} {name}")


def _marker_revision_from_snapshot(snapshot: Dict[str, Any]) -> Optional[int]:
    try:
        return int(snapshot.get("revision"))
    except (TypeError, ValueError):
        return None


def _latest_marker_snapshot(radar: OreDetectorDevice) -> Dict[str, Any]:
    if hasattr(radar, "visible_markers_snapshot"):
        snapshot = radar.visible_markers_snapshot()
        if isinstance(snapshot, dict):
            return snapshot

    telemetry = getattr(radar, "telemetry", None) or {}
    visible_markers = telemetry.get("visibleMarkers")
    if isinstance(visible_markers, dict):
        return visible_markers

    radar_data = telemetry.get("radar")
    if isinstance(radar_data, dict) and isinstance(radar_data.get("markers"), list):
        return {"ready": True, "items": radar_data.get("markers", [])}

    return {}


def _send_raw_marker_scan(
    radar: OreDetectorDevice,
    *,
    radius: float,
    include_gps: bool,
    include_broadcasts: bool,
    include_entity_signals: bool,
    include_all_players: bool,
) -> int:
    if hasattr(radar, "scan_markers"):
        return radar.scan_markers(
            radius=radius,
            include_gps=include_gps,
            include_broadcasts=include_broadcasts,
            include_entity_signals=include_entity_signals,
            include_all_players=include_all_players,
        )

    state = {
        "includeGps": bool(include_gps),
        "includeBroadcasts": bool(include_broadcasts),
        "includeEntitySignals": bool(include_entity_signals),
        "includeAllPlayers": bool(include_all_players),
        "radius": float(radius),
    }
    payload = {
        "cmd": "scan_markers",
        "targetId": int(radar.device_id),
        "state": state,
    }
    name = getattr(radar, "name", None)
    if name:
        payload["targetName"] = name
    return radar.send_command(payload)


def scan_markers_compatible(
    controller: RadarController,
    radar: OreDetectorDevice,
    *,
    radius: float,
    include_gps: bool,
    include_broadcasts: bool,
    include_entity_signals: bool,
    include_all_players: bool,
    timeout: float,
) -> Dict[str, Any]:
    if hasattr(controller, "scan_markers"):
        snapshot = controller.scan_markers(
            radius=radius,
            include_gps=include_gps,
            include_broadcasts=include_broadcasts,
            include_entity_signals=include_entity_signals,
            include_all_players=include_all_players,
            timeout=timeout,
            return_snapshot=True,
        )
        return snapshot if isinstance(snapshot, dict) else {"ready": True, "items": snapshot}

    print("RadarController.scan_markers is missing; using raw scan_markers command fallback.")
    initial_snapshot = _latest_marker_snapshot(radar)
    initial_revision = _marker_revision_from_snapshot(initial_snapshot)

    seq = _send_raw_marker_scan(
        radar,
        radius=radius,
        include_gps=include_gps,
        include_broadcasts=include_broadcasts,
        include_entity_signals=include_entity_signals,
        include_all_players=include_all_players,
    )
    print(f"Marker scan sent, seq={seq}")

    start = time.time()
    snapshot: Dict[str, Any] = {}
    while time.time() - start < timeout:
        radar.update()
        if hasattr(radar, "wait_for_telemetry"):
            radar.wait_for_telemetry(timeout=0.5, wait_for_new=False, need_update=False)
        snapshot = _latest_marker_snapshot(radar)
        revision = _marker_revision_from_snapshot(snapshot)
        if snapshot.get("ready") and (initial_revision is None or revision != initial_revision):
            break
        time.sleep(0.1)

    if not snapshot:
        snapshot = _latest_marker_snapshot(radar)

    items = snapshot.get("items")
    markers = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    print(f"Markers found: total={len(markers)}, revision={snapshot.get('revision', 0)}")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan visible GPS/HUD markers and broadcast signals")
    parser.add_argument("--grid", default="skynet-farpost0", help="Grid name to scan from")
    parser.add_argument("--radius", type=float, default=20000.0, help="Scan radius in meters")
    parser.add_argument("--timeout", type=float, default=10.0, help="Telemetry wait timeout in seconds")
    parser.add_argument("--strong-only", action="store_true", help="Show only strong signal markers")
    parser.add_argument("--no-gps", action="store_true", help="Skip GPS/HUD markers")
    parser.add_argument("--no-broadcasts", action="store_true", help="Skip beacon and antenna broadcasts")
    parser.add_argument("--no-entity-signals", action="store_true", help="Skip loaded signal entities")
    parser.add_argument("--owner-only", action="store_true", help="Use only grid owner GPS, not all online players")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        radar = grid.get_first_device(OreDetectorDevice)
        print(f"Radar: {radar.name} (id={radar.device_id})")
        print(f"Scanning from: {grid.name} (id={grid.grid_id})")
        print(f"Radius: {args.radius:.0f}m")

        controller = RadarController(radar, radius=args.radius, cell_size=10, ore_only=False)
        snapshot = scan_markers_compatible(
            controller,
            radar,
            radius=args.radius,
            include_gps=not args.no_gps,
            include_broadcasts=not args.no_broadcasts,
            include_entity_signals=not args.no_entity_signals,
            include_all_players=not args.owner_only,
            timeout=args.timeout,
        )

        raw_items = snapshot.get("items") if isinstance(snapshot, dict) else []
        markers = filtered_markers(raw_items if isinstance(raw_items, list) else [], strong_only=args.strong_only)
        print_markers(markers)

        if isinstance(snapshot, dict):
            print(
                "\nCounters: "
                f"gps={snapshot.get('gpsCount', 0)}, "
                f"broadcasts={snapshot.get('broadcastCount', 0)}, "
                f"entitySignals={snapshot.get('entitySignalCount', 0)}, "
                f"identitySources={snapshot.get('identityCount', 0)}, "
                f"revision={snapshot.get('revision', 0)}"
            )
    finally:
        close(grid)


if __name__ == "__main__":
    main()
