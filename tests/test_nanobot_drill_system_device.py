import pytest

from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice


def _make_device(telemetry):
    device = NanobotDrillSystemDevice.__new__(NanobotDrillSystemDevice)
    device.telemetry = telemetry
    issued = {}

    def _fake_send(payload):
        issued["payload"] = payload
        return payload

    device.send_command = _fake_send  # type: ignore[attr-defined]
    return device, issued


def _sample_telemetry():
    return {
        "id": 86739460838529603,
        "type": "MyObjectBuilder_Drill",
        "subtype": "SELtdLargeNanobotDrillSystem",
        "name": "DrillSystem",
        "ownerId": 144115188075855919,
        "load": {
            "window": 32,
            "update": {
                "lastMs": 0.951,
                "avgMs": 2.109659,
                "peakMs": 13.5172,
                "samples": 32,
            },
            "commands": {
                "lastMs": 0,
                "avgMs": 0,
                "peakMs": 0,
                "samples": 0,
            },
            "total": {
                "avgMs": 2.109659,
                "peakMs": 13.5172,
            },
        },
        "enabled": False,
        "isFunctional": True,
        "isWorking": False,
        "actions": [
            {"id": "OnOff_On"},
            {"id": "OnOff_Off"},
            {"id": "Collect_On"},
            {"id": "Drill_On"},
            {"id": "Fill_On"},
            {"id": "CollectIfIdle_On"},
            {"id": "CollectIfIdle_Off"},
        ],
        "status": {
            "type": "DrillSystem",
            "max_required_input": "160.02 kW",
        },
        "oreFilters": ["Iron", "Nickel", "Stone"],
    }


def test_nanobot_drill_system_telemetry_helpers():
    telemetry = _sample_telemetry()
    device, _ = _make_device(telemetry)

    assert device.load_window() == 32
    assert device.load_update_metrics()["avgMs"] == pytest.approx(2.109659)
    assert device.load_command_metrics()["samples"] == pytest.approx(0)
    assert device.load_total_metrics()["peakMs"] == pytest.approx(13.5172)
    assert device.max_required_input_kw() == pytest.approx(160.02)
    assert "Drill_On" in device.available_action_ids()
    assert device.ore_filters() == ["Iron", "Nickel", "Stone"]
    assert device.known_ore_targets() == ["Iron", "Nickel", "Stone"]


def test_nanobot_drill_system_commands_and_filters():
    telemetry = _sample_telemetry()
    device, issued = _make_device(telemetry)

    device.set_ore_filters(["Uranium"])
    assert issued["payload"] == {
        "cmd": "set",
        "payload": {
            "property": "DrillSystem.OreFilter",
            "value": ["Uranium"],
        },
    }

    device.start_drilling()
    assert issued["payload"] == {"command": "Drill_On", "payload": {}}

    device.stop_drilling()
    assert issued["payload"] == {"command": "OnOff_Off", "payload": {}}

    with pytest.raises(ValueError):
        device.set_ore_filters([])
