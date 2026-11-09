import json
import time
from unittest.mock import Mock

import pytest

from secontrol.se2 import BridgeError, Client, LampDevice


def ready(epoch="test:1"):
    return {"state": "READY", "epoch": epoch, "sampledAtMs": int(time.time() * 1000),
            "lamps": [{"id": "1:2", "gridId": "3:4", "gridName": "Test", "name": "Interior Light 0.5\u00a0m",
                       "enabled": True, "working": True, "revision": 1}]}


@pytest.fixture
def client(monkeypatch):
    backend = Mock()
    monkeypatch.setattr("secontrol.se2.redis.Redis.from_url", lambda *a, **kw: backend)
    c = Client()
    backend.get.return_value = json.dumps(ready())
    return c


def test_names_and_opaque_ids(client):
    lamp, = client.lamps(name="Interior Light 0.5 m")
    assert (lamp.device_id, lamp.grid_id) == ("1:2", "3:4")


def test_no_write_after_session_change(client):
    lamp, = client.lamps()
    client.redis.get.return_value = json.dumps(ready("different:1"))
    with pytest.raises(BridgeError, match="Session changed"):
        lamp.disable()
    client.redis.eval.assert_not_called()


def test_no_write_from_stale_telemetry(client):
    stale = ready()
    stale["sampledAtMs"] -= 10000
    client.redis.get.return_value = json.dumps(stale)
    with pytest.raises(BridgeError, match="Stale"):
        client.lamps()


def test_full_queue_is_explicit(client):
    lamp, = client.lamps()
    client.redis.eval.return_value = 0
    with pytest.raises(BridgeError, match="queue is full"):
        lamp.enable()


def test_confirmed_result_not_publish_count(client):
    lamp, = client.lamps()
    state = ready()["lamps"][0] | {"enabled": False}
    client.redis.get.side_effect = [json.dumps(ready()), json.dumps({"status": "confirmed", "actualState": state})]
    result = lamp.disable()
    assert result.status == "confirmed"
    assert lamp.is_enabled() is False
    payload = json.loads(client.redis.eval.call_args.args[-1])
    assert payload["deviceId"] == "1:2"
    assert payload["cmd"] == "disable"
    assert len(payload["requestId"]) == 32


def test_rejection_never_updates_cached_state(client):
    lamp, = client.lamps()
    client.redis.get.side_effect = [json.dumps(ready()), json.dumps({"status": "rejected", "error": "revision_conflict"})]
    with pytest.raises(BridgeError, match="revision_conflict"):
        lamp.disable()
    assert lamp.is_enabled() is True


def test_bool_validation(client):
    lamp, = client.lamps()
    with pytest.raises(TypeError):
        lamp.set_enabled("false")


def test_no_change_to_se1_device_registration():
    from secontrol.devices.lamp_device import LampDevice as SE1Lamp
    from secontrol.base_device import DEVICE_TYPE_MAP
    assert DEVICE_TYPE_MAP["lamp"] is SE1Lamp
    assert SE1Lamp is not LampDevice


def test_mixed_device_factory_and_shared_switch(client):
    from secontrol.se2 import DoorDevice, FunctionalDevice
    data = ready()
    lamp = data["lamps"][0] | {"type": "lamp"}
    door = lamp | {"id": "9:1", "name": "Door", "type": "door", "status": "Closed"}
    data["devices"] = [lamp, door]
    client.redis.get.return_value = json.dumps(data)
    devices = client.devices()
    assert isinstance(devices[0], LampDevice)
    assert isinstance(devices[1], DoorDevice)
    assert LampDevice.enable is DoorDevice.enable is FunctionalDevice.enable
    assert [d.device_id for d in client.doors()] == ["9:1"]
    client.redis.get.side_effect = [json.dumps(data), json.dumps({"status": "confirmed", "actualState": door | {"status": "Open"}})]
    result = devices[1].open()
    assert result.actual_state["status"] == "Open"
    assert json.loads(client.redis.eval.call_args.args[-1])["cmd"] == "open"


def test_lamp_rejects_door_capability_before_enqueue(client):
    lamp, = client.lamps()
    with pytest.raises(BridgeError, match="Unsupported"):
        client.command(lamp, "open")
    client.redis.eval.assert_not_called()


def test_device_timestamp_not_snapshot_completion_time(client):
    lamp, = client.lamps()
    data = ready()
    data["lamps"][0]["measuredAtMs"] = int(time.time() * 1000) - 10000
    client.redis.get.return_value = json.dumps(data)
    with pytest.raises(BridgeError, match="Stale device"):
        lamp.refresh()


def test_extended_device_dispatch_and_validation(client):
    from secontrol.se2 import ThrusterDevice, GravityDevice, LandingGearDevice, CargoDevice
    snapshot = ready()
    base = snapshot["lamps"][0] | {"type": "thruster"}
    snapshot["devices"] = [base, base | {"id": "2:2", "type": "gravity_generator"},
                           base | {"id": "3:3", "type": "landing_gear"},
                           base | {"id": "4:4", "type": "cargo", "properties": {"items": []}}]
    client.redis.get.return_value = json.dumps(snapshot)
    thrust, gravity, gear, cargo = client.devices()
    assert isinstance(thrust, ThrusterDevice)
    assert isinstance(gravity, GravityDevice)
    assert isinstance(gear, LandingGearDevice)
    assert isinstance(cargo, CargoDevice)
    with pytest.raises(ValueError):
        thrust.set_thrust_override(1.5)
    with pytest.raises(ValueError):
        gravity.set_gravity(float("nan"))
    with pytest.raises(TypeError):
        gear.set_auto_lock(1)
    with pytest.raises(BridgeError, match="Unsupported"):
        client.command(cargo, "enable")
    client.redis.eval.assert_not_called()


def test_new_property_command_payloads(client):
    from secontrol.se2 import AntennaDevice, ConverterDevice, LampDevice
    snapshot = ready()
    item = snapshot["lamps"][0]
    snapshot["devices"] = [item | {"type": "lamp"},
                           item | {"id": "2:2", "type": "antenna"},
                           item | {"id": "3:3", "type": "Reactor"}]
    client.redis.get.return_value = json.dumps(snapshot)
    lamp, antenna, reactor = client.devices()
    assert isinstance(lamp, LampDevice)
    assert isinstance(antenna, AntennaDevice)
    assert isinstance(reactor, ConverterDevice)
    with pytest.raises(ValueError):
        lamp.set_brightness(-1)
    with pytest.raises(TypeError):
        antenna.set_broadcast("yes")
    with pytest.raises(TypeError):
        reactor.set_processing(1)
    client.redis.eval.assert_not_called()
