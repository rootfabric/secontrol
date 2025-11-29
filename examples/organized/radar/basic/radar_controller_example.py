"""
Example of using RadarController for scanning and getting voxel data.
"""

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController


def main() -> None:
    grid = prepare_grid("Drone")  # Replace with actual grid name

    try:
        # Find radar
        radars = grid.find_devices_by_type(OreDetectorDevice)
        if not radars:
            print("No radar found on grid.")
            return
        radar = radars[0]


        print(f"Found radar: {radar.name} (id={radar.device_id})")

        # Create controller
        controller = RadarController(radar, radius = 80)

        # Scan voxels
        print("Starting voxel scan...")
        solid, metadata, contacts, ore_cells = controller.scan_voxels()

        # Check results
        if solid is not None and metadata is not None and contacts is not None and ore_cells is not None:
            print(f"Scan completed successfully!")
            print(f"Grid size: {metadata['size']}")
            print(f"Origin: {metadata['origin']}")
            print(f"Cell size: {metadata['cellSize']}")
            print(f"Total solid voxels: {len(solid)}")
            print(f"Total ore cells: {len(ore_cells)}")
            if len(ore_cells)>0:
                print(f"Total ore cells: {ore_cells}")


            # Check occupancy_grid for compatibility
            if controller.occupancy_grid is not None:
                # Example: get surface height at origin
                height = controller.get_surface_height(metadata['origin'][0], metadata['origin'][2])
                if height is not None:
                    print(f"Surface height at origin: {height}")
                else:
                    print("No surface height available.")
        else:
            print("Scan failed or no data.")

    finally:
        close(grid)


if __name__ == "__main__":
    main()
