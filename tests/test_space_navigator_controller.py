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
    assert profile.scan_kwargs["boundingBoxX"] == 10000.0


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
        clearance_voxels=12,
    )

    assert nav.effective_clearance_radius(50.0, profile) == 650.0


def test_default_fine_clearance_keeps_parking_farther_from_voxels():
    assert nav.FINE_SCAN.clearance_voxels == 20
    assert nav.effective_clearance_radius(50.0, nav.FINE_SCAN) == 250.0


def test_normalize_scan_metadata_expands_to_profile_volume():
    profile = nav.ScanProfile(
        name="COARSE",
        radius=5000.0,
        cell_size=50.0,
        rescan_distance=2000.0,
        clearance_voxels=12,
    )
    metadata = {"origin": [100.0, 200.0, 300.0], "cellSize": 50.0, "size": [10, 10, 10], "rev": 1}

    normalized = nav.normalize_scan_metadata(metadata, profile, (1000.0, 2000.0, 3000.0))

    assert normalized["size"] == [200, 200, 200]
    assert normalized["origin"] == [-4000.0, -3000.0, -2000.0]
    assert normalized["expandedToScanVolume"] is True


def test_resolve_nearest_safe_target_when_requested_cell_is_occupied():
    radar_map = _map(solid=[(2, 2, 2)])

    safe = nav.resolve_nearest_safe_point(radar_map, (25.0, 25.0, 25.0), safety_radius=0.0)

    assert safe is not None
    assert safe != (25.0, 25.0, 25.0)
    assert radar_map.world_to_index(safe) != (2, 2, 2)


def test_safe_target_resolution_prefers_current_ship_side():
    radar_map = _map(size=(11, 11, 11), cell=10.0, solid=[(5, 5, 5)])
    target = (55.0, 55.0, 55.0)

    safe = nav.resolve_nearest_safe_point(
        radar_map,
        target,
        safety_radius=0.0,
        preferred_from=(95.0, 55.0, 55.0),
    )

    assert safe is not None
    assert safe[0] > target[0]


def test_safe_target_resolution_respects_distance_limit():
    radar_map = _map(size=(11, 11, 11), cell=10.0, solid=[(5, 5, 5)])
    target = (55.0, 55.0, 55.0)

    safe = nav.resolve_nearest_safe_point(
        radar_map,
        target,
        safety_radius=0.0,
        preferred_from=(5.0, 55.0, 55.0),
        max_distance_from=(5.0, 55.0, 55.0),
        max_distance=45.0,
    )

    assert safe is not None
    assert nav._dist(safe, (5.0, 55.0, 55.0)) <= 45.0


def test_safe_target_resolution_returns_none_when_only_safe_cells_are_outside_limit():
    radar_map = _map(size=(11, 11, 11), cell=10.0, solid=[(5, 5, 5)])

    safe = nav.resolve_nearest_safe_point(
        radar_map,
        (55.0, 55.0, 55.0),
        safety_radius=0.0,
        preferred_from=(5.0, 55.0, 55.0),
        max_distance_from=(5.0, 55.0, 55.0),
        max_distance=20.0,
    )

    assert safe is None


def test_safe_target_resolution_stops_when_no_free_cell_exists():
    solid = [
        (x, y, z)
        for x in range(3)
        for y in range(3)
        for z in range(3)
    ]
    radar_map = _map(size=(3, 3, 3), cell=10.0, solid=solid)

    safe = nav.resolve_nearest_safe_point(radar_map, (15.0, 15.0, 15.0), safety_radius=0.0)

    assert safe is None


def test_crop_map_for_path_limits_large_search_volume():
    radar_map = _map(size=(200, 200, 200), cell=10.0)

    cropped = nav.crop_map_for_path(
        radar_map,
        (100.0, 100.0, 100.0),
        (900.0, 100.0, 100.0),
        padding_m=100.0,
    )

    assert cropped.size == (101, 21, 21)
    assert cropped.world_to_index((100.0, 100.0, 100.0)) is not None
    assert cropped.world_to_index((900.0, 100.0, 100.0)) is not None


