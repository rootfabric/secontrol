#!/usr/bin/env python3
"""
Space Navigator v2 — gyro+thruster manual flight (no autopilot needed).

Flies to nearest asteroid using:
- Gyro override for orientation (point ship at target)
- Thruster override for acceleration
- Cockpit for position/velocity telemetry and dampeners
- Forward voxel beam for obstacle detection

Stops 200m before asteroid surface.
"""
import argparse, json, math, os, sys, time, threading
from typing import Optional, Tuple, List, Dict, Any

WORKSPACE = "/workspace"
# Don't add /workspace/src to path — use pip-installed secontrol (has latest ore_only support)
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import prepare_grid, close
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.thruster_device import ThrusterDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position, get_orientation, _dist, _normalize, _dot, _cross

# ── Config ─────────────────────────────────────────────────────────────
DEFAULT_GRID       = "skynet-baza0"
CRUISE_SPEED       = 20.0     # m/s target cruise
SLOW_SPEED         = 3.0      # m/s approach speed
STOP_DISTANCE      = 200.0    # m before asteroid surface
BEAM_X, BEAM_Y, BEAM_Z = 50, 50, 1000  # forward beam (voxel cells)
CELL_SIZE          = 5.0      # m per cell
OBSTACLE_THRESHOLD = 3        # min solid points to trigger
SCAN_INTERVAL      = 1.5      # seconds

# PD controller gains (tuned for large grid heavy ship)
ORIENT_KP = 1.5    # proportional gain (match align_to_up_vector pattern)
ORIENT_KD = 0.0    # no derivative — pure P controller
THRUST_KP = 0.5    # proportional gain for thrust
MAX_THRUST = 1.0   # max thruster override (0-1)
MAX_ANGULAR = 1.0  # max gyro override (match align_to_up_vector max_rate)


# ── Asteroid finder ────────────────────────────────────────────────────

def find_nearest_asteroid(radar: OreDetectorDevice, timeout=15.0) -> Optional[Dict]:
    radar.send_command({
        "cmd": "asteroids", "targetId": int(radar.device_id),
        "state": {"radius": 50000.0, "limit": 320, "includePlanets": False},
    })
    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.update()
        idx = (radar.telemetry or {}).get("asteroidIndex")
        if isinstance(idx, dict) and idx.get("ready"):
            items = idx.get("items", [])
            valid = [a for a in items if a.get("distance") is not None]
            if valid:
                return min(valid, key=lambda a: float(a.get("distance", 1e12)))
        time.sleep(0.5)
    return None


def compute_approach_point(ship_pos, asteroid, stop_dist=200.0):
    center = asteroid.get("center", [])
    ast = (float(center[0]), float(center[1]), float(center[2]))
    radius = float(asteroid.get("approxRadius", 50.0))
    dx, dy, dz = ast[0]-ship_pos[0], ast[1]-ship_pos[1], ast[2]-ship_pos[2]
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    if dist < 1e-3:
        return ast
    d = (dx/dist, dy/dist, dz/dist)
    approach_dist = max(0, dist - radius - stop_dist)
    return (ship_pos[0]+d[0]*approach_dist,
            ship_pos[1]+d[1]*approach_dist,
            ship_pos[2]+d[2]*approach_dist)


# ── Forward scanner ────────────────────────────────────────────────────

class ForwardScanner:
    def __init__(self, radar: OreDetectorDevice):
        self.radar = radar
        self._obstacle = False
        self._count = 0
        self._lock = threading.Lock()
        self._running = False

    @property
    def obstacle_detected(self) -> bool:
        with self._lock: return self._obstacle

    @property
    def solid_count(self) -> int:
        with self._lock: return self._count

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        ctrl = RadarController(
            self.radar,
            radius=float(BEAM_Z) * CELL_SIZE,
            cell_size=CELL_SIZE,
            boundingBoxX=BEAM_X, boundingBoxY=BEAM_Y, boundingBoxZ=BEAM_Z,
            fullSolidScan=True, ore_only=False, filter_no_stone=True,
        )
        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
                n = len(solid) if solid else 0
                with self._lock:
                    self._count = n
                    self._obstacle = n >= OBSTACLE_THRESHOLD
                if self._obstacle:
                    print(f"[SCAN] ⚠️  OBSTACLE: {n} pts")
                else:
                    print(f"[SCAN] clear ({n} pts)")
            except Exception as e:
                print(f"[SCAN] err: {e}")
            time.sleep(SCAN_INTERVAL)


# ── PD flight controller ───────────────────────────────────────────────

