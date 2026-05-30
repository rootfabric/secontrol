#!/usr/bin/env python3
"""
=== DIRECT VECTOR FLIGHT CONTROLLER ===

Moves a Space Engineers grid to a target point using direct thruster override
and holds a requested grid orientation using gyros.

Important:
  - Remote Control autopilot is NOT used.
  - The ship can move sideways/backwards while keeping any requested angle.
  - Thruster telemetry must contain thrustDirection, or orientation.forward.

Basic usage:
  python direct_vector_flight.py skynet-agent0 --target -137351.2,-111183.2,-82062.6

Hold current angle and move to point:
  python direct_vector_flight.py skynet-agent0 --target -137351.2,-111183.2,-82062.6

Move 50m in current local backward direction, hold current angle:
  python direct_vector_flight.py skynet-agent0 --local-relative 0,0,-50

Move to point while forcing grid forward/up world vectors:
  python direct_vector_flight.py skynet-agent0 ^
    --target -137351.2,-111183.2,-82062.6 ^
    --forward -0.538,-0.736,-0.411 ^
    --up 0.734,-0.649,0.200

Move sideways to point while keeping nose pointed elsewhere:
  python direct_vector_flight.py skynet-agent0 ^
    --target -137351.2,-111183.2,-82062.6 ^
    --forward 0.538,0.736,0.411 ^
    --up 0.734,-0.649,0.200

Tuning examples:
  python direct_vector_flight.py skynet-agent0 --target X,Y,Z --max-speed 3 --max-thrust 25
  python direct_vector_flight.py skynet-agent0 --target X,Y,Z --pos-tolerance 1.5 --angle-tolerance-deg 3
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional

ENV_CANDIDATES = (
    "C:/secontrol/.env",
    "/workspace/.env",
    ".env",
)

SRC_CANDIDATES = (
    "C:/secontrol/src",
    "/workspace/src",
)

for env_path in ENV_CANDIDATES:
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

for src_path in SRC_CANDIDATES:
    if os.path.isdir(src_path) and src_path not in sys.path:
        sys.path.insert(0, src_path)

from secontrol.common import prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.thruster_device import ThrusterDevice
from secontrol.devices.gyro_device import GyroDevice


Vector3 = tuple[float, float, float]


@dataclass
class ThrusterInfo:
    device: ThrusterDevice
    direction: Vector3
    max_thrust: float
    source: str


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(v: Vector3) -> float:
    return math.sqrt(dot(v, v))


def normalize(v: Vector3) -> Vector3:
    size = length(v)
    if size <= 1e-10:
        return (0.0, 0.0, 0.0)
    return (v[0] / size, v[1] / size, v[2] / size)


def add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(v: Vector3, scalar: float) -> Vector3:
    return (v[0] * scalar, v[1] * scalar, v[2] * scalar)


def div(v: Vector3, scalar: float) -> Vector3:
    if abs(scalar) <= 1e-10:
        return (0.0, 0.0, 0.0)
    return (v[0] / scalar, v[1] / scalar, v[2] / scalar)


def project(v: Vector3, axis: Vector3) -> Vector3:
    unit = normalize(axis)
    return mul(unit, dot(v, unit))


def reject(v: Vector3, axis: Vector3) -> Vector3:
    return sub(v, project(v, axis))


def limit_vector(v: Vector3, max_len: float) -> Vector3:
    size = length(v)
    if size <= max_len or size <= 1e-10:
        return v
    return mul(v, max_len / size)


def angle_between(a: Vector3, b: Vector3) -> float:
    an = normalize(a)
    bn = normalize(b)
    value = clamp(dot(an, bn), -1.0, 1.0)
    return math.acos(value)


def parse_vec3(text: str) -> Vector3:
    cleaned = str(text).replace(";", ",").replace(" ", ",")
    parts = [p for p in cleaned.split(",") if p.strip()]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"expected 3 numbers, got: {text!r}")
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid vector: {text!r}") from exc


def parse_gps(text: str) -> Vector3:
    value = str(text).strip()
    if value.upper().startswith("GPS:"):
        value = value[4:]
    value = value.strip().strip(":")
    parts = value.split(":")
    if len(parts) >= 4:
        return (float(parts[-3]), float(parts[-2]), float(parts[-1]))
    return parse_vec3(value)


def vec_from_obj(value: object) -> Optional[Vector3]:
    if isinstance(value, dict):
        try:
            return (
                float(value.get("x", 0.0)),
                float(value.get("y", 0.0)),
                float(value.get("z", 0.0)),
            )
        except (TypeError, ValueError):
            return None

    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None

    if isinstance(value, str):
        try:
            return parse_vec3(value)
        except Exception:
            return None

    return None


def get_position(device) -> Optional[Vector3]:
    telemetry = device.telemetry or {}
    raw = telemetry.get("position") or telemetry.get("pos")
    if isinstance(raw, dict):
        try:
            return (float(raw["x"]), float(raw["y"]), float(raw["z"]))
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]))
        except (TypeError, ValueError):
            return None
    return None


def get_orientation_frame(rc: RemoteControlDevice) -> Optional[tuple[Vector3, Vector3, Vector3]]:
    telemetry = rc.telemetry or {}
    orientation = telemetry.get("orientation") or {}

    forward = vec_from_obj(orientation.get("forward")) or vec_from_obj(telemetry.get("forward"))
    up = vec_from_obj(orientation.get("up")) or vec_from_obj(telemetry.get("up"))
    right = (
        vec_from_obj(orientation.get("right"))
        or vec_from_obj(orientation.get("left"))
    )

    if forward is None or up is None:
        return None

    forward = normalize(forward)
    up = normalize(up)

    if right is None:
        right = normalize(cross(up, forward))
    else:
        right = normalize(right)
        # Older telemetry exposes "left". If the basis is left-handed here,
        # recompute right from forward/up instead of trusting the field blindly.
        expected_right = normalize(cross(up, forward))
        if dot(right, expected_right) < 0.0:
            right = expected_right

    if length(forward) <= 1e-8 or length(up) <= 1e-8 or length(right) <= 1e-8:
        return None

    # Re-orthogonalize so gyro math stays stable.
    right = normalize(cross(up, forward))
    up = normalize(cross(forward, right))
    return forward, up, right


def make_orientation(forward: Vector3, up_hint: Vector3) -> tuple[Vector3, Vector3, Vector3]:
    fwd = normalize(forward)
    if length(fwd) <= 1e-8:
        raise ValueError("desired forward vector must be non-zero")

    up = reject(up_hint, fwd)
    if length(up) <= 1e-8:
        raise ValueError("desired up vector must not be parallel to desired forward")

    up = normalize(up)
    right = normalize(cross(up, fwd))
    up = normalize(cross(fwd, right))
    return fwd, up, right


def get_thruster_direction(thruster: ThrusterDevice) -> tuple[Optional[Vector3], str]:
    telemetry = thruster.telemetry or {}

    direction = vec_from_obj(telemetry.get("thrustDirection"))
    if direction and length(direction) > 1e-8:
        return normalize(direction), "thrustDirection"

    orientation = telemetry.get("orientation") or {}
    forward = vec_from_obj(orientation.get("forward"))
    if forward and length(forward) > 1e-8:
        return normalize(mul(forward, -1.0)), "-orientation.forward"

    return None, "missing"


def get_max_thrust(thruster: ThrusterDevice) -> float:
    telemetry = thruster.telemetry or {}
    for key in ("maxThrust", "MaxThrust", "maxEffectiveThrust"):
        try:
            value = float(telemetry.get(key))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return 1.0


def refresh_devices(devices: Iterable[object], wait_seconds: float) -> None:
    for device in devices:
        try:
            device.update()
        except Exception:
            pass
    time.sleep(max(0.0, wait_seconds))


def wait_for_rc(rc: RemoteControlDevice, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            rc.update()
        except Exception:
            pass
        time.sleep(0.2)
        if get_position(rc) and get_orientation_frame(rc):
            return True
    return False


def build_thruster_infos(thrusters: list[ThrusterDevice], wait_seconds: float) -> list[ThrusterInfo]:
    refresh_devices(thrusters, wait_seconds)

    infos: list[ThrusterInfo] = []
    source_count: dict[str, int] = {}

    for thruster in thrusters:
        direction, source = get_thruster_direction(thruster)
        source_count[source] = source_count.get(source, 0) + 1
        if direction is None:
            continue
        infos.append(
            ThrusterInfo(
                device=thruster,
                direction=direction,
                max_thrust=get_max_thrust(thruster),
                source=source,
            )
        )

    print(
        "  Thruster direction sources: "
        + ", ".join(f"{key}={value}" for key, value in sorted(source_count.items()))
    )
    return infos


def set_thruster_override(thruster: ThrusterDevice, override_pct: float) -> None:
    value = clamp(float(override_pct), 0.0, 100.0)
    try:
        thruster.set_thrust(override=value, enabled=True)
    except Exception as exc:
        print(f"  WARN: failed to set thruster {thruster.name or thruster.device_id}: {exc}")


def clear_thrusters(thrusters: Iterable[ThrusterDevice]) -> None:
    for thruster in thrusters:
        try:
            thruster.set_thrust(override=0.0, enabled=True)
        except Exception:
            try:
                thruster.clear_override()
            except Exception:
                pass


def apply_force_vector(
    infos: list[ThrusterInfo],
    force_vector: Vector3,
    *,
    max_pct: float,
    min_dot: float,
    exponent: float,
) -> tuple[int, float]:
    magnitude = length(force_vector)
    if magnitude <= 1e-5:
        for info in infos:
            set_thruster_override(info.device, 0.0)
        return 0, 0.0

    direction = normalize(force_vector)
    active = 0
    max_sent = 0.0

    # Use all thrusters that can contribute to the requested world vector.
    # This allows diagonal movement and sideways flight.
    for info in infos:
        score = dot(info.direction, direction)
        if score <= min_dot:
            pct = 0.0
        else:
            pct = max_pct * (score ** exponent) * clamp(magnitude, 0.0, 1.0)

        if pct > 0.01:
            active += 1
            max_sent = max(max_sent, pct)

        set_thruster_override(info.device, pct)

    return active, max_sent


def clear_gyros(gyros: Iterable[GyroDevice]) -> None:
    for gyro in gyros:
        try:
            gyro.clear_override()
        except Exception:
            pass


def enable_gyros(gyros: Iterable[GyroDevice]) -> None:
    for gyro in gyros:
        try:
            gyro.enable()
        except Exception:
            pass


def apply_orientation_control(
    gyros: list[GyroDevice],
    current_frame: tuple[Vector3, Vector3, Vector3],
    desired_frame: tuple[Vector3, Vector3, Vector3],
    *,
    gain: float,
    max_cmd: float,
    deadband_rad: float,
    pitch_sign: float,
    yaw_sign: float,
    roll_sign: float,
) -> tuple[float, float, float, float]:
    current_forward, current_up, current_right = current_frame
    desired_forward, desired_up, _ = desired_frame

    forward_error = angle_between(current_forward, desired_forward)
    up_error = angle_between(current_up, desired_up)
    total_error = max(forward_error, up_error)

    if total_error < deadband_rad:
        clear_gyros(gyros)
        return total_error, 0.0, 0.0, 0.0

    # World rotation vector that moves current basis toward desired basis.
    # cross(current, desired) is the small-angle world rotation direction.
    error_world = add(
        cross(current_forward, desired_forward),
        cross(current_up, desired_up),
    )

    pitch_raw = -dot(error_world, current_right) * gain * pitch_sign
    yaw_raw = -dot(error_world, current_up) * gain * yaw_sign
    roll_raw = -dot(error_world, current_forward) * gain * roll_sign

    pitch = clamp(pitch_raw, -max_cmd, max_cmd)
    yaw = clamp(yaw_raw, -max_cmd, max_cmd)
    roll = clamp(roll_raw, -max_cmd, max_cmd)

    for gyro in gyros:
        try:
            gyro.set_override(pitch=pitch, yaw=yaw, roll=roll)
        except Exception as exc:
            print(f"  WARN: gyro command failed {gyro.name or gyro.device_id}: {exc}")

    return total_error, pitch, yaw, roll


def get_speed_vector(rc: RemoteControlDevice, previous_pos: Optional[Vector3], previous_time: Optional[float], previous_velocity: Vector3) -> Vector3:
    now = time.time()
    pos = get_position(rc)
    if not pos or previous_pos is None or previous_time is None:
        return previous_velocity

    dt = max(1e-3, now - previous_time)
    measured = div(sub(pos, previous_pos), dt)

    # Low-pass filtering reduces telemetry jitter.
    return add(mul(previous_velocity, 0.65), mul(measured, 0.35))


def get_current_speed(rc: RemoteControlDevice, velocity: Vector3) -> float:
    telemetry = rc.telemetry or {}
    for key in ("speed", "linearSpeed", "velocityLength"):
        try:
            value = float(telemetry.get(key))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return length(velocity)


def prepare_controls(rc: RemoteControlDevice, gyros: list[GyroDevice], thrusters: list[ThrusterDevice]) -> None:
    try:
        rc.disable()
    except Exception:
        pass
    try:
        rc.gyro_control_off()
    except Exception:
        pass
    try:
        rc.thrusters_on()
    except Exception:
        pass
    try:
        rc.dampeners_off()
    except Exception:
        pass

    enable_gyros(gyros)
    clear_gyros(gyros)
    clear_thrusters(thrusters)


def finish_controls(rc: RemoteControlDevice, gyros: list[GyroDevice], thrusters: list[ThrusterDevice], *, dampeners: bool = True) -> None:
    clear_thrusters(thrusters)
    clear_gyros(gyros)

    if dampeners:
        try:
            rc.dampeners_on()
        except Exception:
            pass

    try:
        rc.disable()
    except Exception:
        pass


def compute_target_position(args, current_pos: Vector3, current_frame: tuple[Vector3, Vector3, Vector3]) -> Vector3:
    current_forward, current_up, current_right = current_frame

    if args.target is not None:
        return args.target

    if args.gps is not None:
        return parse_gps(args.gps)

    if args.relative is not None:
        return add(current_pos, args.relative)

    if args.local_relative is not None:
        dx, dy, dz = args.local_relative
        world_delta = add(
            add(mul(current_right, dx), mul(current_up, dy)),
            mul(current_forward, dz),
        )
        return add(current_pos, world_delta)

    raise ValueError("target is required: use --target, --gps, --relative, or --local-relative")


def compute_desired_orientation(args, current_pos: Vector3, current_frame: tuple[Vector3, Vector3, Vector3]) -> tuple[Vector3, Vector3, Vector3]:
    current_forward, current_up, _ = current_frame

    if args.look_at is not None:
        desired_forward = normalize(sub(args.look_at, current_pos))
        if length(desired_forward) <= 1e-8:
            desired_forward = current_forward
    elif args.forward is not None:
        desired_forward = normalize(args.forward)
    else:
        desired_forward = current_forward

    desired_up = normalize(args.up) if args.up is not None else current_up
    return make_orientation(desired_forward, desired_up)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move a Space Engineers grid to a point by direct thruster and gyro control."
    )

    parser.add_argument("grid", help="Grid ID or grid name")

    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--target", type=parse_vec3, help="World target point: x,y,z")
    target_group.add_argument("--gps", help="GPS string: GPS:Name:X:Y:Z:")
    target_group.add_argument("--relative", type=parse_vec3, help="World relative movement vector: dx,dy,dz")
    target_group.add_argument("--local-relative", type=parse_vec3, help="Local relative movement vector: right,up,forward")

    parser.add_argument("--forward", type=parse_vec3, help="Desired world forward vector of the grid")
    parser.add_argument("--up", type=parse_vec3, help="Desired world up vector of the grid")
    parser.add_argument("--look-at", type=parse_vec3, help="Make grid forward look at this world point")

    parser.add_argument("--max-speed", type=float, default=4.0, help="Max travel speed, m/s")
    parser.add_argument("--slow-radius", type=float, default=25.0, help="Distance where speed is reduced")
    parser.add_argument("--pos-tolerance", type=float, default=1.5, help="Position tolerance, meters")
    parser.add_argument("--speed-tolerance", type=float, default=0.35, help="Stop speed tolerance, m/s")
    parser.add_argument("--angle-tolerance-deg", type=float, default=4.0, help="Orientation tolerance, degrees")

    parser.add_argument("--max-thrust", type=float, default=25.0, help="Max thruster override percent 0..100")
    parser.add_argument("--min-thrust-dot", type=float, default=0.10, help="Minimum thruster direction dot product")
    parser.add_argument("--thrust-exponent", type=float, default=1.35, help="Thruster distribution exponent")
    parser.add_argument("--pos-gain", type=float, default=0.45, help="Position-to-velocity gain")
    parser.add_argument("--vel-gain", type=float, default=0.22, help="Velocity error to force gain")

    parser.add_argument("--gyro-gain", type=float, default=1.6, help="Gyro orientation gain")
    parser.add_argument("--max-gyro", type=float, default=0.35, help="Max gyro override command 0..1")
    parser.add_argument("--pitch-sign", type=float, default=float(os.getenv("SE_GYRO_SIGN_PITCH", "-1")))
    parser.add_argument("--yaw-sign", type=float, default=float(os.getenv("SE_GYRO_SIGN_YAW", "-1")))
    parser.add_argument("--roll-sign", type=float, default=float(os.getenv("SE_GYRO_SIGN_ROLL", "-1")))

    parser.add_argument("--tick", type=float, default=0.35, help="Control loop interval")
    parser.add_argument("--timeout", type=float, default=240.0, help="Max control time, seconds")
    parser.add_argument("--telemetry-wait", type=float, default=1.5, help="Initial telemetry wait for thrusters")
    parser.add_argument("--dry-run", action="store_true", help="Print plan but do not move")
    parser.add_argument("--keep-dampeners-off", action="store_true", help="Do not enable dampeners at the end")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("=" * 72)
    print("DIRECT VECTOR FLIGHT CONTROLLER")
    print("=" * 72)

    print("\n[LOAD] Loading grid...")
    grid = prepare_grid(args.grid)
    time.sleep(1.0)

    rc = grid.get_first_device(RemoteControlDevice)
    thrusters = grid.find_devices_by_type(ThrusterDevice)
    gyros = grid.find_devices_by_type(GyroDevice)

    if rc is None:
        print("ERROR: no Remote Control found on grid")
        return 1
    if not thrusters:
        print("ERROR: no thrusters found on grid")
        return 1
    if not gyros:
        print("ERROR: no gyros found on grid")
        return 1

    print(f"  Grid: {grid.name} ({grid.grid_id})")
    print(f"  Remote Control: {rc.name or rc.device_id}")
    print(f"  Thrusters: {len(thrusters)}")
    print(f"  Gyros: {len(gyros)}")

    print("\n[INIT] Updating telemetry...")
    if not wait_for_rc(rc, timeout=5.0):
        print("ERROR: cannot read Remote Control position/orientation")
        return 1

    current_pos = get_position(rc)
    current_frame = get_orientation_frame(rc)

    if current_pos is None or current_frame is None:
        print("ERROR: incomplete Remote Control telemetry")
        return 1

    thruster_infos = build_thruster_infos(thrusters, args.telemetry_wait)
    if not thruster_infos:
        print("ERROR: no thruster direction telemetry found")
        print("Need thruster telemetry with thrustDirection or orientation.forward")
        return 1

    target_pos = compute_target_position(args, current_pos, current_frame)
    desired_frame = compute_desired_orientation(args, current_pos, current_frame)

    desired_forward, desired_up, _ = desired_frame

    print("\n[PLAN]")
    print(f"  Start:  ({current_pos[0]:.2f}, {current_pos[1]:.2f}, {current_pos[2]:.2f})")
    print(f"  Target: ({target_pos[0]:.2f}, {target_pos[1]:.2f}, {target_pos[2]:.2f})")
    print(f"  Distance: {length(sub(target_pos, current_pos)):.2f}m")
    print(f"  Desired forward: ({desired_forward[0]:.4f}, {desired_forward[1]:.4f}, {desired_forward[2]:.4f})")
    print(f"  Desired up:      ({desired_up[0]:.4f}, {desired_up[1]:.4f}, {desired_up[2]:.4f})")
    print(f"  Max speed: {args.max_speed:.2f}m/s")
    print(f"  Max thrust override: {args.max_thrust:.1f}%")
    print(f"  Max gyro command: {args.max_gyro:.2f}")

    print("\n[THRUSTERS] Top available direction groups:")
    top = sorted(
        thruster_infos,
        key=lambda item: dot(item.direction, normalize(sub(target_pos, current_pos))),
        reverse=True,
    )[:8]
    for item in top:
        score = dot(item.direction, normalize(sub(target_pos, current_pos)))
        print(
            f"  score={score:+.3f} source={item.source:>20} "
            f"id={item.device.device_id} name={item.device.name or ''}"
        )

    if args.dry_run:
        print("\n[DRY RUN] No movement commands were sent.")
        return 0

    print("\n[CONTROL] Starting direct control...")
    prepare_controls(rc, gyros, thrusters)

    previous_pos = current_pos
    previous_time = time.time()
    velocity: Vector3 = (0.0, 0.0, 0.0)
    started = time.time()
    last_print = 0.0

    try:
        while time.time() - started < args.timeout:
            loop_started = time.time()

            refresh_devices([rc], 0.02)
            pos = get_position(rc)
            frame = get_orientation_frame(rc)

            if pos is None or frame is None:
                print("  WARN: missing RC telemetry, waiting...")
                time.sleep(args.tick)
                continue

            now = time.time()
            velocity = get_speed_vector(rc, previous_pos, previous_time, velocity)
            previous_pos = pos
            previous_time = now

            to_target = sub(target_pos, pos)
            distance = length(to_target)
            direction_to_target = normalize(to_target) if distance > 1e-8 else (0.0, 0.0, 0.0)

            speed_limit = args.max_speed * clamp(distance / max(args.pos_tolerance, args.slow_radius), 0.12, 1.0)
            desired_velocity = mul(direction_to_target, speed_limit)

            velocity_error = sub(desired_velocity, velocity)
            force_vector = limit_vector(mul(velocity_error, args.vel_gain), 1.0)

            active_thrusters, max_sent_pct = apply_force_vector(
                thruster_infos,
                force_vector,
                max_pct=args.max_thrust,
                min_dot=args.min_thrust_dot,
                exponent=args.thrust_exponent,
            )

            orient_error, pitch, yaw, roll = apply_orientation_control(
                gyros,
                frame,
                desired_frame,
                gain=args.gyro_gain,
                max_cmd=args.max_gyro,
                deadband_rad=math.radians(args.angle_tolerance_deg * 0.35),
                pitch_sign=args.pitch_sign,
                yaw_sign=args.yaw_sign,
                roll_sign=args.roll_sign,
            )

            speed = get_current_speed(rc, velocity)
            elapsed = now - started

            if elapsed - last_print >= 1.0:
                print(
                    f"  [{elapsed:6.1f}s] "
                    f"dist={distance:7.2f}m "
                    f"speed={speed:5.2f}m/s "
                    f"angle={math.degrees(orient_error):5.2f}deg "
                    f"thr={active_thrusters:2d}/{len(thruster_infos)} "
                    f"maxPct={max_sent_pct:5.1f} "
                    f"gyro=({pitch:+.2f},{yaw:+.2f},{roll:+.2f})"
                )
                last_print = elapsed

            if (
                distance <= args.pos_tolerance
                and speed <= args.speed_tolerance
                and orient_error <= math.radians(args.angle_tolerance_deg)
            ):
                print("  Target reached.")
                break

            spent = time.time() - loop_started
            time.sleep(max(0.02, args.tick - spent))
        else:
            print("  WARN: timeout reached")

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] User stopped controller.")

    finally:
        print("\n[STOP] Clearing overrides...")
        finish_controls(
            rc,
            gyros,
            thrusters,
            dampeners=not args.keep_dampeners_off,
        )

    refresh_devices([rc], 0.5)
    final_pos = get_position(rc)
    if final_pos:
        final_dist = length(sub(target_pos, final_pos))
        print(f"  Final distance: {final_dist:.2f}m")

    print("[DONE]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
