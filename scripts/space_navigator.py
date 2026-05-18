#!/usr/bin/env python3
"""
Space Navigator — autonomous flight to nearest asteroid with forward beam scanning.

Flies to nearest asteroid, continuously scans a forward voxel beam,
brakes when obstacles detected, then slow-approaches.
"""
import argparse, json, math, os, sys, time, threading
from typing import Optional, Tuple, List, Dict, Any

WORKSPACE = "/workspace"
# Don't add /workspace/src to path — use pip-installed secontrol
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import prepare_grid, close
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position, get_orientation, _dist, _normalize

# ── Defaults ───────────────────────────────────────────────────────────
DEFAULT_GRID       = "skynet-baza1"
DEFAULT_SPEED      = 30.0      # m/s cruising
SLOW_SPEED         = 3.0       # m/s approach after obstacle
DEFAULT_STOP_DIST  = 200.0     # meters before asteroid surface
BEAM_X             = 50        # beam width  (voxel cells)
BEAM_Y             = 50        # beam height (voxel cells)
BEAM_Z             = 1000      # beam depth  (forward, voxel cells)
CELL_SIZE          = 5.0       # meters per voxel cell
OBSTACLE_THRESHOLD = 3         # min solid points to trigger brake
SCAN_INTERVAL      = 1.5       # seconds between scans


# ── Asteroid finder ────────────────────────────────────────────────────

