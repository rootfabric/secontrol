from __future__ import annotations

import types

import pytest

from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.radar_navigation import RawRadarMap

import secontrol.controllers.space_navigator_controller as nav


def _map(size=(5, 5, 5), cell=10.0, solid=()):
    import numpy as np

    occ = np.zeros(size, dtype=bool)
    for idx in solid:
        occ[idx] = True
    return RawRadarMap(
        occ=occ,
        origin=np.array([0.0, 0.0, 0.0], dtype=float),
        cell_size=cell,
        size=size,
        revision=1,
        timestamp_ms=1,
        contacts=(),
        _inflation_cache={},
    )


def test_scan_profile_computes_beam_from_radius_and_cell_size():
    profile = nav.ScanProfile(
        name="COARSE",
        radius=5000.0,
        cell_size=50.0,
        rescan_distance=1000.0,
        clearance_voxels=5,
    )

    assert profile.beam == 200
    assert profile.beam_meters == 10000.0
    assert profile.scan_kwargs["boundingBoxX"] == 200.0


def test_estimate_ship_radius_from_block_bounding_boxes():
    block = types.SimpleNamespace(
        bounding_box={
            "min": (0.0, 0.0, 0.0),
            "max": (0.0, 30.0, 40.0),
        }
    )
    grid = types.SimpleNamespace(blocks={1: block})

    assert nav.estimate_ship_radius_from_blocks(grid) == pytest.approx(25.0)


def test_ship_radius_falls_back_when_block_bounds_are_missing():
    grid = types.SimpleNamespace(blocks={})

    assert nav.estimate_ship_radius_from_blocks(grid, fallback=50.0) == 50.0


def test_effective_clearance_radius_includes_ship_and_voxel_margin():
    profile = nav.ScanProfile(
        name="COARSE",
        radius=5000.0,
        cell_size=50.0,
        rescan_distance=1000.0,
        clearance_voxels=10,
    )

    assert nav.effective_clearance_radius(50.0, profile) == 550.0


def test_resolve_nearest_safe_target_when_requested_cell_is_occupied():
    radar_map = _map(solid=[(2, 2, 2)])

    safe = nav.resolve_nearest_safe_point(radar_map, (25.0, 25.0, 25.0), safety_radius=0.0)

    assert safe is not None
    assert safe != (25.0, 25.0, 25.0)
    assert radar_map.world_to_index(safe) != (2, 2, 2)


def test_waypoint_selection_respects_rescan_distance_and_boundary():
    path = [
        (0.0, 0.0, 0.0),
        (400.0, 0.0, 0.0),
        (800.0, 0.0, 0.0),
        (1200.0, 0.0, 0.0),
    ]

    waypoint = nav.pick_waypoint_along_path(
        path,
        (0.0, 0.0, 0.0),
        scan_radius=1000.0,
        boundary_margin=100.0,
        scan_center=(0.0, 0.0, 0.0),
        rescan_distance=500.0,
        max_leg_distance=900.0,
    )

    assert waypoint == (400.0, 0.0, 0.0)


class FakeRC:
    def __init__(self, position=(5.0, 45.0, 45.0)):
        self.telemetry = {"worldPosition": list(position)}
        self.goto_calls = 0
        self.disabled = False

    def update(self):
        return None

    def enable(self):
        return 1

    def gyro_control_on(self):
        return 1

    def thrusters_on(self):
        return 1

    def dampeners_on(self):
        return 1

    def handbrake_on(self):
        return 1

    def set_collision_avoidance(self, enabled):
        return 1

    def disable(self):
        self.disabled = True
        return 1

    def goto(self, *args, **kwargs):
        self.goto_calls += 1
        return 1


class FakeRadar:
    device_id = "10"
    telemetry = {}


class FakeGrid:
    def __init__(self, radar, rc):
        self.radar = radar
        self.rc = rc
        self.blocks = {}

    def find_devices_by_type(self, device_type):
        if device_type is OreDetectorDevice:
            return [self.radar]
        if device_type is RemoteControlDevice:
            return [self.rc]
        return []


def _install_fake_controller(monkeypatch, scan_results, rc=None):
    radar = FakeRadar()
    rc = rc or FakeRC()
    grid = FakeGrid(radar, rc)
    results = list(scan_results)

    class FakeRadarController:
        def __init__(self, *args, **kwargs):
            pass

        def scan_voxels(self):
            if len(results) > 1:
                return results.pop(0)
            return results[0]

    monkeypatch.setattr("secontrol.common.prepare_grid", lambda grid_name: grid)
    monkeypatch.setattr(nav, "RadarController", FakeRadarController)
    return rc


def test_dry_run_plans_one_bounded_segment_without_flying(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        dry_run=True,
        max_steps=1,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "COARSE"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_blocked_route_returns_result_without_direct_fallback(monkeypatch):
    solid = []
    for y in range(10):
        for z in range(10):
            solid.append([45.0, y * 10.0 + 5.0, z * 10.0 + 5.0])
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [10, 10, 10], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [(solid, meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        dry_run=True,
        max_replans=0,
        max_steps=1,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "blocked"
    assert rc.goto_calls == 0


def test_failed_waypoint_execution_returns_flight_failed(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    _install_fake_controller(monkeypatch, [([], meta, [], [])])
    monkeypatch.setattr(nav, "fly_to_point", lambda *args, **kwargs: None)
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        max_replans=0,
        max_steps=1,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "flight_failed"
