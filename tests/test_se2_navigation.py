import math
from unittest.mock import Mock
import pytest
from secontrol.se2_navigation import AutopilotDevice
from secontrol.se2 import BridgeError


def device():
    client = Mock()
    return AutopilotDevice(client, "epoch", {"id": "autopilot:1:1", "gridId": "1:1", "name": "Pilot"})


def test_navigation_payload_and_no_switch_commands():
    pilot = device()
    pilot.goto([1, 2, 3], forward=[0, 0, -1], up=[0, 1, 0], max_speed=2)
    args = pilot.client.command.call_args
    assert args.args == (pilot, "autopilot_goto")
    assert args.kwargs["navigation"]["target"] == [1, 2, 3]
    assert args.kwargs["navigation"]["maxSpeed"] == 2
    assert "enable" not in pilot.commands


def test_nonfinite_coordinates_rejected_before_transport():
    pilot = device()
    with pytest.raises(ValueError):
        pilot.goto([math.nan, 0, 0])
    pilot.client.command.assert_not_called()


def test_wait_observes_arrival_for_matching_mission():
    pilot = device()
    pilot.refresh = Mock(return_value={"status": "Arrived", "properties": {"missionId": "expected"}})
    assert pilot.wait("expected")["status"] == "Arrived"


def test_wait_surfaces_game_failure():
    pilot = device()
    pilot.refresh = Mock(return_value={"status": "Failed", "properties": {"missionId": "expected", "error": "insufficient_thrust"}})
    with pytest.raises(BridgeError, match="insufficient_thrust"):
        pilot.wait("expected")


def test_align_course_flag_reaches_navigation_payload():
    pilot = device()
    pilot.goto([1, 2, 3], max_speed=2, align_course=True)
    navigation = pilot.client.command.call_args.kwargs["navigation"]
    assert navigation["alignCourse"] is True


def test_align_course_rejects_forward_and_ground_before_transport():
    pilot = device()
    with pytest.raises(ValueError, match="forward"):
        pilot.goto([1, 2, 3], forward=[0, 0, -1], align_course=True)
    with pytest.raises(ValueError, match="ground"):
        pilot.goto([1, 2, 3], mode="ground", align_course=True)
    pilot.client.command.assert_not_called()


def test_keep_control_on_player_is_default_and_invertible():
    pilot = device()
    pilot.goto([1, 2, 3])
    assert pilot.client.command.call_args.kwargs["navigation"]["keepControlOnPlayer"] is True
    pilot.goto([1, 2, 3], cancel_on_player=True)
    assert pilot.client.command.call_args.kwargs["navigation"]["keepControlOnPlayer"] is False