class ManualNavigator:
    def __init__(self, grid_name: str):
        self.grid = prepare_grid(grid_name)
        self.cockpit = self.grid.get_first_device(CockpitDevice)
        self.gyros = self.grid.find_devices_by_type(GyroDevice)
        self.thrusters = self.grid.find_devices_by_type(ThrusterDevice)
        self.radar = self.grid.get_first_device(OreDetectorDevice)

        if not self.cockpit: raise RuntimeError("No Cockpit found")
        if not self.gyros:   raise RuntimeError("No Gyros found")
        if not self.thrusters: raise RuntimeError("No Thrusters found")

        # Enable cockpit
        self.cockpit.enable()
        time.sleep(0.5)
        self.cockpit.update()

        self.status = "init"
        self._cancelled = False
        self._prev_angle_err = 0.0

        print(f"[INIT] Cockpit: {self.cockpit.name}")
        print(f"[INIT] Gyros: {len(self.gyros)}")
        print(f"[INIT] Thrusters: {len(self.thrusters)}")

    def _get_pos(self) -> Optional[Tuple[float, float, float]]:
        self.cockpit.update()
        return get_world_position(self.cockpit)

    def _get_vel(self) -> Tuple[float, float, float]:
        v = (self.cockpit.telemetry or {}).get("linearVelocity") or {}
        if isinstance(v, dict):
            return (float(v.get("x",0)), float(v.get("y",0)), float(v.get("z",0)))
        return (0,0,0)

    def _get_speed(self) -> float:
        v = self._get_vel()
        return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)

    def _get_basis(self):
        try:
            return get_orientation(self.cockpit)
        except:
            return None

    def _orient_toward(self, target: Tuple[float, float, float]) -> float:
        """Point ship forward at target using gyro override. Returns angle error."""
        basis = self._get_basis()
        if not basis:
            return 999.0

        pos = self._get_pos()
        if not pos:
            return 999.0

        # Direction to target in world coords
        dx = target[0]-pos[0]; dy = target[1]-pos[1]; dz = target[2]-pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1e-3:
            return 0.0
        desired_fwd = _normalize((dx, dy, dz))

        # Angle between current forward and desired
        dot_val = max(-1.0, min(1.0, _dot(basis.forward, desired_fwd)))
        angle_err = math.acos(dot_val)

        # Project desired_fwd into ship's local frame (same pattern as align_to_up_vector)
        # How much of desired direction is in "up" and "right" axes
        local_y = _dot(desired_fwd, basis.up)      # positive = target is above
        local_x = _dot(desired_fwd, basis.right)    # positive = target is right

        # P control with sign from align_to_up_vector
        pitch_cmd = -local_y * ORIENT_KP
        yaw_cmd   = -local_x * ORIENT_KP

        # Clamp
        pitch_cmd = max(-MAX_ANGULAR, min(MAX_ANGULAR, pitch_cmd))
        yaw_cmd   = max(-MAX_ANGULAR, min(MAX_ANGULAR, yaw_cmd))

        # Apply to all gyros
        for gyro in self.gyros:
            gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

        return angle_err

    def _set_thrust(self, value: float):
        """Set thrust override on all thrusters."""
        value = max(0.0, min(MAX_THRUST, value))
        for t in self.thrusters:
            t.set_thrust(override=value)

    def _stop_thrust(self):
        for t in self.thrusters:
            t.set_thrust(override=0.0)
        for g in self.gyros:
            g.clear_override()

    def brake(self):
        print("[NAV] 🛑 BRAKE")
        self._set_thrust(0.0)
        # Enable dampeners via cockpit
        self.cockpit.set_dampeners(True)
        self.status = "braking"

    def cancel(self):
        self._cancelled = True
        self.brake()

    def _velocity_toward(self, target) -> float:
        """Component of velocity toward target (positive = approaching)."""
        pos = self._get_pos()
        vel = self._get_vel()
        if not pos:
            return 0.0
        dx = target[0]-pos[0]; dy = target[1]-pos[1]; dz = target[2]-pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1e-3:
            return 0.0
        dir_to_target = (dx/dist, dy/dist, dz/dist)
        return _dot(vel, dir_to_target)

    def fly(self, target: Tuple[float, float, float]) -> bool:
        """Fly to target with gyro orientation + thrust control."""
        scanner = ForwardScanner(self.radar)
        scanner.start()

        # Disable dampeners for flight
        self.cockpit.set_dampeners(False)
        time.sleep(0.5)

        self.status = "flying"
        phase = "cruise"
        target_speed = CRUISE_SPEED

        print(f"[NAV] ▶ Flying to ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        print(f"[NAV]   cruise={CRUISE_SPEED} m/s, slow={SLOW_SPEED} m/s, stop={STOP_DISTANCE}m")

        tick = 0
        while not self._cancelled:
            pos = self._get_pos()
            if not pos:
                time.sleep(0.5)
                continue

            dist = _dist(pos, target)
            speed = self._get_speed()
            vel_toward = self._velocity_toward(target)

            # ── Obstacle → brake and switch to slow ──
            if scanner.obstacle_detected and phase == "cruise":
                print(f"[NAV] ⚠️  VOXELS at {dist:.0f}m — braking to {SLOW_SPEED} m/s")
                self.brake()
                time.sleep(2.0)

                # Recompute closer target
                pos2 = self._get_pos()
                if pos2:
                    dx = target[0]-pos2[0]; dy = target[1]-pos2[1]; dz = target[2]-pos2[2]
                    d = math.sqrt(dx*dx+dy*dy+dz*dz)
                    if d > 50.0:
                        n = _normalize((dx, dy, dz))
                        target = (pos2[0]+n[0]*(d-50), pos2[1]+n[1]*(d-50), pos2[2]+n[2]*(d-50))

                # Re-disable dampeners
                self.cockpit.set_dampeners(False)
                time.sleep(0.3)
                phase = "slow"
                target_speed = SLOW_SPEED
                self._prev_angle_err = 0.0

            # ── Slow mode: keep braking if obstacles ──
            if scanner.obstacle_detected and phase == "slow":
                print(f"[NAV] ⚠️  Still voxels — braking more")
                self.brake()
                time.sleep(2.0)
                pos3 = self._get_pos()
                if pos3:
                    dx = target[0]-pos3[0]; dy = target[1]-pos3[1]; dz = target[2]-pos3[2]
                    d = math.sqrt(dx*dx+dy*dy+dz*dz)
                    if d > 30.0:
                        n = _normalize((dx, dy, dz))
                        target = (pos3[0]+n[0]*(d-30), pos3[1]+n[1]*(d-30), pos3[2]+n[2]*(d-30))
                self.cockpit.set_dampeners(False)
                time.sleep(0.3)
                target_speed = SLOW_SPEED * 0.5
                self._prev_angle_err = 0.0

            # ── Arrival ──
            if dist < 15.0:
                print(f"[NAV] ✅ Arrived! dist={dist:.1f}m")
                self.brake()
                scanner.stop()
                self.status = "arrived"
                return True

            # ── Orient toward target ──
            angle_err = self._orient_toward(target)

            # ── Thrust control ──
            # Thrust if pointing roughly at target (within 30 degrees)
            if angle_err < 0.5:
                # Speed error: positive means we need more speed
                speed_err = target_speed - vel_toward
                if speed_err > 0.1:
                    thrust = min(MAX_THRUST, max(0.1, speed_err * THRUST_KP))
                    self._set_thrust(thrust)
                else:
                    self._set_thrust(0.0)  # coast
            else:
                self._set_thrust(0.0)  # don't thrust while turning

            # ── Status ──
            tick += 1
            if tick % 2 == 0:
                print(f"STATUS:{json.dumps({'phase':phase,'dist':round(dist,1),'speed':round(speed,1),'vel_toward':round(vel_toward,1),'angle':round(math.degrees(angle_err),1),'obstacle':scanner.obstacle_detected})}")

            time.sleep(0.5)

        scanner.stop()
        return False


# ── Main ───────────────────────────────────────────────────────────────

def main():
    global CRUISE_SPEED
    parser = argparse.ArgumentParser(description="Space Navigator v2 (gyro+thruster)")
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--speed", type=float, default=CRUISE_SPEED)
    parser.add_argument("--stop-distance", type=float, default=STOP_DISTANCE)
    parser.add_argument("--test-target", type=str, default=None)
    args = parser.parse_args()

    CRUISE_SPEED = args.speed

    print(f"=== Space Navigator v2 (manual gyro+thrust) ===")
    print(f"Grid: {args.grid}  Speed: {args.speed} m/s  Stop: {args.stop_distance}m")
    print(f"Beam: {BEAM_X}x{BEAM_Y}x{BEAM_Z} cells = {BEAM_X*CELL_SIZE:.0f}x{BEAM_Y*CELL_SIZE:.0f}x{BEAM_Z*CELL_SIZE:.0f}m")
    print()

    nav = ManualNavigator(args.grid)

    try:
        if args.test_target:
            p = args.test_target.replace("GPS:", "").split(":")
            target = (float(p[1]), float(p[2]), float(p[3]))
        else:
            print("[NAV] Searching for nearest asteroid...")
            pos = nav._get_pos()
            if not pos:
                print("[ERROR] No position!"); return
            print(f"[NAV] Ship at ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")

            asteroid = find_nearest_asteroid(nav.radar)
            if not asteroid:
                print("[ERROR] No asteroids!"); return

            name = asteroid.get("name", "?")
            center = asteroid.get("center", [])
            dist   = asteroid.get("distance", "?")
            surf   = asteroid.get("surfaceDistance", "?")
            radius = asteroid.get("approxRadius", "?")
            print(f"[NAV] Asteroid: {name}")
            print(f"  center={center}  dist={dist}m  surface={surf}m  radius={radius}m")

            target = compute_approach_point(pos, asteroid, args.stop_distance)
            print(f"[NAV] Approach: ({target[0]:.1f}, {target[1]:.1f}, {target[2]:.1f})")

        ok = nav.fly(target)
        print(f"\n=== RESULT: {nav.status} (success={ok}) ===")

    except KeyboardInterrupt:
        print("\n[NAV] Interrupted"); nav.cancel()
    except Exception as e:
        print(f"\n[ERROR] {e}"); nav.cancel(); raise
    finally:
        close(nav.grid)


if __name__ == "__main__":
    main()
