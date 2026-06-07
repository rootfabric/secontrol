#!/usr/bin/env python3
"""Orbit a planet (default: Earth) by continuously re-issuing a tangent point ahead.

For each control tick the script reads the current ship position, projects it
onto the orbit circle around the planet center, then issues a single
``rc.goto`` to a point ``--arc-km`` ahead along the orbit arc. The autopilot
continuously chases that moving target, which produces a circular orbit.

This is a "lead pursuit" pattern: the target is always 10 km (configurable)
in front of the ship along the orbit circle, so the autopilot never stops at
the target — it keeps curving.

The orbit is computed in the equatorial (XY) plane. The Z coordinate of the
target is locked to the planet's center Z, so the ship naturally settles into
the equatorial plane on the first lap.

Earth is resolved automatically from the ore detector's celestial index by
matching the storage name ``EarthLike`` (case-insensitive). Override with
``--planet`` to orbit a different body.

Examples
--------
    # Dry run: compute one tangent point and exit.
    python examples/space_flight/orbit_earth.py --grid skynet-agent0 --dry-run

    # Orbit Earth at 50 km altitude, lead by 10 km, default CCW.
    python examples/space_flight/orbit_earth.py --grid skynet-agent0

    # Orbit at 80 km, lead by 5 km, clockwise, max 1 lap.
    python examples/space_flight/orbit_earth.py \\
        --grid skynet-agent0 --altitude-km 80 --arc-km 5 \\
        --direction cw --max-laps 1

    # Orbit the Moon (Europa in this server) at 20 km altitude.
    python examples/space_flight/orbit_earth.py \\
        --grid skynet-agent0 --planet Europa --altitude-km 20

Safety
------
* Docked grids are refused — undock first.
* The script aborts if no Remote Control is present or its telemetry is stale.
* After ``--stall-timeout`` seconds with no measurable position change the
  loop warns and continues; after ``--abort-timeout`` it stops.
* On exit, RC autopilot is left enabled so the user can take manual control
  with a single goto. Use ``--disable-autopilot-on-exit`` to turn it off.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, WORKSPACE)
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import close, prepare_grid  # noqa: E402
from secontrol.devices.connector_device import ConnectorDevice  # noqa: E402
from secontrol.devices.ore_detector_device import OreDetectorDevice  # noqa: E402
from secontrol.devices.remote_control_device import RemoteControlDevice  # noqa: E402
from secontrol.tools.navigation_tools import get_world_position  # noqa: E402


DEFAULT_GRID = "skynet-agent0"
DEFAULT_PLANET = "EarthLike"
CELESTIAL_TIMEOUT = 10.0
CELESTIAL_LIMIT = 64
TELEMETRY_TIMEOUT = 3.0
TICK_SECONDS = 2.0


def _parse_vector(value: Any) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        try:
            return (float(value["x"]), float(value["y"]), float(value["z"]))
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _speed_from_telemetry(tel: Dict[str, Any]) -> float:
    vec = _parse_vector(tel.get("velocity") or tel.get("linearVelocity"))
    if not vec:
        return 0.0
    return math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])


def request_celestial_index(
    radar: OreDetectorDevice,
    *,
    limit: int = CELESTIAL_LIMIT,
    timeout: float = CELESTIAL_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    prev = (radar.telemetry or {}).get("celestialIndex")
    prev_rev = prev.get("revision") if isinstance(prev, dict) else None
    radar.send_command({
        "cmd": "celestial",
        "targetId": int(radar.device_id),
        "state": {"limit": int(limit)},
    })
    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        idx = (radar.telemetry or {}).get("celestialIndex")
        if not isinstance(idx, dict):
            continue
        if idx.get("ready") and idx.get("revision") != prev_rev:
            return idx
    return None


def find_planet(
    celestial_index: Dict[str, Any],
    planet_hint: str,
) -> Optional[Dict[str, Any]]:
    """Pick the planet body that best matches the hint.

    Matching is case-insensitive substring against ``storageName`` and
    ``name``. If nothing matches, the first item with ``kind == "planet"`` is
    returned as a fallback.
    """
    items = celestial_index.get("items", []) or []
    if not items:
        return None
    hint_lc = planet_hint.lower()
    for item in items:
        for key in ("storageName", "name"):
            value = item.get(key) or ""
            if hint_lc in value.lower():
                return item
    for item in items:
        if item.get("kind") == "planet":
            return item
    return items[0]


def planet_center_radius(item: Dict[str, Any]) -> Optional[Tuple[Tuple[float, float, float], float]]:
    center = _parse_vector(item.get("center"))
    radius = item.get("approxRadius")
    if center is None or radius is None:
        return None
    try:
        return center, float(radius)
    except (TypeError, ValueError):
        return None


def get_rc(grid) -> Optional[RemoteControlDevice]:
    rc = grid.get_first_device(RemoteControlDevice)
    return rc if isinstance(rc, RemoteControlDevice) else None


def get_connected_connector(grid) -> Optional[Tuple[ConnectorDevice, Dict[str, Any]]]:
    connectors = grid.find_devices_by_type("connector") or []
    for conn in connectors:
        tel = conn.telemetry or {}
        status = (tel.get("status") or tel.get("connectionState") or "").lower()
        if "connected" in status and "disconnect" not in status:
            return conn, tel
    return None


def activate_rc(rc: RemoteControlDevice) -> None:
    rc.handbrake_off()
    rc.thrusters_on()
    rc.gyro_control_on()
    rc.dampeners_on()
    rc.ensure_ready_for_autopilot(timeout=TELEMETRY_TIMEOUT)
    rc.set_mode("oneway")
    rc.autopilot_enable()


def angle_in_orbit_plane(
    pos: Tuple[float, float, float],
    center: Tuple[float, float, float],
) -> float:
    """Project pos onto XY plane and return the equatorial angle around center."""
    return math.atan2(pos[1] - center[1], pos[0] - center[0])


def compute_tangent_target(
    pos: Tuple[float, float, float],
    center: Tuple[float, float, float],
    orbit_radius: float,
    arc_length: float,
    direction_sign: int,
) -> Tuple[float, float, float]:
    """Return a point ``arc_length`` ahead of ``pos`` along the orbit circle.

    The orbit lives in the equatorial (XY) plane; the target Z is locked to
    the planet center Z so the ship settles into the equatorial plane.
    """
    angle = angle_in_orbit_plane(pos, center)
    delta = (arc_length / orbit_radius) * direction_sign
    new_angle = angle + delta
    return (
        center[0] + orbit_radius * math.cos(new_angle),
        center[1] + orbit_radius * math.sin(new_angle),
        center[2],
    )


def format_gps(name: str, target: Tuple[float, float, float]) -> str:
    return f"GPS:{name}:{target[0]:.3f}:{target[1]:.3f}:{target[2]:.3f}:"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orbit a planet (default Earth) at a fixed altitude using lead pursuit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name (default: %(default)s)")
    parser.add_argument(
        "--planet",
        default=DEFAULT_PLANET,
        help="Planet storage-name substring (default: %(default)s). Try 'EarthLike', 'Moon', 'Mars', 'Europa'.",
    )
    parser.add_argument("--altitude-km", type=float, default=50.0, help="Orbit altitude above surface (km, default 50)")
    parser.add_argument("--arc-km", type=float, default=10.0, help="Lead distance in front of ship (km, default 10)")
    parser.add_argument("--direction", choices=("ccw", "cw"), default="ccw", help="Orbit direction (default ccw)")
    parser.add_argument("--max-speed", type=float, default=60.0, help="Autopilot max speed m/s (default 60)")
    parser.add_argument("--tick-seconds", type=float, default=TICK_SECONDS, help="Loop tick interval (s, default 2)")
    parser.add_argument("--max-laps", type=float, default=0.0, help="Stop after N laps (0 = unlimited, default 0)")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="Stop after N seconds (0 = unlimited, default 0)")
    parser.add_argument(
        "--stall-timeout",
        type=float,
        default=15.0,
        help="Warn after N seconds with no measurable position change (default 15)",
    )
    parser.add_argument(
        "--abort-timeout",
        type=float,
        default=60.0,
        help="Stop after N seconds with no measurable position change (default 60)",
    )
    parser.add_argument(
        "--safety-band-km",
        type=float,
        default=20.0,
        help="Abort if altitude deviates from target by more than this many km (default 20)",
    )
    parser.add_argument(
        "--disable-autopilot-on-exit",
        action="store_true",
        help="Turn RC autopilot off when the loop ends (default: leave it on so you can take over)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the first tangent target, print it and exit. Do not fly.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.altitude_km <= 0:
        raise SystemExit("--altitude-km must be > 0")
    if args.arc_km <= 0:
        raise SystemExit("--arc-km must be > 0")
    direction_sign = 1 if args.direction == "ccw" else -1
    orbit_radius = None
    orbit_altitude = args.altitude_km * 1000.0
    arc_length = args.arc_km * 1000.0

    grid = prepare_grid(args.grid)
    try:
        rc = get_rc(grid)
        if rc is None:
            raise SystemExit("Remote Control not found on the grid.")

        connected = get_connected_connector(grid)
        if connected is not None:
            conn, tel = connected
            other = tel.get("otherGridId") or tel.get("connectedToGridId")
            raise SystemExit(
                f"Grid is docked via connector {conn.name!r} (other grid id={other}). "
                "Undock before orbiting (use examples/organized/parking/smooth_undock.py)."
            )

        radar = grid.get_first_device(OreDetectorDevice)
        if radar is None:
            raise SystemExit("Ore detector not found on the grid (needed for celestial index).")

        print(f"Requesting celestial index from {radar.name}...")
        idx = request_celestial_index(radar)
        if idx is None:
            raise SystemExit("Celestial index request timed out.")
        planet_item = find_planet(idx, args.planet)
        if planet_item is None:
            raise SystemExit(f"No planet matching {args.planet!r} in celestial index.")
        parsed = planet_center_radius(planet_item)
        if parsed is None:
            raise SystemExit("Planet has no center/radius in celestial index.")
        center, planet_radius = parsed
        orbit_radius = planet_radius + orbit_altitude

        rc.wait_for_telemetry(timeout=TELEMETRY_TIMEOUT, wait_for_new=True, need_update=True)
        pos = get_world_position(rc)
        if pos is None:
            raise SystemExit("Remote Control has no position telemetry.")

        distance = math.sqrt(
            (pos[0] - center[0]) ** 2
            + (pos[1] - center[1]) ** 2
            + (pos[2] - center[2]) ** 2
        )
        current_altitude_km = (distance - planet_radius) / 1000.0

        target = compute_tangent_target(pos, center, orbit_radius, arc_length, direction_sign)
        circumference_km = 2.0 * math.pi * orbit_radius / 1000.0
        arc_deg = math.degrees(arc_length / orbit_radius)

        print()
        print("=" * 60)
        print("  Orbit plan")
        print("=" * 60)
        print(f"Planet:        {planet_item.get('name')}  storage={planet_item.get('storageName')}")
        print(f"Center:        ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})")
        print(f"Planet radius: {planet_radius / 1000.0:.2f} km")
        print(f"Orbit radius:  {orbit_radius / 1000.0:.2f} km  (altitude {args.altitude_km} km)")
        print(f"Circumference: {circumference_km:.1f} km  (1 lap)")
        print(f"Lead:          {args.arc_km} km = {arc_deg:.2f}°  direction={args.direction}")
        print(f"Max speed:     {args.max_speed} m/s")
        print(f"Ship:          ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
        print(f"Distance:      {distance / 1000.0:.2f} km  altitude {current_altitude_km:+.2f} km")
        print(f"First target:  ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        print(f"GPS:           {format_gps('OrbitLead', target)}")

        if args.dry_run:
            print()
            print("Dry run: not enabling autopilot, not flying.")
            return

        print()
        print("Enabling RC systems...")
        activate_rc(rc)

        lap_count = 0.0
        prev_angle = angle_in_orbit_plane(pos, center)
        last_motion_time = time.time()
        last_pos = pos
        start_time = time.time()
        target_name_index = 0
        last_log_time = 0.0
        orbit_targets_sent = 0
        stuck_since = None

        while True:
            now = time.time()
            if args.duration_sec > 0 and (now - start_time) >= args.duration_sec:
                print(f"\n[ORBIT] Duration limit reached ({args.duration_sec}s).")
                break
            if args.max_laps > 0 and lap_count >= args.max_laps:
                print(f"\n[ORBIT] Lap limit reached ({args.max_laps}).")
                break

            rc.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
            pos = get_world_position(rc)
            if pos is None:
                print("[ORBIT] WARN: no position telemetry; skipping tick.")
                time.sleep(args.tick_seconds)
                continue

            distance = math.sqrt(
                (pos[0] - center[0]) ** 2
                + (pos[1] - center[1]) ** 2
                + (pos[2] - center[2]) ** 2
            )
            altitude_km = (distance - planet_radius) / 1000.0
            if abs(altitude_km - args.altitude_km) > args.safety_band_km:
                print(
                    f"[ORBIT] ABORT: altitude {altitude_km:+.2f} km deviates from target "
                    f"{args.altitude_km} km by more than {args.safety_band_km} km."
                )
                break

            target = compute_tangent_target(pos, center, orbit_radius, arc_length, direction_sign)
            target_name_index += 1
            target_name = f"Orbit{args.altitude_km:.0f}km_{target_name_index:04d}"
            rc.goto(format_gps(target_name, target), speed=args.max_speed, gps_name=target_name)
            orbit_targets_sent += 1

            angle = angle_in_orbit_plane(pos, center)
            delta_angle = (angle - prev_angle) * direction_sign
            if delta_angle < -math.pi:
                delta_angle += 2.0 * math.pi
            elif delta_angle > math.pi:
                delta_angle -= 2.0 * math.pi
            if delta_angle > 0:
                lap_count += delta_angle / (2.0 * math.pi)
            prev_angle = angle

            moved = math.sqrt(
                (pos[0] - last_pos[0]) ** 2
                + (pos[1] - last_pos[1]) ** 2
                + (pos[2] - last_pos[2]) ** 2
            )
            if moved > 25.0:
                last_motion_time = now
                last_pos = pos
                stuck_since = None
            else:
                if stuck_since is None:
                    stuck_since = now
                stuck_for = now - stuck_since
                if stuck_for >= args.abort_timeout:
                    print(f"[ORBIT] ABORT: no motion for {stuck_for:.0f}s.")
                    break
                if stuck_for >= args.stall_timeout and (now - last_log_time) > 5.0:
                    print(
                        f"[ORBIT] WARN: no motion for {stuck_for:.0f}s "
                        f"(position delta last tick {moved:.1f} m)."
                    )
                    last_log_time = now

            speed = _speed_from_telemetry(rc.telemetry or {})
            if (now - last_log_time) > 5.0:
                elapsed = now - start_time
                print(
                    f"[ORBIT] t={elapsed:6.0f}s  laps={lap_count:.3f}  "
                    f"alt={altitude_km:+6.2f} km  speed={speed:5.1f} m/s  "
                    f"pos=({pos[0]:7.0f},{pos[1]:7.0f},{pos[2]:7.0f})  "
                    f"targets={orbit_targets_sent}"
                )
                last_log_time = now

            time.sleep(args.tick_seconds)

        if args.disable_autopilot_on_exit:
            rc.autopilot_disable()

        elapsed = time.time() - start_time
        print()
        print("=" * 60)
        print("  Orbit summary")
        print("=" * 60)
        print(f"Laps completed:    {lap_count:.3f}")
        print(f"Targets issued:    {orbit_targets_sent}")
        print(f"Elapsed:           {elapsed:.0f}s")
        print(f"Last position:     {pos}")
        print(f"Autopilot state:   {'disabled' if args.disable_autopilot_on_exit else 'still ON — take over manually'}")
    except KeyboardInterrupt:
        print("\n[ORBIT] Interrupted by user.")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
