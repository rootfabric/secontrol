import types
import numpy as np

from secontrol.controllers.radar_controller import RadarController


def _build_controller_with_grid(cell_size: float = 10.0):
    controller = RadarController(types.SimpleNamespace())
    controller.cell_size = cell_size
    controller.origin = (0.0, 0.0, 0.0)
    controller.size = (3, 3, 3)
    controller.occupancy_grid = np.zeros(controller.size, dtype=bool)
    return controller


def test_get_surface_height_direct_column():
    controller = _build_controller_with_grid()
    controller.occupancy_grid[1, 2, 1] = True

    height = controller.get_surface_height(15.0, 15.0)

    assert height == 25.0


def test_get_surface_height_neighbour_search():
    controller = _build_controller_with_grid()
    controller.occupancy_grid[1, 2, 1] = True

    height = controller.get_surface_height(5.0, 15.0)

    assert height == 25.0
