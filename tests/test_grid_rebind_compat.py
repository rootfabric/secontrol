from __future__ import annotations

from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.grids import Grid


class _Subscription:
    def close(self):
        pass


class FakeRedis:
    def __init__(self):
        self.store = {
            "se:owner:grid:1:gridinfo": {
                "id": 1,
                "name": "scout",
                "blocks": [
                    {
                        "id": 10,
                        "type": "MyObjectBuilder_RemoteControl",
                        "customName": "Remote Control",
                        "isDevice": True,
                    }
                ],
            },
            "se:owner:grid:1:remote_control:10:telemetry": {
                "worldPosition": [1.0, 2.0, 3.0],
                "autopilotEnabled": False,
            },
            "se:owner:grid:2:gridinfo": {
                "id": 2,
                "name": "scout",
                "blocks": [
                    {
                        "id": 20,
                        "type": "MyObjectBuilder_RemoteControl",
                        "customName": "Remote Control",
                        "isDevice": True,
                    }
                ],
            },
            "se:owner:grid:2:remote_control:20:telemetry": {
                "worldPosition": [4.0, 5.0, 6.0],
                "autopilotEnabled": False,
            },
        }
        self.published = []

    def get_json(self, key):
        return self.store.get(key)

    def set_json(self, key, value):
        self.store[key] = value

    def subscribe_to_key(self, key, callback, **kwargs):
        return _Subscription()

    def subscribe_to_channel(self, channel, callback):
        return _Subscription()

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1

    def list_grids(self, owner_id):
        return [{"id": 2, "name": "scout"}]


def test_device_update_refreshes_telemetry_snapshot():
    redis = FakeRedis()
    grid = Grid(redis, "owner", "1", "player", "scout", auto_wake=False)
    rc = grid.find_devices_by_type(RemoteControlDevice)[0]

    redis.store[rc.telemetry_key] = {"worldPosition": [7.0, 8.0, 9.0]}

    assert rc.update()["worldPosition"] == [7.0, 8.0, 9.0]


def test_device_wait_for_telemetry_uses_update_refresh():
    redis = FakeRedis()
    grid = Grid(redis, "owner", "1", "player", "scout", auto_wake=False)
    rc = grid.find_devices_by_type(RemoteControlDevice)[0]

    redis.store[rc.telemetry_key] = {"worldPosition": [9.0, 8.0, 7.0]}

    assert rc.wait_for_telemetry(timeout=0.2, wait_for_new=True, need_update=True)
    assert rc.telemetry["worldPosition"] == [9.0, 8.0, 7.0]


def test_command_rebinds_grid_and_device_after_restart():
    redis = FakeRedis()
    grid = Grid(redis, "owner", "1", "player", "scout", auto_wake=False)
    rc = grid.find_devices_by_type(RemoteControlDevice)[0]

    grid.mark_identity_suspect("test restart")
    rc.goto("0,0,0", speed=3)

    channel, payload = redis.published[-1]
    assert grid.grid_id == "2"
    assert rc.device_id == "20"
    assert channel == "se.player.commands.device.20"
    assert payload["targetId"] == 20
    assert payload["gridId"] == 2
