"""Rover device implementation for high-level rover control.

This module provides a high-level interface for controlling rovers by managing
all wheels on a grid. It automatically discovers wheels and provides simple
drive commands.
"""

from __future__ import annotations

import math
import time

from typing import List

from ..base_device import Grid
from .ore_detector_device import OreDetectorDevice
from .wheel_device import WheelDevice


class PID:
    """Simple PID controller."""

    def __init__(self, kp: float, ki: float, kd: float, setpoint: float = 0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.prev_error = 0.0
        self.integral = 0.0
        self.prev_time = time.time()

    def update(self, current_value: float) -> float:
        error = self.setpoint - current_value
        current_time = time.time()
        dt = current_time - self.prev_time
        if dt <= 0:
            dt = 0.001
        self.integral += error * dt
        derivative = (error - self.prev_error) / dt
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        self.prev_error = error
        self.prev_time = current_time
        return output


class RoverDevice:
    """High-level rover controller that manages all wheels on a grid."""

    def __init__(self, grid: Grid):
        """Initialize rover controller with a grid.

        Args:
            grid: The Space Engineers grid containing the rover wheels.
        """
        self.grid = grid
        self.wheels: List[WheelDevice] = grid.find_devices_by_type("wheel")
        detectors = grid.find_devices_by_type("ore_detector")
        if not detectors:
            raise ValueError("No ore detector (radar) found on the grid. Cannot determine rover position for pathfinding.")
        self.detector: OreDetectorDevice = detectors[0]
        self._current_speed = None
        self._current_steering = None
        self._parked = False
        self._is_moving = False
        self._target_point = None
        self._target_callback = None
        self._min_distance = 20.0
        self._max_distance = 500.0
        self._base_speed = 0.005
        self._speed_factor = 0.05
        self._max_speed = 0.015
        self._steering_gain = 2.5
        self._pid_steering = PID(kp=1.0, ki=0.1, kd=0.05, setpoint=0.0)

    def drive_forward(self, speed: float) -> None:
        """Drive the rover forward at the specified speed.

        Args:
            speed: Propulsion speed (-1.0 to 1.0). Positive values drive forward.
        """
        self.drive(speed, 0.0)

    def drive(self, speed: float, steering: float = 0.0) -> None:
        """Drive the rover with specified speed and steering.

        Args:
            speed: Propulsion speed (-1.0 to 1.0). Positive values drive forward.
            steering: Steering angle (-1.0 to 1.0). Negative values turn left, positive turn right.
        """
        # if self._current_speed == speed and self._current_steering == steering:
        #     return  # No change, skip sending commands
        for wheel in self.wheels:
            wheel.set_steering(steering)
            if 'Left' in wheel.name:
                wheel.set_propulsion(speed)
            else:
                wheel.set_propulsion(-speed)
        self._current_speed = speed
        self._current_steering = steering


    def stop(self) -> None:
        """Stop all rover wheels."""
        if self._current_speed == 0.0 and self._current_steering == 0.0:
            return  # Already stopped
        for wheel in self.wheels:
            wheel.set_propulsion(0.0)
            wheel.set_steering(0.0)
        self._current_speed = 0.0
        self._current_steering = 0.0

    def park_on(self) -> None:
        """Enable parking mode for the grid."""
        if not self._parked:
            self.grid.park_on()
            self._parked = True

    def park_off(self, force = False) -> None:
        """Disable parking mode for the grid."""
        if self._parked or force:
            self.grid.park_off()
            self._parked = False

    @property
    def is_parked(self) -> bool:
        """Check if the rover is in parking mode."""
        return self._parked

    def _compute_steering_and_speed(
        self,
        current_pos: tuple[float, float, float],
        rover_forward: tuple[float, float, float],
        target_point: tuple[float, float, float],
        base_speed: float,
        speed_factor: float,
        max_speed: float,
        steering_gain: float,
        min_distance: float,
        max_distance: float = 500.0,
    ) -> tuple[float, float]:
        """Compute steering and speed to move towards target point.

        Args:
            current_pos: Current rover position.
            rover_forward: Rover's forward vector.
            target_point: Target position.
            base_speed: Base propulsion speed.
            speed_factor: Unused in current implementation.
            max_speed: Maximum propulsion speed.
            steering_gain: Steering amplification factor.
            min_distance: Minimum distance to stop.
            max_distance: Maximum distance for speed scaling.

        Returns:
            Tuple of (speed, steering).
        """
        # Vector from rover to target
        vector_to_target = [t - c for t, c in zip(target_point, current_pos)]
        distance = math.sqrt(sum(v**2 for v in vector_to_target))

        if distance < min_distance:
            return 0.0, 0.0  # Stop

        # Speed: closer to target, slower
        speed = base_speed + (max_speed - base_speed) * min(1.0, distance / max_distance)

        # Direction to target (normalized, ignore Y)
        dir_to_target = [vector_to_target[0], 0, vector_to_target[2]]
        dir_length = math.sqrt(sum(d**2 for d in dir_to_target))
        if dir_length > 0:
            dir_norm = [d / dir_length for d in dir_to_target]
        else:
            dir_norm = [1, 0, 0]  # Fallback

        # Rover forward (normalized, ignore Y)
        forward_horiz = [rover_forward[0], 0, rover_forward[2]]
        forward_length = math.sqrt(sum(f**2 for f in forward_horiz))
        if forward_length > 0:
            forward_norm = [f / forward_length for f in forward_horiz]
        else:
            forward_norm = [1, 0, 0]  # Fallback

        # Angle between forward and direction to target
        dot = sum(a * b for a, b in zip(dir_norm, forward_norm))
        cross = dir_norm[0] * forward_norm[2] - dir_norm[2] * forward_norm[0]
        angle = math.atan2(cross, dot)

        # Use PID for steering
        steering = self._pid_steering.update(angle)
        steering = max(-1.0, min(1.0, steering))

        return speed, steering

    def _on_telemetry(self, dev, telemetry: dict, event: str) -> None:
        """Handle telemetry update from the radar."""
        if not self._is_moving or not self._target_point:
            return

        radar = telemetry.get("radar")
        if not radar:
            return

        # Get current position and forward direction
        contacts = self.detector.contacts()
        current_pos = None
        rover_forward = None
        for contact in contacts:
            if contact.get("type") == "grid" and contact.get("id") == int(self.grid.grid_id):
                current_pos = contact.get("position")
                rover_forward = contact.get("forward")
                break

        if not current_pos or not rover_forward:
            print("Warning: Could not find rover position or forward in radar telemetry.")
            return

        # Update target if callback is set
        if self._target_callback:
            self._target_point = self._target_callback()

        # Compute distance to target
        distance = math.sqrt(sum((t - c)**2 for t, c in zip(self._target_point, current_pos)))
        print(distance)

        # Compute steering and speed
        speed, steering = self._compute_steering_and_speed(
            current_pos, rover_forward, self._target_point,
            self._base_speed, self._speed_factor, self._max_speed, self._steering_gain, self._min_distance, self._max_distance
        )

        if speed == 0.0 and steering == 0.0:
            # Stop moving
            self.stop()
            self.park_on()
            self._is_moving = False
            print(f"Reached target point {self._target_point}")
        else:
            # self.park_off(True)
            self.drive(speed, steering)
            print(f"Moving: pos={current_pos}, target={self._target_point}, distance={distance:.2f}, speed={speed:.3f}, steering={steering:.3f}")

    def move_to_point(
        self,
        target_point: tuple[float, float, float] | None = None,
        target_callback: callable = None,
        min_distance: float = 20.0,
        base_speed: float = 0.015,
        speed_factor: float = 0.5,
        max_speed: float = 0.02,
        steering_gain: float = 2.5,
        max_distance: float = 500.0,
    ) -> None:
        """Move the rover to the specified target point.

        Blocks until the target is reached or interrupted (e.g., KeyboardInterrupt).

        Args:
            target_point: The (x, y, z) coordinates to move to.
            min_distance: Minimum distance to target to consider it reached.
            base_speed: Base propulsion speed (-1.0 to 1.0).
            speed_factor: Unused in current implementation.
            max_speed: Maximum propulsion speed.
            steering_gain: Steering amplification factor.
            max_distance: Maximum distance for speed scaling.
        """
        if self._is_moving:
            print("Already moving to a target point.")
            return

        # Set parameters
        self._target_callback = target_callback
        if target_callback:
            self._target_point = target_callback()
        else:
            self._target_point = target_point
        self._min_distance = min_distance
        self._max_distance = max_distance
        self._base_speed = base_speed
        self._speed_factor = speed_factor
        self._max_speed = max_speed
        self._steering_gain = steering_gain
        self._is_moving = True

        # Subscribe to telemetry
        self.detector.on("telemetry", self._on_telemetry)

        print(f"Starting move to target")

        try:
            # Initial scan
            self.detector.scan(include_grids=True, include_voxels=False)
            while self._is_moving:
                time.sleep(1)  # Wait for telemetry updates
                self.detector.scan(include_grids=True, include_voxels=False)  # Refresh scan
        except KeyboardInterrupt:
            print("Move interrupted by user.")
            self.stop()
            self.park_on()
            self._is_moving = False
        finally:
            # Unsubscribe
            self.detector.off("telemetry", self._on_telemetry)
