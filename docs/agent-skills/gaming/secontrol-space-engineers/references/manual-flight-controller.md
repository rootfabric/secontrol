# Manual Flight Controller — gyro + thruster without RemoteControl

When a grid has no `RemoteControlDevice`, use `CockpitDevice` for telemetry + `GyroDevice` for orientation + `ThrusterDevice` for propulsion. The cockpit provides the same position/velocity/orientation telemetry as RC.

## Prerequisites

- `CockpitDevice` on grid (any cockpit seat works — `LargeBlockCockpitSeat`, `LargeBlockCockpit`, etc.)
- `GyroDevice` — at least 1, preferably 2+ for redundancy
- `ThrusterDevice` — at least some thrusters in the flight direction
- **A pilot seated in the cockpit** OR a `RemoteControlDevice` — without either, thrusters are DEAD

## Check if thrusters will respond

```python
cockpit = grid.get_first_device(CockpitDevice)
cockpit.update()
tel = cockpit.telemetry or {}

has_pilot = tel.get('hasPilot', False)
is_under_control = tel.get('isUnderControl', False)
can_control = tel.get('canControlShip', False)
control_thrusters = tel.get('controlThrusters', False)

if not has_pilot and not is_under_control:
    print("WARNING: No pilot and no RC — thrusters will NOT respond!")
    print("Fix: seat a pilot in cockpit or add Remote Control block")
```

## Full flight loop pattern

```python
import math, time, json
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.thruster_device import ThrusterDevice
from secontrol.tools.navigation_tools import (
    get_world_position, get_orientation, _dot, _normalize, _dist
)

class ManualFlightController:
    """Fly a grid to a target point using gyro orientation + thruster override."""

    def __init__(self, grid, orient_kp=1.5, max_angular=1.0, thrust_kp=0.5, max_thrust=1.0):
        self.grid = grid
        self.cockpit = grid.get_first_device(CockpitDevice)
        self.gyros = grid.find_devices_by_type(GyroDevice)
        self.thrusters = grid.find_devices_by_type(ThrusterDevice)
        self.orient_kp = orient_kp
        self.max_angular = max_angular
        self.thrust_kp = thrust_kp
        self.max_thrust = max_thrust

        if not self.cockpit:
            raise RuntimeError("No CockpitDevice found")
        if not self.gyros:
            raise RuntimeError("No GyroDevice found")
        if not self.thrusters:
            raise RuntimeError("No ThrusterDevice found")

        self.cockpit.enable()
        time.sleep(0.5)

    def get_position(self):
        self.cockpit.update()
        return get_world_position(self.cockpit)

    def get_velocity(self):
        v = (self.cockpit.telemetry or {}).get("linearVelocity") or {}
        if isinstance(v, dict):
            return (float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0)))
        return (0, 0, 0)

    def get_speed(self):
        v = self.get_velocity()
        return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)

    def orient_toward(self, target):
        """Point ship forward at target. Returns angle error in radians."""
        basis = get_orientation(self.cockpit)
        pos = self.get_position()
        if not pos:
            return 999.0

        dx, dy, dz = target[0]-pos[0], target[1]-pos[1], target[2]-pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1e-3:
            return 0.0

        desired_fwd = _normalize((dx, dy, dz))
        dot_val = max(-1.0, min(1.0, _dot(basis.forward, desired_fwd)))
        angle_err = math.acos(dot_val)

        # Project into ship's local frame (same as align_to_up_vector)
        local_y = _dot(desired_fwd, basis.up)
        local_x = _dot(desired_fwd, basis.right)

        pitch_cmd = max(-self.max_angular, min(self.max_angular, -local_y * self.orient_kp))
        yaw_cmd = max(-self.max_angular, min(self.max_angular, -local_x * self.orient_kp))

        for gyro in self.gyros:
            gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

        return angle_err

    def set_thrust(self, value):
        value = max(0.0, min(self.max_thrust, value))
        for t in self.thrusters:
            t.set_thrust(override=value)

    def brake(self):
        self.set_thrust(0.0)
        self.cockpit.set_dampeners(True)

    def clear_gyros(self):
        for g in self.gyros:
            g.clear_override()

    def fly_to(self, target, cruise_speed=10.0, arrival_dist=15.0, status_cb=None):
        """Fly to target. Returns True on arrival."""
        self.cockpit.set_dampeners(False)
        time.sleep(0.3)

        while True:
            pos = self.get_position()
            if not pos:
                time.sleep(0.5)
                continue

            dist = _dist(pos, target)
            speed = self.get_speed()
            angle = self.orient_toward(target)

            # Thrust only when pointing at target
            if angle < 0.5:  # ~30 degrees
                vel_toward = self._velocity_toward(target)
                speed_err = cruise_speed - vel_toward
                if speed_err > 0.1:
                    self.set_thrust(min(self.max_thrust, max(0.1, speed_err * self.thrust_kp)))
                else:
                    self.set_thrust(0.0)
            else:
                self.set_thrust(0.0)

            if dist < arrival_dist:
                self.brake()
                self.clear_gyros()
                return True

            if status_cb:
                status_cb({"dist": round(dist, 1), "speed": round(speed, 1),
                           "angle": round(math.degrees(angle), 1)})

            time.sleep(0.5)

    def _velocity_toward(self, target):
        pos = self.get_position()
        vel = self.get_velocity()
        if not pos:
            return 0.0
        dx, dy, dz = target[0]-pos[0], target[1]-pos[1], target[2]-pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1e-3:
            return 0.0
        return _dot(vel, (dx/dist, dy/dist, dz/dist))
```

## Known issues and tuning

### Gyro oscillation
- **Do NOT add derivative (D) term** to the orientation controller. The angle error signal from `math.acos(dot)` is noisy (jitter from telemetry updates), and the D-term amplifies this into wild oscillation (ship spins continuously).
- Pure P-controller with `gain=1.5` and `max_rate=1.0` works for large grid heavy ships.
- If the ship overshoots, reduce `gain` to 0.8-1.0.

### Thruster not firing
- **Most common cause: no pilot and no RC** — see prerequisites above.
- All thrusters get the same override value. If thrusters face different directions, net force may be near zero. The v2 script sets ALL thrusters to the same override — for ships with mixed thruster orientations, this is suboptimal. For now, this works if most thrusters face the same way.
- Hydrogen thrusters need fuel. Check `HydrogenEngine` is enabled and `HydrogenTank` has hydrogen.

### Speed stays near zero
- If `speed` stays at ~0.2-0.4 m/s despite max thrust: the ship is likely inside an asteroid (surfaceDistance=0) or thrusters aren't oriented for the flight direction.
- Check `vel_toward` — if negative, the ship is drifting away from target. Enable dampeners briefly to kill drift, then re-orient.

### Dampeners API
- `cockpit.set_dampeners(True/False)` — correct method
- `cockpit.send_command({"cmd": "set_dampeners", "state": "on"})` — wrong, non-standard
- Dampeners ON = auto-brake to zero velocity. Dampeners OFF = free drift.
- Toggle dampeners OFF before flight, ON for braking.
