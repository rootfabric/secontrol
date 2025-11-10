"""Demonstration of issuing commands to AI flight autopilot blocks."""

from __future__ import annotations

from secontrol.common import prepare_grid

# Coordinates are expressed in world meters. Adjust them for your world.
TARGET_COORDS = (0.0, 100.0, 0.0)


def main() -> None:
    grid = prepare_grid()
    autopilots = grid.find_devices_by_type("ai_flight_autopilot")
    if not autopilots:
        print("No AI Flight Autopilot blocks found on grid", grid.name)
        return

    autopilot = autopilots[0]
    print(f"Using AI autopilot: {autopilot.name or autopilot.device_id}")

    autopilot.clear_waypoints()
    autopilot.add_waypoint(TARGET_COORDS, speed=25.0, name="Demo waypoint")
    autopilot.set_speed_limit(30.0)
    autopilot.enable_autopilot()
    autopilot.start_mission()
    print("Waypoint queued and mission started.")


if __name__ == "__main__":
    main()
