"""Rover device implementation for high-level rover control.

This module provides a high-level interface for controlling rovers by managing
all wheels on a grid. It automatically discovers wheels and provides simple
drive commands.
"""

from __future__ import annotations

from typing import List

from ..base_device import Grid
from .wheel_device import WheelDevice


class RoverDevice:
    """High-level rover controller that manages all wheels on a grid."""

    def __init__(self, grid: Grid):
        """Initialize rover controller with a grid.

        Args:
            grid: The Space Engineers grid containing the rover wheels.
        """
        self.grid = grid
        self.wheels: List[WheelDevice] = grid.find_devices_by_type("wheel")
        self._current_speed = None
        self._current_steering = None
        self._parked = False

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
        if self._current_speed == speed and self._current_steering == steering:
            return  # No change, skip sending commands
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

    def park_off(self) -> None:
        """Disable parking mode for the grid."""
        if self._parked:
            self.grid.park_off()
            self._parked = False

    @property
    def is_parked(self) -> bool:
        """Check if the rover is in parking mode."""
        return self._parked