def test_occupancy_inflation_matches_box_clearance():
    radar_map = _map(size=(5, 5, 5), cell=10.0, solid=[(2, 2, 2)])

    inflated = radar_map.occupancy(10.0)

    assert inflated.sum() == 27
    assert inflated[1, 1, 1]
    assert inflated[3, 3, 3]
    assert not inflated[0, 2, 2]


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
    medium = nav.ScanProfile("MEDIUM", 40.0, 10.0, rescan_distance=20.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_steps=1,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "COARSE"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_initial_scan_uses_fine_profile_when_target_is_already_close(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 60.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_steps=1,
    )

    result = controller.navigate_to((45.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "FINE"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_target_just_outside_usable_fine_radius_stays_medium(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 200.0, 10.0, rescan_distance=100.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_steps=1,
    )

    result = controller.navigate_to((45.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "MEDIUM"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_initial_scan_uses_medium_profile_before_fine_zone(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 200.0, 10.0, rescan_distance=100.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 30.0, 10.0, rescan_distance=15.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_steps=1,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "MEDIUM"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_coarse_scan_switches_to_medium_before_flying_near_voxels(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [120, 20, 20], "rev": 1}
    rc = _install_fake_controller(
        monkeypatch,
        [([[255.0, 45.0, 45.0]], meta, [], []), ([], meta, [], [])],
    )
    coarse = nav.ScanProfile("COARSE", 600.0, 10.0, rescan_distance=200.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 300.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_steps=2,
    )

    result = controller.navigate_to((505.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "MEDIUM"
    assert result.scan_count == 2
    assert result.replans == 1
    assert rc.goto_calls == 0


def test_medium_scan_does_not_switch_to_fine_only_because_voxel_is_near(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [120, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([[185.0, 45.0, 45.0]], meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 1200.0, 10.0, rescan_distance=500.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 1000.0, 10.0, rescan_distance=500.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 300.0, 10.0, rescan_distance=200.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_steps=1,
        target_is_obstacle=True,
    )

    result = controller.navigate_to((755.0, 45.0, 45.0))

    assert result.status == "dry_run"
    assert result.profile == "MEDIUM"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_fine_parking_stops_when_current_position_is_safe_boundary(monkeypatch):
    solid = [[45.0, 45.0, 45.0]]
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [(solid, meta, [], [])], rc=FakeRC(position=(25.0, 45.0, 45.0)))
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 60.0, 10.0, rescan_distance=25.0, clearance_voxels=1)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        arrival_distance=5.0,
        max_steps=1,
    )

    result = controller.navigate_to((45.0, 45.0, 45.0))

    assert result.status == "safe_target_reached"
    assert result.profile == "FINE"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_obstacle_target_empty_fine_scan_fails_instead_of_flying_blind(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])], rc=FakeRC(position=(5.0, 45.0, 45.0)))
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 60.0, 10.0, rescan_distance=25.0, clearance_voxels=1)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_replans=0,
        max_steps=1,
        target_is_obstacle=True,
    )

    result = controller.navigate_to((45.0, 45.0, 45.0))

    assert result.status == "scan_failed"
    assert result.profile == "FINE"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_obstacle_target_empty_medium_scan_fails_instead_of_flying_blind(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])], rc=FakeRC(position=(5.0, 45.0, 45.0)))
    coarse = nav.ScanProfile("COARSE", 200.0, 10.0, rescan_distance=100.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=1)
    fine = nav.ScanProfile("FINE", 30.0, 10.0, rescan_distance=15.0, clearance_voxels=1)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_replans=0,
        max_steps=1,
        target_is_obstacle=True,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "scan_failed"
    assert result.profile == "MEDIUM"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_obstacle_target_empty_fine_scan_inside_standoff_still_fails(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])], rc=FakeRC(position=(25.0, 45.0, 45.0)))
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 60.0, 10.0, rescan_distance=25.0, clearance_voxels=1)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        fine_scan=fine,
        arrival_distance=5.0,
        dry_run=True,
        max_replans=0,
        max_steps=1,
        target_is_obstacle=True,
    )

    result = controller.navigate_to((45.0, 45.0, 45.0))

    assert result.status == "scan_failed"
    assert result.profile == "FINE"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_zero_origin_after_valid_position_is_treated_as_telemetry_glitch():
    assert nav._looks_like_zero_telemetry_glitch((0.0, 0.0, 0.0), (96000.0, 81000.0, -124000.0))
    assert not nav._looks_like_zero_telemetry_glitch((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))


def test_blocked_route_returns_result_without_direct_fallback(monkeypatch):
    solid = []
    for y in range(20):
        for z in range(20):
            solid.append([45.0, y * 10.0 + 5.0, z * 10.0 + 5.0])
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [20, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [(solid, meta, [], []), (solid, meta, [], [])])
    coarse = nav.ScanProfile("COARSE", 100.0, 10.0, rescan_distance=50.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 40.0, 10.0, rescan_distance=20.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 50.0, 10.0, rescan_distance=25.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        dry_run=True,
        max_replans=0,
        max_steps=2,
    )

    result = controller.navigate_to((85.0, 45.0, 45.0))

    assert result.status == "safe_target_reached"
    assert result.profile == "MEDIUM"
    assert result.scan_count == 2
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


def test_navigation_reuses_scan_until_rescan_distance(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [80, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])])

    def fake_fly_to_point(remote, waypoint, **kwargs):
        remote.telemetry["worldPosition"] = list(waypoint)
        return waypoint

    monkeypatch.setattr(nav, "fly_to_point", fake_fly_to_point)

    coarse = nav.ScanProfile("COARSE", 400.0, 10.0, rescan_distance=120.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 10.0, 10.0, rescan_distance=10.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 10.0, 10.0, rescan_distance=10.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        max_steps=2,
    )

    result = controller.navigate_to((305.0, 45.0, 45.0))

    assert result.status == "max_steps"
    assert result.scan_count == 1
    assert rc.goto_calls == 0


def test_obstacle_target_does_not_switch_to_fine_from_resolved_goal(monkeypatch):
    meta = {"origin": [0.0, 0.0, 0.0], "cellSize": 10.0, "size": [200, 20, 20], "rev": 1}
    rc = _install_fake_controller(monkeypatch, [([], meta, [], [])])

    def fake_fly_to_point(remote, waypoint, **kwargs):
        remote.telemetry["worldPosition"] = list(waypoint)
        return waypoint

    monkeypatch.setattr(nav, "fly_to_point", fake_fly_to_point)

    coarse = nav.ScanProfile("COARSE", 2000.0, 10.0, rescan_distance=2000.0, clearance_voxels=0)
    medium = nav.ScanProfile("MEDIUM", 1000.0, 10.0, rescan_distance=1000.0, clearance_voxels=0)
    fine = nav.ScanProfile("FINE", 300.0, 10.0, rescan_distance=200.0, clearance_voxels=0)
    controller = nav.SpaceNavigatorController(
        "fake",
        ship_radius=0.0,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=5.0,
        max_steps=2,
        target_is_obstacle=True,
    )

    result = controller.navigate_to((1850.0, 45.0, 45.0))

    assert result.status == "max_steps"
    assert result.profile == "COARSE"
    assert result.scan_count == 2
