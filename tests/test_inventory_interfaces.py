from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from secontrol.base_device import DeviceMetadata
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.refinery_device import RefineryDevice


class DummySubscription:
    def close(self) -> None:  # pragma: no cover - simple stub
        pass


class DummyRedis:
    def __init__(self, payload: Optional[dict[str, Any]] = None) -> None:
        self._payload = payload or {}
        self.last_command: Optional[dict[str, Any]] = None
        self.published: list[tuple[str, dict[str, Any]]] = []

    def subscribe_to_key_resilient(self, key: str, callback):
        self._callback = callback
        return DummySubscription()

    def get_json(self, key: str):
        return self._payload

    def publish(self, channel: str, payload: dict[str, Any]) -> int:
        self.last_command = payload
        self.published.append((channel, payload))
        return 1

    def set_json(self, key: str, value: Any, expire: int | None = None) -> None:  # pragma: no cover - unused in tests
        pass


class DummyGrid:
    def __init__(self, redis: DummyRedis) -> None:
        self.redis = redis
        self.owner_id = "1"
        self.grid_id = "2"
        self.player_id = "3"


@pytest.fixture
def refinery_telemetry() -> dict[str, Any]:
    return {
        "id": 128570790678436671,
        "type": "MyObjectBuilder_Refinery",
        "subtype": "LargeRefinery",
        "name": "Refinery",
        "ownerId": 144115188075855919,
        "gridId": 127168092107255649,
        "gridName": "My Renamed Grid",
        "enabled": False,
        "useConveyorSystem": True,
        "isProducing": True,
        "isQueueEmpty": False,
        "currentProgress": 0,
        "queue": [],
        "inputInventory": {
            "currentVolume": 4.293846,
            "maxVolume": 7.5,
            "currentMass": 11604.993451,
            "items": [
                {
                    "type": "MyObjectBuilder_Ore",
                    "subtype": "Magnesium",
                    "amount": 6236.5858,
                    "displayName": "Magnesium Ore",
                },
                {
                    "type": "MyObjectBuilder_Ore",
                    "subtype": "Uranium",
                    "amount": 5368.407651,
                    "displayName": "Uranium Ore",
                },
            ],
        },
        "outputInventory": {
            "currentVolume": 0.018841,
            "maxVolume": 7.5,
            "currentMass": 97.399034,
            "items": [
                {
                    "type": "MyObjectBuilder_Ingot",
                    "subtype": "Magnesium",
                    "amount": 26.343899,
                    "displayName": "Magnesium Powder",
                },
                {
                    "type": "MyObjectBuilder_Ingot",
                    "subtype": "Gold",
                    "amount": 71.055135,
                    "displayName": "Gold Ingot",
                },
            ],
        },
    }


@pytest.fixture
def refinery_device(refinery_telemetry: dict[str, Any]) -> RefineryDevice:
    redis = DummyRedis(refinery_telemetry)
    grid = DummyGrid(redis)
    metadata = DeviceMetadata(
        device_type="refinery",
        device_id=str(refinery_telemetry["id"]),
        telemetry_key="test:refinery",
        grid_id=grid.grid_id,
    )
    return RefineryDevice(grid, metadata)


def test_refinery_inventories_discovered(refinery_device: RefineryDevice) -> None:
    snapshots = refinery_device.inventories()
    assert len(snapshots) == 2

    names = {snap.name for snap in snapshots}
    assert "Input Inventory" in names
    assert "Output Inventory" in names

    input_items = refinery_device.items("inputInventory")
    assert {item.subtype for item in input_items} == {"Magnesium", "Uranium"}

    output_items = refinery_device.items("outputInventory")
    assert {item.subtype for item in output_items} == {"Magnesium", "Gold"}

    combined = refinery_device.items()
    assert len(combined) == len(input_items) + len(output_items)

    capacity = refinery_device.capacity("inputInventory")
    assert capacity["currentVolume"] == pytest.approx(4.293846)
    assert capacity["maxVolume"] == pytest.approx(7.5)


def test_move_items_with_inventory_indexes(refinery_device: RefineryDevice) -> None:
    redis: DummyRedis = refinery_device.redis  # type: ignore[assignment]
    redis.published.clear()

    refinery_device.move_subtype(
        555,
        "Gold",
        source_inventory="outputInventory",
        destination_inventory=1,
    )

    assert redis.published, "move_subtype should publish a command"
    _channel, message = redis.published[-1]
    payload = json.loads(message["state"])
    assert payload["fromInventoryIndex"] == 1
    assert payload["toInventoryIndex"] == 1
    assert payload["items"] == [{"subtype": "Gold"}]


def test_container_device_alias_still_available() -> None:
    assert ContainerDevice.Item is ContainerDevice.Item  # type: ignore[attr-defined]
