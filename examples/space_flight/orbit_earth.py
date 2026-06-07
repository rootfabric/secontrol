#!/usr/bin/env python3
"""Orbit a planet by continuously re-issuing a lead GPS point.

The simple and reliable mode is --center-distance-km:
    orbit_radius = requested distance from the planet center

This mode does not use approxRadius, surfaceDistance or altitude heuristics.
It is useful when the API-reported planet radius does not match the visible
terrain radius in Space Engineers.

Examples
--------
    # Put the orbit lead target exactly 140 km from Earth's center.
    python examples/space_flight/orbit_earth.py --grid skynet-scout2 --center-distance-km 140

    # Dry run: only print the first GPS point and its center distance.
    python examples/space_flight/orbit_earth.py --grid skynet-scout2 --center-distance-km 140 --dry-run

    # Legacy mode: altitude over a resolved surface radius.
    python examples/space_flight/orbit_earth.py --grid skynet-scout2 --altitude-km 20

    # Default behavior: GPS markers are updated every 5 km, not every tick.
    python examples/space_flight/orbit_earth.py --grid skynet-scout2 --center-distance-km 140

    # Coarser RC goto targets too: update both marker and goto target every 5 km.
    python examples/space_flight/orbit_earth.py --grid skynet-scout2 \
        --center-distance-km 140 --goto-step-km 5
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

Vec3 = Tuple[float, float, float]


def parse_vector(value: Any) -> Optional[Vec3]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return float(value[0]), float(value[1]), float(value[2])
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        try:
            return float(value["x"]), float(value["y"]), float(value["z"])
        except (KeyError, TypeError, ValueError):
            return None

    return None


def optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def vec_sub(a: Vec3, b: Vec3) -> Vec3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def vec_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_len(v: Vec3) -> float:
    return math.sqrt(vec_dot(v, v))


def vec_norm(v: Vec3, label: str = "vector") -> Vec3:
    length = vec_len(v)
    if length <= 1e-9:
        raise ValueError(f"{label} has zero length")
    return v[0] / length, v[1] / length, v[2] / length


def axis_vector(axis: str) -> Vec3:
    if axis == "x":
        return 1.0, 0.0, 0.0
    if axis == "y":
        return 0.0, 1.0, 0.0
    return 0.0, 0.0, 1.0


def distance_from_center(pos: Vec3, center: Vec3) -> float:
    return vec_len(vec_sub(pos, center))


def speed_from_telemetry(tel: Dict[str, Any]) -> float:
    velocity = parse_vector(tel.get("velocity") or tel.get("linearVelocity"))
    if velocity is None:
        return 0.0
    return vec_len(velocity)


def format_gps(name: str, target: Vec3) -> str:
    return f"GPS:{name}:{target[0]:.3f}:{target[1]:.3f}:{target[2]:.3f}:"


def request_celestial_index(
    radar: OreDetectorDevice,
    *,
    limit: int = CELESTIAL_LIMIT,
    timeout: float = CELESTIAL_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    previous = (radar.telemetry or {}).get("celestialIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command({
        "cmd": "celestial",
        "targetId": int(radar.device_id),
        "state": {"limit": int(limit)},
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        index = (radar.telemetry or {}).get("celestialIndex")
        if not isinstance(index, dict):
            continue
        if index.get("ready") and index.get("revision") != previous_revision:
            return index

    return None


def find_planet(celestial_index: Dict[str, Any], planet_hint: str) -> Optional[Dict[str, Any]]:
    items = celestial_index.get("items", []) or []
    if not items:
        return None

    hint = planet_hint.lower()
    for item in items:
        for key in ("storageName", "name"):
            value = item.get(key) or ""
            if hint in value.lower():
                return item

    for item in items:
        if item.get("kind") == "planet":
            return item

    return items[0]


def planet_center_radius(item: Dict[str, Any]) -> Optional[Tuple[Vec3, float]]:
    center = parse_vector(item.get("center"))
    radius = optional_float(item.get("approxRadius"))
    if center is None or radius is None:
        return None
    return center, radius


def resolve_surface_radius(
    *,
    api_approx_radius: float,
    api_surface_distance: Optional[float],
    current_distance: float,
    radius_source: str,
    override_radius_km: Optional[float],
) -> Tuple[float, str, Optional[float]]:
    if override_radius_km is not None:
        return override_radius_km * 1000.0, "manual --planet-radius-km", None

    implied_radius: Optional[float] = None
    if api_surface_distance is not None:
        candidate = current_distance - api_surface_distance
        if candidate > 1000.0:
            implied_radius = candidate

    if radius_source == "approx-radius":
        return api_approx_radius, "API approxRadius", implied_radius

    if radius_source == "surface-distance" and implied_radius is None:
        raise SystemExit(
            "--radius-source surface-distance was requested, but celestial "
            "surfaceDistance is missing or invalid."
        )

    if implied_radius is not None:
        return implied_radius, "API surfaceDistance", implied_radius

    return api_approx_radius, "API approxRadius fallback", implied_radius


def get_rc(grid) -> Optional[RemoteControlDevice]:
    rc = grid.get_first_device(RemoteControlDevice)
    return rc if isinstance(rc, RemoteControlDevice) else None


def get_connected_connector(grid) -> Optional[Tuple[ConnectorDevice, Dict[str, Any]]]:
    connectors = grid.find_devices_by_type("connector") or []
    for connector in connectors:
        telemetry = connector.telemetry or {}
        status = (telemetry.get("status") or telemetry.get("connectionState") or "").lower()
        if "connected" in status and "disconnect" not in status:
            return connector, telemetry
    return None


def activate_rc(rc: RemoteControlDevice) -> None:
    rc.handbrake_off()
    rc.thrusters_on()
    rc.gyro_control_on()
    rc.dampeners_on()
    rc.ensure_ready_for_autopilot(timeout=TELEMETRY_TIMEOUT)
    rc.set_mode("oneway")
    rc.autopilot_enable()


def angle_in_xy(pos: Vec3, center: Vec3) -> float:
    return math.atan2(pos[1] - center[1], pos[0] - center[0])


def compute_tangent_target(
    pos: Vec3,
    center: Vec3,
    orbit_radius: float,
    arc_length: float,
    direction_sign: int,
    orbit_normal_axis: str,
) -> Vec3:
    """Return a lead target exactly on the sphere with radius ``orbit_radius``.

    This function never uses the surface radius and never forces z=center.z.
    The returned target is guaranteed, up to floating-point error, to satisfy:
        distance(target, center) == orbit_radius
    """
    if orbit_radius <= 0.0:
        raise ValueError("orbit_radius must be positive")

    radial = vec_norm(vec_sub(pos, center), "radial vector")
    normal = axis_vector(orbit_normal_axis)
    tangent = vec_cross(normal, radial)

    if vec_len(tangent) <= 1e-6:
        fallback_axis = "y" if orbit_normal_axis != "y" else "x"
        tangent = vec_cross(axis_vector(fallback_axis), radial)

    tangent = vec_norm(tangent, "tangent vector")
    delta = direction_sign * arc_length / orbit_radius
    cos_delta = math.cos(delta)
    sin_delta = math.sin(delta)

    target_unit = vec_norm(
        (
            radial[0] * cos_delta + tangent[0] * sin_delta,
            radial[1] * cos_delta + tangent[1] * sin_delta,
            radial[2] * cos_delta + tangent[2] * sin_delta,
        ),
        "target radial vector",
    )

    return (
        center[0] + target_unit[0] * orbit_radius,
        center[1] + target_unit[1] * orbit_radius,
        center[2] + target_unit[2] * orbit_radius,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orbit a planet. Prefer --center-distance-km for exact radius from planet center.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name (default: %(default)s)")
    parser.add_argument(
        "--planet",
        default=DEFAULT_PLANET,
        help="Planet storage-name substring (default: %(default)s).",
    )
    parser.add_argument(
        "--center-distance-km",
        "--orbit-radius-km",
        dest="center_distance_km",
        type=float,
        default=None,
        help=(
            "Exact orbit radius from the planet center in km. "
            "This overrides --altitude-km, --planet-radius-km and --radius-source."
        ),
    )
    parser.add_argument(
        "--altitude-km",
        type=float,
        default=50.0,
        help="Legacy mode: orbit altitude above selected surface radius in km (default 50).",
    )
    parser.add_argument(
        "--planet-radius-km",
        type=float,
        default=None,
        help="Legacy mode: manual surface radius in km.",
    )
    parser.add_argument(
        "--radius-source",
        choices=("auto", "surface-distance", "approx-radius"),
        default="auto",
        help="Legacy mode: source for surface radius (default: %(default)s).",
    )
    parser.add_argument("--arc-km", type=float, default=10.0, help="Lead distance in front of ship in km (default 10).")
    parser.add_argument(
        "--goto-step-km",
        type=float,
        default=0.0,
        help=(
            "Minimum ship travel before sending the next RC goto target in km. "
            "0 means every tick (default, smoother autopilot). Use 5 for coarse 5 km target spacing."
        ),
    )
    parser.add_argument(
        "--marker-step-km",
        type=float,
        default=5.0,
        help=(
            "Minimum ship travel before updating the visible lead GPS marker in km "
            "(default 5). Use 0 for every tick."
        ),
    )
    parser.add_argument("--direction", choices=("ccw", "cw"), default="ccw", help="Orbit direction (default ccw).")
    parser.add_argument(
        "--orbit-normal",
        choices=("x", "y", "z"),
        default="z",
        help="Global axis used as orbit normal for the 3D lead point (default z).",
    )
    parser.add_argument("--max-speed", type=float, default=500.0, help="Autopilot max speed in m/s (default 60).")
    parser.add_argument("--tick-seconds", type=float, default=TICK_SECONDS, help="Loop tick interval in seconds.")
    parser.add_argument("--max-laps", type=float, default=0.0, help="Stop after N laps (0 = unlimited).")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="Stop after N seconds (0 = unlimited).")
    parser.add_argument(
        "--safety-band-km",
        type=float,
        default=2.0,
        help="Abort if radius/altitude deviates from target by more than this many km after reaching band (default 2).",
    )
    parser.add_argument("--stall-timeout", type=float, default=15.0, help="Warn after N seconds with no motion.")
    parser.add_argument("--abort-timeout", type=float, default=60.0, help="Abort after N seconds with no motion.")
    parser.add_argument("--disable-autopilot-on-exit", action="store_true", help="Turn RC autopilot off on exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print the first target and exit without flying.")
    parser.add_argument(
        "--mark-flyby",
        dest="mark_flyby",
        action="store_true",
        default=True,
        help="Create/update GPS markers (default: enabled).",
    )
    parser.add_argument("--no-mark-flyby", dest="mark_flyby", action="store_false", help="Disable GPS markers.")
    parser.add_argument(
        "--flyby-color",
        default="0,200,255",
        help="RGB color for GPS markers, format R,G,B (default cyan).",
    )
    return parser


def parse_rgb(value: str) -> Tuple[int, int, int]:
    try:
        parts = [int(float(part)) for part in value.replace(";", ",").split(",")]
        if len(parts) != 3:
            raise ValueError("expected three values")
        return tuple(max(0, min(255, part)) for part in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        print(f"[ORBIT] WARN: invalid --flyby-color {value!r}; using default cyan.")
        return 0, 200, 255


def main() -> None:
    args = build_parser().parse_args()

    if args.center_distance_km is not None and args.center_distance_km <= 0.0:
        raise SystemExit("--center-distance-km must be > 0")
    if args.center_distance_km is None and args.altitude_km <= 0.0:
        raise SystemExit("--altitude-km must be > 0")
    if args.arc_km <= 0.0:
        raise SystemExit("--arc-km must be > 0")
    if args.goto_step_km < 0.0:
        raise SystemExit("--goto-step-km must be >= 0")
    if args.marker_step_km < 0.0:
        raise SystemExit("--marker-step-km must be >= 0")
    if args.max_speed <= 0.0:
        raise SystemExit("--max-speed must be > 0")
    if args.tick_seconds <= 0.0:
        raise SystemExit("--tick-seconds must be > 0")
    if args.safety_band_km <= 0.0:
        raise SystemExit("--safety-band-km must be > 0")

    direction_sign = 1 if args.direction == "ccw" else -1
    arc_length = args.arc_km * 1000.0
    goto_step_m = args.goto_step_km * 1000.0
    marker_step_m = args.marker_step_km * 1000.0
    center_distance_mode = args.center_distance_km is not None

    grid = prepare_grid(args.grid)
    try:
        if args.mark_flyby and not hasattr(grid, "create_gps_marker"):
            print("[ORBIT] WARN: grid object has no create_gps_marker(); disabling markers.")
            args.mark_flyby = False

        flyby_rgb = parse_rgb(args.flyby_color)

        rc = get_rc(grid)
        if rc is None:
            raise SystemExit("Remote Control not found on the grid.")

        connected = get_connected_connector(grid)
        if connected is not None:
            connector, telemetry = connected
            other_grid_id = telemetry.get("otherGridId") or telemetry.get("connectedToGridId")
            raise SystemExit(
                f"Grid is docked via connector {connector.name!r} (other grid id={other_grid_id}). "
                "Undock before orbiting."
            )

        radar = grid.get_first_device(OreDetectorDevice)
        if radar is None:
            raise SystemExit("Ore detector not found on the grid (needed for celestial index).")

        print(f"Requesting celestial index from {radar.name}...")
        celestial_index = request_celestial_index(radar)
        if celestial_index is None:
            raise SystemExit("Celestial index request timed out.")

        planet_item = find_planet(celestial_index, args.planet)
        if planet_item is None:
            raise SystemExit(f"No planet matching {args.planet!r} in celestial index.")

        parsed = planet_center_radius(planet_item)
        if parsed is None:
            raise SystemExit("Planet has no center/radius in celestial index.")

        center, api_approx_radius = parsed
        api_surface_distance = optional_float(planet_item.get("surfaceDistance"))

        rc.wait_for_telemetry(timeout=TELEMETRY_TIMEOUT, wait_for_new=True, need_update=True)
        pos = get_world_position(rc)
        if pos is None:
            raise SystemExit("Remote Control has no position telemetry.")

        ship_center_distance = distance_from_center(pos, center)

        if center_distance_mode:
            surface_radius: Optional[float] = None
            surface_source = "not used"
            orbit_radius = float(args.center_distance_km) * 1000.0
            radial_error_km = (ship_center_distance - orbit_radius) / 1000.0
            orbit_label = f"R{orbit_radius / 1000.0:.0f}km"
        else:
            surface_radius, surface_source, _ = resolve_surface_radius(
                api_approx_radius=api_approx_radius,
                api_surface_distance=api_surface_distance,
                current_distance=ship_center_distance,
                radius_source=args.radius_source,
                override_radius_km=args.planet_radius_km,
            )
            orbit_radius = surface_radius + args.altitude_km * 1000.0
            radial_error_km = (ship_center_distance - orbit_radius) / 1000.0
            orbit_label = f"{args.altitude_km:.0f}km"

        if orbit_radius <= 1000.0:
            raise SystemExit("Resolved orbit radius is unrealistically small.")

        target = compute_tangent_target(
            pos,
            center,
            orbit_radius,
            arc_length,
            direction_sign,
            args.orbit_normal,
        )
        target_center_distance = distance_from_center(target, center)
        target_range = distance_from_center(target, pos)
        circumference_km = 2.0 * math.pi * orbit_radius / 1000.0
        arc_deg = math.degrees(arc_length / orbit_radius)

        print()
        print("=" * 60)
        print("  Orbit plan  [center-distance-coarse-markers-v2]")
        print("=" * 60)
        print(f"Planet:        {planet_item.get('name')}  storage={planet_item.get('storageName')}")
        print(f"Center:        ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})")
        print(f"API approxRadius:       {api_approx_radius / 1000.0:.2f} km")
        if api_surface_distance is not None:
            implied_surface_radius = ship_center_distance - api_surface_distance
            print(f"API surfaceDistance:    {api_surface_distance / 1000.0:+.2f} km")
            print(f"API implied surface:    {implied_surface_radius / 1000.0:.2f} km")
        else:
            print("API surfaceDistance:    unavailable")

        if center_distance_mode:
            print("Mode:                  center distance, no surface math")
            print(f"Requested center dist: {orbit_radius / 1000.0:.2f} km")
        else:
            assert surface_radius is not None
            print(f"Mode:                  altitude over selected surface")
            print(f"Selected surface:      {surface_radius / 1000.0:.2f} km  source={surface_source}")
            print(f"Requested altitude:    {args.altitude_km:.2f} km")
            print(f"Requested center dist: {orbit_radius / 1000.0:.2f} km")

        print(f"Ship center distance: {ship_center_distance / 1000.0:.2f} km")
        print(f"Ship radius error:    {radial_error_km:+.2f} km")
        print(f"Orbit circumference:  {circumference_km:.1f} km")
        print(f"Lead:                 {args.arc_km:.2f} km = {arc_deg:.2f}°  direction={args.direction}")
        print(
            f"Goto update step:     "
            f"{'every tick' if args.goto_step_km <= 0.0 else f'{args.goto_step_km:.2f} km'}"
        )
        print(
            f"Marker update step:   "
            f"{'every tick' if args.marker_step_km <= 0.0 else f'{args.marker_step_km:.2f} km'}"
        )
        print(f"Orbit normal:         global {args.orbit_normal.upper()} axis")
        print(f"Max speed:            {args.max_speed:.1f} m/s")
        print(f"Ship:                 ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
        print(f"First target:         ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        print(f"Target center dist:   {target_center_distance / 1000.0:.2f} km")
        print(f"Target radius error:  {(target_center_distance - orbit_radius) / 1000.0:+.6f} km")
        print(f"Target range:         {target_range / 1000.0:.2f} km from ship")
        print(f"GPS:                  {format_gps('OrbitLead', target)}")

        if args.mark_flyby:
            print(
                f"Flyby markers: enabled  (color RGB={flyby_rgb})\n"
                f"               lead marker:     'OrbitLead_{orbit_label}_{args.direction.upper()}'\n"
                f"               per-lap flyby:   'FlybyNNN_{orbit_label}_{args.direction.upper()}'"
            )
        else:
            print("Flyby markers: disabled (--no-mark-flyby)")

        if args.dry_run:
            print()
            print("Dry run: not enabling autopilot, not flying.")
            return

        print()
        print("Enabling RC systems...")
        activate_rc(rc)

        lap_count = 0.0
        previous_angle = angle_in_xy(pos, center)
        last_pos = pos
        start_time = time.time()
        last_log_time = 0.0
        stuck_since: Optional[float] = None
        target_index = 0
        targets_sent = 0
        lead_marker_updates = 0
        last_goto_update_pos: Optional[Vec3] = None
        last_marker_update_pos: Optional[Vec3] = None
        last_marked_lap = 0
        flyby_markers_created = 0
        reached_orbit_band = abs(radial_error_km) <= args.safety_band_km

        if not reached_orbit_band:
            low = orbit_radius / 1000.0 - args.safety_band_km
            high = orbit_radius / 1000.0 + args.safety_band_km
            print(
                f"[ORBIT] Ship center distance {ship_center_distance / 1000.0:.2f} km is outside "
                f"orbit band [{low:.2f}, {high:.2f}] km."
            )
            print("[ORBIT] Flying toward lead points on the requested center-distance sphere.")

        while True:
            now = time.time()
            if args.duration_sec > 0.0 and now - start_time >= args.duration_sec:
                print(f"\n[ORBIT] Duration limit reached ({args.duration_sec}s).")
                break
            if args.max_laps > 0.0 and lap_count >= args.max_laps:
                print(f"\n[ORBIT] Lap limit reached ({args.max_laps}).")
                break

            rc.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
            pos = get_world_position(rc)
            if pos is None:
                print("[ORBIT] WARN: no position telemetry; skipping tick.")
                time.sleep(args.tick_seconds)
                continue

            ship_center_distance = distance_from_center(pos, center)
            radial_error_km = (ship_center_distance - orbit_radius) / 1000.0

            target = compute_tangent_target(
                pos,
                center,
                orbit_radius,
                arc_length,
                direction_sign,
                args.orbit_normal,
            )

            should_send_goto = (
                last_goto_update_pos is None
                or goto_step_m <= 0.0
                or distance_from_center(pos, last_goto_update_pos) >= goto_step_m
            )
            if should_send_goto:
                target_index += 1
                target_name = f"Orbit{orbit_label}_{target_index:04d}"
                rc.goto(format_gps(target_name, target), speed=args.max_speed, gps_name=target_name)
                targets_sent += 1
                last_goto_update_pos = pos

            if args.mark_flyby:
                should_update_marker = (
                    last_marker_update_pos is None
                    or marker_step_m <= 0.0
                    or distance_from_center(pos, last_marker_update_pos) >= marker_step_m
                )
                if should_update_marker:
                    lead_marker_name = f"OrbitLead_{orbit_label}_{args.direction.upper()}"
                    try:
                        grid.create_gps_marker(lead_marker_name, coordinates=target, rgb=flyby_rgb)
                        lead_marker_updates += 1
                        last_marker_update_pos = pos
                    except Exception as exc:  # noqa: BLE001
                        print(f"[ORBIT] WARN: failed to create lead GPS marker {lead_marker_name!r}: {exc}")

            deviation = abs(radial_error_km)
            if not reached_orbit_band and deviation <= args.safety_band_km:
                reached_orbit_band = True
                print(
                    f"\n[ORBIT] Reached orbit band at center distance "
                    f"{ship_center_distance / 1000.0:.2f} km (error {radial_error_km:+.2f} km)."
                )
            elif reached_orbit_band and deviation > args.safety_band_km:
                print(
                    f"[ORBIT] ABORT: center distance {ship_center_distance / 1000.0:.2f} km "
                    f"drifted from target {orbit_radius / 1000.0:.2f} km by more than "
                    f"{args.safety_band_km:.2f} km."
                )
                break

            angle = angle_in_xy(pos, center)
            delta_angle = (angle - previous_angle) * direction_sign
            if delta_angle < -math.pi:
                delta_angle += 2.0 * math.pi
            elif delta_angle > math.pi:
                delta_angle -= 2.0 * math.pi
            if delta_angle > 0.0:
                lap_count += delta_angle / (2.0 * math.pi)
            previous_angle = angle

            full_lap = int(lap_count)
            if full_lap > last_marked_lap and full_lap >= 1:
                flyby_name = f"Flyby{full_lap:03d}_{orbit_label}_{args.direction.upper()}"
                if args.mark_flyby:
                    try:
                        grid.create_gps_marker(flyby_name, coordinates=pos, rgb=flyby_rgb)
                        flyby_markers_created += 1
                        print(
                            f"[ORBIT] Flyby #{full_lap} marker dropped at "
                            f"({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f}) name={flyby_name!r}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"[ORBIT] WARN: failed to create GPS marker {flyby_name!r}: {exc}")
                else:
                    print(f"[ORBIT] Flyby #{full_lap} at ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
                last_marked_lap = full_lap

            moved = distance_from_center(pos, last_pos)
            if moved > 25.0:
                last_pos = pos
                stuck_since = None
            else:
                if stuck_since is None:
                    stuck_since = now
                stuck_for = now - stuck_since
                if stuck_for >= args.abort_timeout:
                    print(f"[ORBIT] ABORT: no motion for {stuck_for:.0f}s.")
                    break
                if stuck_for >= args.stall_timeout and now - last_log_time > 5.0:
                    print(f"[ORBIT] WARN: no motion for {stuck_for:.0f}s (position delta {moved:.1f} m).")
                    last_log_time = now

            speed = speed_from_telemetry(rc.telemetry or {})
            if now - last_log_time > 5.0:
                elapsed = now - start_time
                print(
                    f"[ORBIT] t={elapsed:6.0f}s  laps={lap_count:.3f}  "
                    f"r={ship_center_distance / 1000.0:7.2f} km  "
                    f"err={radial_error_km:+6.2f} km  speed={speed:5.1f} m/s  "
                    f"pos=({pos[0]:7.0f},{pos[1]:7.0f},{pos[2]:7.0f})  "
                    f"targets={targets_sent}  leadMarkers={lead_marker_updates}"
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
        print(f"Targets issued:    {targets_sent}")
        print(f"Lead marker updates: {lead_marker_updates}")
        print(f"Flyby markers:     {flyby_markers_created}")
        print(f"Elapsed:           {elapsed:.0f}s")
        print(f"Last position:     {pos}")
        print(f"Target radius:     {orbit_radius / 1000.0:.2f} km from center")
        print(f"Autopilot state:   {'disabled' if args.disable_autopilot_on_exit else 'still ON — take over manually'}")
        if args.mark_flyby:
            marker_policy = "updated every tick" if args.marker_step_km <= 0.0 else f"updated every {args.marker_step_km:.2f} km"
            print(f"Lead marker:       OrbitLead_{orbit_label}_{args.direction.upper()} ({marker_policy})")

    except KeyboardInterrupt:
        print("\n[ORBIT] Interrupted by user.")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
