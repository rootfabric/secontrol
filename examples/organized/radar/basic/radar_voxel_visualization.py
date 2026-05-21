"""
Example of using RadarController to scan voxels and visualize them.
"""

import time
from typing import Any, Dict

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.radar_visualizer import RadarVisualizer
from secontrol.tools.navigation_tools import get_world_position

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
    """Get own world position from cockpit or remote control."""
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
    position = get_world_position(device)
    return list(position) if position else None


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
    # grid = prepare_grid("skynet-baza0")
    # grid = prepare_grid("DroneBase")
    grid = prepare_grid("taburet3")

    try:
        radar = grid.get_first_device(OreDetectorDevice)

        print(f"Found radar: {radar.name} (id={radar.device_id})")
        print("Cancelling any previous voxel scan...")
        cancel_seq = radar.cancel_scan()
        print(f"Cancel sent, seq={cancel_seq}")
        time.sleep(0.2)

        # Create controller
        controller = RadarController(radar,
                                    radius=500,
                                    # voxel_step=1,
                                    cell_size=10.0,
                                    # ore_only=True,
                                    # ore_only=False,
                                    # boundingBoxX=10,
                                    boundingBoxY=1000,
                                    # boundingBoxZ=5000,
                                    # boundingBoxZ=30,

                                    )

        # Scan voxels
        print("Starting voxel scan...")
        t0 = time.time()
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        elapsed = time.time() - t0

        if solid is not None and metadata is not None and contacts is not None and ore_cells is not None:
            own_position = get_own_position(grid)

            # ── Distance measurements ──
            print(f"\n{'='*60}")
            print(f"  VOXEL DISTANCE MEASUREMENTS")
            print(f"{'='*60}")
            print(f"Ship position: {own_position}")
            print(f"Scan time: {elapsed:.2f}s")
            print(f"Solid voxels: {len(solid)}")
            print(f"Grid: {metadata['size']}, cell_size={metadata['cellSize']}")
            print(f"Origin: {metadata['origin']}")

            if solid and own_position:
                import math

                # solid points are already WORLD coordinates
                voxel_info = []
                for pt in solid:
                    dx = pt[0] - own_position[0]
                    dy = pt[1] - own_position[1]
                    dz = pt[2] - own_position[2]
                    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                    voxel_info.append({
                        "world": (pt[0], pt[1], pt[2]),
                        "dist": dist,
                    })

                voxel_info.sort(key=lambda v: v["dist"])

                print(f"\n  Distance range: {voxel_info[0]['dist']:.1f}m — {voxel_info[-1]['dist']:.1f}m")
                print(f"  Average: {sum(v['dist'] for v in voxel_info)/len(voxel_info):.1f}m")

                print(f"\n  All voxels (sorted by distance):")
                print(f"  {'#':>3}  {'Dist':>8}  {'World coordinates'}")
                print(f"  {'─'*3}  {'─'*8}  {'─'*50}")
                for i, v in enumerate(voxel_info):
                    w = v["world"]
                    print(f"  {i+1:3d}  {v['dist']:8.1f}m  ({w[0]:.1f}, {w[1]:.1f}, {w[2]:.1f})")

                nearest = voxel_info[0]
                print(f"\n  → Ближайший воксель: {nearest['dist']:.1f}m")
                print(f"    World: ({nearest['world'][0]:.1f}, {nearest['world'][1]:.1f}, {nearest['world'][2]:.1f})")

            # Ore cells
            if ore_cells:
                print(f"\n  Ore cells: {len(ore_cells)}")
                for i, cell in enumerate(ore_cells[:10]):
                    cx = cell.get("centerX") or cell.get("center", {}).get("x", 0)
                    cy = cell.get("centerY") or cell.get("center", {}).get("y", 0)
                    cz = cell.get("centerZ") or cell.get("center", {}).get("z", 0)
                    if own_position:
                        import math
                        d = math.sqrt((cx-own_position[0])**2 + (cy-own_position[1])**2 + (cz-own_position[2])**2)
                        ore_type = cell.get("ore", cell.get("type", "?"))
                        print(f"    {i+1}. {ore_type}: {d:.1f}m ({cx:.1f}, {cy:.1f}, {cz:.1f})")

            print(f"{'='*60}\n")

            # Visualize
            print("Visualizing...")
            visualizer.visualize(solid, metadata, contacts, own_position, ore_cells)
        else:
            print("Scan failed.")

    finally:
        visualizer.close()
        close(grid)


if __name__ == "__main__":
    main()
