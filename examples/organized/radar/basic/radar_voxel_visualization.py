"""
Example of using RadarController to scan voxels and visualize them.
"""

import time
from typing import Any, Dict

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.radar_visualizer import RadarVisualizer

# Global variables
last_solid_data = None
visualizer = RadarVisualizer()


def extract_solid(radar: Dict[str, Any]) -> tuple[list[list[float]], Dict[str, Any], list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Extract solid points, metadata, contacts, and ore cells from radar data."""
    raw = radar.get("raw", {})
    solid = raw.get("solidPoints", [])
    if not isinstance(solid, list):
        solid = []

    metadata = {
        "size": raw.get("size", [100, 100, 100]),
        "cellSize": raw.get("cellSize", 1.0),
        "origin": raw.get("origin", [0.0, 0.0, 0.0]),
        "rev": raw.get("rev", 0),
    }

    contacts = radar.get("contacts", [])
    if not isinstance(contacts, list):
        contacts = []

    ore_cells = radar.get("oreCells", [])
    if not isinstance(ore_cells, list):
        ore_cells = []

    return solid, metadata, contacts, ore_cells


def get_own_position(grid):
    """Get own position from cockpit or remote control."""
    cockpit_devices = grid.find_devices_by_type("cockpit")
    remote_devices = grid.find_devices_by_type("remote_control")
    device = None
    if cockpit_devices:
        device = cockpit_devices[0]
    elif remote_devices:
        device = remote_devices[0]
    else:
        return None

    device.update()
    position = device.telemetry.get("planetPosition") or device.telemetry.get("position")
    if isinstance(position, dict):
        position = [position["x"], position["y"], position["z"]]
    return position if isinstance(position, list) else None


def process_and_visualize(solid: list[list[float]], metadata: Dict[str, Any], contacts: list[Dict[str, Any]], grid):
    """Process solid data and visualize."""
    global last_solid_data
    if not solid:
        print("No solid data to process.")
        return

    # Check for changes
    current_data = (solid[:10], metadata["rev"])
    if last_solid_data == current_data:
        return
    last_solid_data = current_data

    print(f"Processing solid: {len(solid)} points, rev={metadata['rev']}")

    own_position = get_own_position(grid)
    visualizer.visualize(solid, metadata, contacts, own_position)


def main() -> None:
    grid = prepare_grid("taburet2")
    # grid = prepare_grid("DroneBase")

    try:
        radar = grid.get_first_device(OreDetectorDevice)

        print(f"Found radar: {radar.name} (id={radar.device_id})")

        # Create controller
        controller = RadarController(radar,
                                     radius=100,
                                     voxel_step=1,
                                     cell_size=10.0,
                                     # boundingBoxX=20,
                                     # boundingBoxZ=20,
                                     boundingBoxY=50,
                                     # fullSolidScan=False
                                     )

        # Scan voxels
        print("Starting voxel scan...")
        solid, metadata, contacts, ore_cells = controller.scan_voxels()


        if solid is not None and metadata is not None and contacts is not None and ore_cells is not None:
            print("Visualizing...")
            own_position = get_own_position(grid)

            visualizer.visualize(solid, metadata, contacts, own_position, ore_cells)
        else:
            print("Scan failed.")

    finally:
        visualizer.close()
        close(grid)


if __name__ == "__main__":
    main()
