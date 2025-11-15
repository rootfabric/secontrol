import numpy as np

from secontrol.radar_navigation import PassabilityProfile, PathFinder, RawRadarMap


def _make_map(occ: np.ndarray) -> RawRadarMap:
    size = occ.shape
    return RawRadarMap(
        occ=occ,
        origin=np.zeros(3, dtype=np.float64),
        cell_size=1.0,
        size=size,  # type: ignore[arg-type]
        revision=None,
        timestamp_ms=None,
        contacts=(),
        gravity_vector=np.array([0.0, -9.81, 0.0]),
    )


def test_raw_radar_map_from_json_includes_gravity_vector():
    payload = {
        "size": [2, 2, 2],
        "origin": [0.0, 0.0, 0.0],
        "cellSize": 1.0,
        "gravityVector": [0.0, -9.81, 0.0],
    }

    radar_map = RawRadarMap.from_json(payload)

    assert radar_map.gravity_vector is not None
    assert np.allclose(radar_map.gravity_vector, [0.0, -9.81, 0.0])


def test_pathfinder_requires_support_with_gravity():
    occ = np.zeros((3, 3, 1), dtype=bool)
    occ[0, 0, 0] = True  # ground below the start

    radar_map = _make_map(occ)
    profile = PassabilityProfile(allow_diagonal=False)
    finder = PathFinder(radar_map, profile)

    start = (0, 1, 0)
    goal = (1, 1, 0)

    assert finder.find_path_indices(start, goal) == []

    occ_with_support = occ.copy()
    occ_with_support[1, 0, 0] = True

    finder_supported = PathFinder(_make_map(occ_with_support), profile)
    path = finder_supported.find_path_indices(start, goal)

    assert path[0] == start
    assert path[-1] == goal
