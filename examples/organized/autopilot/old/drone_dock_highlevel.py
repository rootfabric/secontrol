from __future__ import annotations
import os
import sys
import time
from typing import Tuple

sys.path.append(os.path.dirname(__file__))

from secontrol.common import prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import goto

from drone_dock_helpers import (
    _calculate_docking_point,
    _dock_by_connector_vector,
    _ensure_telemetry,
    _get_pos,
    _parse_vector,
    _sub,
    _add,
    _scale,
    get_connector_status,
    is_already_docked,
    is_parking_possible,
    try_dock,
)


class DroneDockController:
    """
    High-level controller for drone docking operations.
    Provides simple methods to dock, undock, and move the drone.
    """

    def __init__(self, base_grid_name: str, ship_grid_name: str):
        self.base_grid = prepare_grid(base_grid_name)
        self.ship_grid = prepare_grid(ship_grid_name)

        # Find devices
        rc_list = self.ship_grid.find_devices_by_type(RemoteControlDevice)
        ship_conn_list = self.ship_grid.find_devices_by_type(ConnectorDevice)
        base_conn_list = self.base_grid.find_devices_by_type(ConnectorDevice)

        if not rc_list:
            raise RuntimeError("No RemoteControl found on ship grid.")
        if not ship_conn_list:
            raise RuntimeError("No Connector found on ship grid.")
        if not base_conn_list:
            raise RuntimeError("No Connector found on base grid.")

        self.rc: RemoteControlDevice = rc_list[0]
        self.ship_conn: ConnectorDevice = ship_conn_list[0]
        self.base_conn: ConnectorDevice = base_conn_list[0]

    def dock(self) -> bool:
        """
        Perform the full docking procedure.
        Returns True if docked successfully, False otherwise.
        """
        print("Starting docking procedure...")

        while not try_dock(self.ship_conn):
            _ensure_telemetry(self.rc)
            self.ship_conn.wait_for_telemetry()
            self.base_conn.wait_for_telemetry()

            # ---- Check initial status ----
            print(f"   [INITIAL] Ship connector status: {get_connector_status(self.ship_conn)}")

            if is_already_docked(self.ship_conn):
                print("   [INITIAL] Ship is already docked, undocking...")
                self.ship_conn.disconnect()
                time.sleep(1)
                self.ship_conn.update()
                print(f"   [INITIAL] After undock status: {get_connector_status(self.ship_conn)}")

            if get_connector_status(self.ship_conn) == "Connectable":
                self.ship_conn.connect()

            if not is_parking_possible(self.base_conn):
                print(f"Base connector not ready for parking, status: {get_connector_status(self.base_conn)}")
                return False

            connector_pos = _parse_vector(self.base_conn.telemetry.get("position"))
            connector_orientation = self.base_conn.telemetry.get("orientation")

            # Calculate vectors
            rc_pos = _get_pos(self.rc)
            ship_conn_pos = _get_pos(self.ship_conn)

            forward_vec = _parse_vector(connector_orientation.get("forward"))
            rc_to_ship_conn = _sub(ship_conn_pos, rc_pos)
            print(f"rc_to_ship_conn: {rc_to_ship_conn}")

            # Approach and final positions
            approach_rc_pos = _sub(_add(connector_pos, _scale(forward_vec, 5.0)), rc_to_ship_conn)
            final_rc_pos = _sub(_add(connector_pos, _scale(forward_vec, 1.5)), rc_to_ship_conn)

            self.ship_grid.create_gps_marker("approach_rc_pos", coordinates=approach_rc_pos)

            current_rc_pos = _get_pos(self.rc)

            self.ship_conn.disconnect()

            # Fly to approach point
            goto(self.ship_grid, approach_rc_pos, 100)
            print("Approached connector area.")
            time.sleep(1)

            # Fly to final point
            goto(self.ship_grid, final_rc_pos, speed=1)
            print("At connector position.")
            time.sleep(1)

        return True

    def undock(self):
        """Undock the ship from the base."""
        print("Undocking...")
        self.ship_conn.disconnect()
        time.sleep(1)
        self.ship_conn.update()
        print(f"Undock status: {get_connector_status(self.ship_conn)}")

    def move_to(self, position: Tuple[float, float, float], speed: int = 100):
        """Move the drone to the specified position."""
        print(f"Moving to {position}...")
        goto(self.ship_grid, position, speed)

    def is_docked(self) -> bool:
        """Check if the ship is currently docked."""
        return is_already_docked(self.ship_conn)


if __name__ == "__main__":
    # Example usage
    controller = DroneDockController("DroneBase", "taburet")
    print("Drone controller initialized.")
    controller.undock()
    # controller.move_to((1083866.53, 145816.53, 1661753.33))  # Example position

    controller.dock()