def find_nearest_asteroid(
    radar: OreDetectorDevice,
    timeout: float = 15.0,
) -> Optional[Dict[str, Any]]:
    """Force-refresh asteroid index, return nearest by distance."""
    radar.send_command({
        "cmd": "asteroids",
        "targetId": int(radar.device_id),
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


def compute_approach_point(
    ship_pos: Tuple[float, float, float],
    asteroid: Dict[str, Any],
    stop_distance: float = 200.0,
) -> Tuple[float, float, float]:
    """Point along ship→asteroid line, stop_distance before surface."""
    center = asteroid.get("center", [])
    ast = (float(center[0]), float(center[1]), float(center[2]))
    radius = float(asteroid.get("approxRadius", 50.0))
    dx, dy, dz = ast[0]-ship_pos[0], ast[1]-ship_pos[1], ast[2]-ship_pos[2]
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    if dist < 1e-3:
        return ast
    d = (dx/dist, dy/dist, dz/dist)
    approach_dist = max(0, dist - radius - stop_distance)
    return (ship_pos[0]+d[0]*approach_dist,
            ship_pos[1]+d[1]*approach_dist,
            ship_pos[2]+d[2]*approach_dist)


# ── Forward scanner (background thread) ────────────────────────────────

class ForwardScanner:
    """Continuous narrow forward beam scan for obstacle detection."""

    def __init__(self, radar: OreDetectorDevice):
        self.radar = radar
        self._obstacle = False
        self._count = 0
        self._lock = threading.Lock()
        self._running = False

    @property
    def obstacle_detected(self) -> bool:
        with self._lock:
            return self._obstacle

    @property
    def solid_count(self) -> int:
        with self._lock:
            return self._count

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
            boundingBoxX=BEAM_X,
            boundingBoxY=BEAM_Y,
            boundingBoxZ=BEAM_Z,
            fullSolidScan=True,
            ore_only=False,
            filter_no_stone=True,
        )
        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
                n = len(solid) if solid else 0
                with self._lock:
                    self._count = n
                    self._obstacle = n >= OBSTACLE_THRESHOLD
                if self._obstacle:
                    print(f"[SCAN] ⚠️  OBSTACLE: {n} solid points in beam")
                else:
                    print(f"[SCAN] clear ({n} pts)")
            except Exception as e:
                print(f"[SCAN] error: {e}")
            time.sleep(SCAN_INTERVAL)


# ── Navigator ──────────────────────────────────────────────────────────

class SpaceNavigator:
    def __init__(self, grid_name: str, speed: float, stop_distance: float):
        self.grid = prepare_grid(grid_name)
        self.rc   = self.grid.get_first_device(RemoteControlDevice)
        self.radar = self.grid.get_first_device(OreDetectorDevice)
        self.speed = speed
        self.stop_distance = stop_distance
        self.scanner = ForwardScanner(self.radar)
        self._cancelled = False
        self.status = "init"
        self._cruising = True   # True=fast, False=slow approach

    # ── control ──

    def brake(self):
        print("[NAV] 🛑 BRAKE")
        self.rc.disable()
        time.sleep(0.3)
        self.rc.dampeners_on()
        self.status = "braking"

    def cancel(self):
        self._cancelled = True
        self.brake()
        self.scanner.stop()

    def _get_speed(self) -> float:
        vel = (self.rc.telemetry or {}).get("linearVelocity") or {}
        if isinstance(vel, dict):
            return math.sqrt(
                float(vel.get("x",0))**2 +
                float(vel.get("y",0))**2 +
                float(vel.get("z",0))**2
            )
        return 0.0

    def _send_goto(self, target, speed, label="NavTarget"):
        gps = f"GPS:{label}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"
        self.rc.set_mode("oneway")
        self.rc.set_collision_avoidance(False)
        self.rc.goto(gps, speed=speed, gps_name=label)

    def _wait_autopilot(self, timeout=3.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.2)
            self.rc.update()
            if (self.rc.telemetry or {}).get("autopilotEnabled"):
                return True
        return False

    # ── main flight ──

    def fly(self, target: Tuple[float, float, float]) -> bool:
        """Fly to target with continuous forward scanning."""
        self.scanner.start()
        self._cruising = True

        # ── Phase 1: cruise speed ──
        print(f"[NAV] ▶ Departing at {self.speed:.0f} m/s → "
              f"({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        self._send_goto(target, self.speed)
        if not self._wait_autopilot():
            print("[NAV] ❌ Autopilot failed to engage")
            self.scanner.stop()
            return False

        self.status = "flying_cruise"

        while not self._cancelled:
            self.rc.update()
            pos = get_world_position(self.rc)
            if not pos:
                time.sleep(0.5)
                continue

            dist = _dist(pos, target)
            spd  = self._get_speed()

            # ── obstacle → brake + slow approach ──
            if self.scanner.obstacle_detected and self._cruising:
                print(f"[NAV] ⚠️  VOXELS DETECTED — braking to {SLOW_SPEED:.0f} m/s")
                self.brake()
                time.sleep(1.0)

                # Recompute closer approach point
                self.rc.update()
                pos2 = get_world_position(self.rc)
                if pos2:
                    # Move target closer: 100m from current position toward original target
                    dx = target[0]-pos2[0]; dy = target[1]-pos2[1]; dz = target[2]-pos2[2]
                    d = math.sqrt(dx*dx+dy*dy+dz*dz)
                    if d > 1.0:
                        n = (dx/d, dy/d, dz/d)
                        new_dist = max(50.0, d - 100.0)
                        target = (pos2[0]+n[0]*new_dist, pos2[1]+n[1]*new_dist, pos2[2]+n[2]*new_dist)

                self._cruising = False
                print(f"[NAV] 🐌 Slow approach at {SLOW_SPEED:.0f} m/s")
                self._send_goto(target, SLOW_SPEED)
                if not self._wait_autopilot():
                    self.scanner.stop()
                    return False
                self.status = "flying_slow"

            # ── slow mode: keep rescanning, brake again if needed ──
            if not self._cruising and self.scanner.obstacle_detected:
                # Already slow — just brake and creep
                self.brake()
                time.sleep(1.5)
                # Nudge 30m forward
                self.rc.update()
                pos3 = get_world_position(self.rc)
                if pos3:
                    dx = target[0]-pos3[0]; dy = target[1]-pos3[1]; dz = target[2]-pos3[2]
                    d = math.sqrt(dx*dx+dy*dy+dz*dz)
                    if d > 30.0:
                        n = (dx/d, dy/d, dz/d)
                        target = (pos3[0]+n[0]*(d-30), pos3[1]+n[1]*(d-30), pos3[2]+n[2]*(d-30))
                self._send_goto(target, SLOW_SPEED * 0.5)
                if not self._wait_autopilot():
                    self.scanner.stop()
                    return False
                self.status = "creeping"

            # ── arrival ──
            if dist < 15.0:
                print(f"[NAV] ✅ Arrived! dist={dist:.1f}m")
                self.brake()
                self.scanner.stop()
                self.status = "arrived"
                return True

            # ── autopilot lost ──
            if not (self.rc.telemetry or {}).get("autopilotEnabled"):
                if dist < 50.0:
                    self.scanner.stop(); self.status = "arrived"; return True
                print(f"[NAV] ⚠️  Autopilot off at {dist:.0f}m")
                self.scanner.stop(); self.status = "autopilot_lost"; return False

            # ── status for agent ──
            phase = "cruise" if self._cruising else "slow"
            print(f"STATUS:{json.dumps({'phase':phase,'dist':round(dist,1),'speed':round(spd,1),'obstacle':self.scanner.obstacle_detected})}")
            time.sleep(0.5)

        self.scanner.stop()
        return False


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Space Navigator — fly to nearest asteroid")
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED)
    parser.add_argument("--stop-distance", type=float, default=DEFAULT_STOP_DIST)
    parser.add_argument("--test-target", type=str, default=None)
    args = parser.parse_args()

    print(f"=== Space Navigator ===")
    print(f"Grid: {args.grid}  Speed: {args.speed} m/s  Stop: {args.stop_distance}m")
    print(f"Beam: {BEAM_X}x{BEAM_Y}x{BEAM_Z} cells ({CELL_SIZE}m/cell) = "
          f"{BEAM_X*CELL_SIZE:.0f}x{BEAM_Y*CELL_SIZE:.0f}x{BEAM_Z*CELL_SIZE:.0f}m")
    print()

    nav = SpaceNavigator(args.grid, speed=args.speed, stop_distance=args.stop_distance)

    try:
        if args.test_target:
            p = args.test_target.replace("GPS:", "").split(":")
            target = (float(p[1]), float(p[2]), float(p[3]))
            print(f"[NAV] Test target: {target}")
        else:
            print("[NAV] Searching for nearest asteroid...")
            nav.rc.update()
            ship_pos = get_world_position(nav.rc)
            if not ship_pos:
                print("[ERROR] Cannot get ship position"); return
            print(f"[NAV] Ship at ({ship_pos[0]:.1f}, {ship_pos[1]:.1f}, {ship_pos[2]:.1f})")

            asteroid = find_nearest_asteroid(nav.radar)
            if not asteroid:
                print("[ERROR] No asteroids found!"); return

            name = asteroid.get("name", "?")
            center = asteroid.get("center", [])
            dist   = asteroid.get("distance", "?")
            surf   = asteroid.get("surfaceDistance", "?")
            radius = asteroid.get("approxRadius", "?")
            print(f"[NAV] Asteroid: {name}")
            print(f"  center={center}  dist={dist}m  surface={surf}m  radius={radius}m")

            target = compute_approach_point(ship_pos, asteroid, args.stop_distance)
            print(f"[NAV] Approach point: ({target[0]:.1f}, {target[1]:.1f}, {target[2]:.1f})")

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
