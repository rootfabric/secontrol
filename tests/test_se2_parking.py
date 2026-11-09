import math

import pytest
from secontrol.se2_parking import park_pose, quat_from_orientation, quat_multiply, quat_rotate


def quat_angle(q):
    return 2 * math.degrees(math.acos(max(-1, min(1, q[0]))))


def test_identity_orientation_maps_axes():
    q = quat_from_orientation([0, 0, -1], [0, 1, 0])
    assert quat_angle(q) == pytest.approx(0, abs=1e-9)
    assert quat_rotate(q, [0, 0, -1]) == pytest.approx([0, 0, -1])


def test_orientation_matches_plugin_convention():
    # forward=+X, up=+Y: local -Z maps to +X, +Y stays +Y
    q = quat_from_orientation([1, 0, 0], [0, 1, 0])
    assert quat_rotate(q, [0, 0, -1]) == pytest.approx([1, 0, 0])
    assert quat_rotate(q, [0, 1, 0]) == pytest.approx([0, 1, 0])
    assert quat_rotate(q, [1, 0, 0]) == pytest.approx([0, 0, 1])


def test_parallel_axes_rejected():
    with pytest.raises(ValueError):
        quat_from_orientation([0, 1, 0], [0, 1, 0])


def test_park_pose_ship_center_lands_beyond_dock_face():
    grid = {"position": [0, 0, 0], "forward": [0, 0, -1], "up": [0, 1, 0]}
    own = {"pivotPosition": [0, 0, -2], "pivotForward": [0, 0, -1], "pivotUp": [0, 1, 0]}
    dock = {"pivotPosition": [100, 0, 0], "pivotForward": [1, 0, 0], "pivotUp": [0, 1, 0]}
    pos, fwd, up = park_pose(grid, own, dock, standoff=0)
    # dock faces +X: the ship approaches from +X, nose (-X) towards the dock,
    # connector 2 m ahead of the centre lands exactly on the dock pivot
    assert pos == pytest.approx([102, 0, 0], abs=1e-6)
    assert fwd == pytest.approx([-1, 0, 0], abs=1e-6)
    assert up == pytest.approx([0, 1, 0], abs=1e-6)


def test_park_pose_keeps_standoff_gap():
    grid = {"position": [0, 0, 0], "forward": [0, 0, -1], "up": [0, 1, 0]}
    own = {"pivotPosition": [0, 0, -2], "pivotForward": [0, 0, -1], "pivotUp": [0, 1, 0]}
    dock = {"pivotPosition": [100, 0, 0], "pivotForward": [1, 0, 0], "pivotUp": [0, 1, 0]}
    pos, _, _ = park_pose(grid, own, dock, standoff=1.5)
    # standoff pulls the ship further back along the dock axis (+X here)
    assert pos == pytest.approx([103.5, 0, 0], abs=1e-6)


def test_park_pose_from_rotated_start():
    # grid starts rotated 90 degrees around Y; own pivot already consistent with telemetry
    grid = {"position": [50, 0, 50], "forward": [1, 0, 0], "up": [0, 1, 0]}
    own = {"pivotPosition": [52, 0, 50], "pivotForward": [1, 0, 0], "pivotUp": [0, 1, 0]}
    dock = {"pivotPosition": [100, 0, 0], "pivotForward": [1, 0, 0], "pivotUp": [0, 1, 0]}
    pos, fwd, up = park_pose(grid, own, dock, standoff=0)
    assert pos == pytest.approx([102, 0, 0], abs=1e-6)
    assert fwd == pytest.approx([-1, 0, 0], abs=1e-6)
