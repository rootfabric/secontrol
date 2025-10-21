from __future__ import annotations

from typing import Any, Optional

import pytest

from secontrol.base_device import BlockInfo, Grid


class DummySubscription:
    def close(self) -> None:  # pragma: no cover - trivial
        pass


class DummyRedis:
    def __init__(self, payload: Optional[dict[str, Any]] = None) -> None:
        self._payload = payload or {}
        self.callback = None
        self.published: list[tuple[str, dict[str, Any]]] = []

    def subscribe_to_key(self, key: str, callback):
        self.callback = callback
        return DummySubscription()

    def get_json(self, key: str):
        return self._payload

    def publish(self, channel: str, message: dict[str, Any]) -> int:
        self.published.append((channel, message))
        return 1


def make_grid(payload: dict[str, Any]) -> Grid:
    dummy = DummyRedis(payload)
    return Grid(dummy, owner_id="1", grid_id="2", player_id="3")


def test_grid_collects_blocks_from_payload():
    payload = {
        "blocks": [
            {
                "id": 95151489158652896,
                "type": "SmallBlockCockpit",
                "state": {
                    "functional": True,
                    "enabled": False,
                    "working": True,
                    "buildRatio": 1,
                    "integrity": 3075,
                    "maxIntegrity": 3180,
                    "damaged": False,
                },
                "local_pos": [0, 0, -1.5],
                "relative_to_grid_center": [-0.999652, 0.479469, -1.258294],
                "mass": 0,
                "bounding_box": {
                    "min": [1047593.21872, 176278.537337, 1668439.557989],
                    "max": [1047595.663772, 176280.887861, 1668442.168112],
                },
            }
        ],
        "devices": [],
    }

    grid = make_grid(payload)
    block_id = 95151489158652896

    block = grid.get_block(block_id)
    assert isinstance(block, BlockInfo)
    assert block.block_type == "SmallBlockCockpit"
    assert block.state["enabled"] is False
    assert block.local_position == (0.0, 0.0, -1.5)
    assert block.relative_to_grid_center == (-0.999652, 0.479469, -1.258294)
    assert block.mass == 0.0
    assert block.bounding_box == {
        "min": (1047593.21872, 176278.537337, 1668439.557989),
        "max": (1047595.663772, 176280.887861, 1668442.168112),
    }

    all_blocks = list(grid.iter_blocks())
    assert len(all_blocks) == 1
    assert all_blocks[0] is block

    by_type = grid.find_blocks_by_type("SmallBlockCockpit")
    assert by_type == [block]
    assert grid.find_blocks_by_type("smallblockcockpit") == [block]


def test_grid_paint_block_accepts_block_info():
    payload = {
        "blocks": [
            {
                "id": 42,
                "type": "LargeBlockArmor",
            }
        ],
        "devices": [],
    }

    dummy = DummyRedis(payload)
    grid = Grid(dummy, owner_id="10", grid_id="20", player_id="30")
    block = grid.get_block(42)
    assert isinstance(block, BlockInfo)

    dummy.published.clear()
    result = grid.paint_block(block, color="#123456")

    assert result == 1
    assert dummy.published, "paint_block should publish a command"
    channel, message = dummy.published[-1]
    assert channel == "se.30.commands.grid.20"
    assert message["cmd"] == "paint_block"
    assert message["blockId"] == 42
    assert message["rgb"] == {"r": 0x12, "g": 0x34, "b": 0x56}


def test_grid_paint_blocks_batches_identifiers():
    payload = {
        "blocks": [
            {"id": 100, "type": "ArmorBlock"},
            {"id": 200, "type": "InteriorWall"},
        ],
        "devices": [],
    }

    dummy = DummyRedis(payload)
    grid = Grid(dummy, owner_id="11", grid_id="22", player_id="33")
    first_block = grid.get_block(100)

    result = grid.paint_blocks([first_block, "200"], hsv=(120, 0.5, 0.75), play_sound=False)

    assert result == 1
    assert dummy.published, "paint_blocks should publish a command"
    channel, message = dummy.published[-1]
    assert channel == "se.33.commands.grid.22"
    assert message["cmd"] == "paint_blocks"
    assert message["blocks"] == [{"blockId": 100}, {"blockId": 200}]
    assert message["playSound"] is False
    assert message["hsv"]["h"] == pytest.approx(120 / 360)
    assert message["hsv"]["s"] == pytest.approx(0.5)
    assert message["hsv"]["v"] == pytest.approx(0.75)


def test_paint_blocks_requires_identifiers():
    dummy = DummyRedis({"blocks": [], "devices": []})
    grid = Grid(dummy, owner_id="1", grid_id="2", player_id="3")

    with pytest.raises(ValueError):
        grid.paint_blocks([], color=(1, 0, 0))

    with pytest.raises(ValueError):
        grid.paint_blocks(["not-a-number"], color=(1, 0, 0))
