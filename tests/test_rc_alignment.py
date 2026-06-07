"""Тесты для ``examples.organized.diagnostics.check_rc_alignment``.

Модуль загружается через ``importlib`` по абсолютному пути, чтобы не
загрязнять ``sys.path`` и не зависеть от того, как именно оформлен ``examples``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = (
    _REPO_ROOT
    / "examples"
    / "organized"
    / "diagnostics"
    / "check_rc_alignment.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("check_rc_alignment", _MODULE_PATH)
    assert spec is not None and spec.loader is not None, "cannot load check_rc_alignment"
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_rc_alignment", module)
    spec.loader.exec_module(module)
    return module


check_rc = _load_module()


diagnose_rc_placement = check_rc.diagnose_rc_placement
_read_local_orientation = check_rc._read_local_orientation
_find_rc_block = check_rc._find_rc_block
_classify_placement = check_rc._classify_placement


class FakeBlock:
    def __init__(self, block_id: int, extra: Optional[Dict[str, Any]] = None) -> None:
        self.block_id = block_id
        self.extra = extra or {}


class FakeRC:
    def __init__(
        self,
        device_id: str = "42",
        name: str = "RC",
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.device_id = device_id
        self.name = name
        self.telemetry = telemetry or {}
        self.update_calls = 0

    def update(self) -> None:
        self.update_calls += 1


class FakeGrid:
    def __init__(self, blocks: Dict[int, FakeBlock], rcs: List[FakeRC]) -> None:
        self.blocks = blocks
        self._rcs = rcs

    def find_devices_by_type(self, _device_type: Any) -> List[FakeRC]:
        return list(self._rcs)


def _standard_orientation() -> Dict[str, Any]:
    return {
        "orientation": {
            "forward": {"x": 0.0, "y": 0.0, "z": 1.0},
            "up": {"x": 0.0, "y": 1.0, "z": 0.0},
        }
    }


def test_classify_placement_standard_is_ok():
    assert _classify_placement("Forward", "Up") == ("OK", "info")


def test_classify_placement_reversed():
    assert _classify_placement("Backward", "Up") == ("REVERSED", "warn")
    assert _classify_placement("Backward", "Down") == ("REVERSED", "warn")


def test_classify_placement_off_axis_vertical_and_horizontal():
    assert _classify_placement("Up", "Forward") == ("OFF_AXIS_VERTICAL", "warn")
    assert _classify_placement("Down", "Forward") == ("OFF_AXIS_VERTICAL", "warn")
    assert _classify_placement("Left", "Up") == ("OFF_AXIS_HORIZONTAL", "warn")
    assert _classify_placement("Right", "Up") == ("OFF_AXIS_HORIZONTAL", "warn")


def test_classify_placement_upside_down_and_rolled():
    assert _classify_placement("Forward", "Down") == ("OK_UPSIDE_DOWN", "warn")
    assert _classify_placement("Forward", "Left") == ("OK_ROLLED", "warn")
    assert _classify_placement("Forward", "Right") == ("OK_ROLLED", "warn")


def test_classify_placement_unknown_falls_back():
    assert _classify_placement("???", "???") == ("UNKNOWN", "warn")


def test_read_local_orientation_snake_case():
    block = FakeBlock(1, {"local_orientation": {"forward": "Forward", "up": "Up"}})
    assert _read_local_orientation(block) == {"forward": "Forward", "up": "Up"}


def test_read_local_orientation_camel_case_keys():
    block = FakeBlock(
        1,
        {"localOrientation": {"Forward": "Forward", "Up": "Up", "Left": "Left"}},
    )
    assert _read_local_orientation(block) == {
        "forward": "Forward",
        "up": "Up",
        "left": "Left",
    }


def test_read_local_orientation_ignores_invalid_values():
    block = FakeBlock(
        1,
        {"local_orientation": {"forward": "Sideways", "up": "Up"}},
    )
    assert _read_local_orientation(block) == {"up": "Up"}


def test_read_local_orientation_returns_none_when_missing():
    assert _read_local_orientation(None) is None
    assert _read_local_orientation(FakeBlock(1, {})) is None
    assert _read_local_orientation(FakeBlock(1, {"local_orientation": {}})) is None
    assert _read_local_orientation(FakeBlock(1, {"local_orientation": "oops"})) is None


def test_read_local_orientation_from_raw_dict_block():
    raw = {
        "local_orientation": {"forward": "Backward", "up": "Up"},
        "id": 7,
    }
    assert _read_local_orientation(raw) == {"forward": "Backward", "up": "Up"}


def test_find_rc_block_matches_by_id():
    rc = FakeRC(device_id="42")
    block = FakeBlock(42)
    grid = FakeGrid({42: block}, [rc])
    assert _find_rc_block(grid, rc) is block


def test_find_rc_block_returns_none_when_missing():
    rc = FakeRC(device_id="42")
    grid = FakeGrid({99: FakeBlock(99)}, [rc])
    assert _find_rc_block(grid, rc) is None


def test_diagnose_no_rc():
    grid = FakeGrid({}, [])
    diag = diagnose_rc_placement(grid, {"grid": "empty"})
    section = diag["rc_alignment"]
    assert section["status"] == "ERROR_NO_RC"
    assert section["ok"] is False
    assert diag["ok"] is False
    assert "Remote Control" in section["warnings"][0]


def test_diagnose_ok_for_standard_placement():
    rc = FakeRC(device_id="42", telemetry=_standard_orientation())
    block = FakeBlock(42, {"local_orientation": {"forward": "Forward", "up": "Up"}})
    grid = FakeGrid({42: block}, [rc])
    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["status"] == "OK"
    assert section["ok"] is True
    primary = section["primary_rc"]
    assert primary["local_forward"] == "Forward"
    assert primary["angle_to_grid_forward_deg"] == 0.0
    assert primary["world_forward_len"] == pytest.approx(1.0)
    assert primary["world_up_len"] == pytest.approx(1.0)
    assert primary["world_forward_dot_up"] == pytest.approx(0.0, abs=1e-6)


def test_diagnose_reversed_block_warns():
    rc = FakeRC(device_id="42", telemetry=_standard_orientation())
    block = FakeBlock(42, {"local_orientation": {"forward": "Backward", "up": "Up"}})
    grid = FakeGrid({42: block}, [rc])
    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["status"] == "REVERSED"
    assert section["ok"] is False
    primary = section["primary_rc"]
    assert primary["angle_to_grid_forward_deg"] == 180.0
    assert any("Backward" in w for w in section["warnings"])
    assert any("180" in rec for rec in section["recommendations"])


def test_diagnose_off_axis_vertical():
    rc = FakeRC(device_id="42", telemetry={
        "orientation": {
            "forward": {"x": 0.0, "y": 1.0, "z": 0.0},
            "up": {"x": 0.0, "y": 0.0, "z": -1.0},
        }
    })
    block = FakeBlock(42, {"local_orientation": {"forward": "Up", "up": "Backward"}})
    grid = FakeGrid({42: block}, [rc])
    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["status"] == "OFF_AXIS_VERTICAL"
    assert section["ok"] is False
    assert section["primary_rc"]["angle_to_grid_forward_deg"] == 90.0


def test_diagnose_missing_block_metadata():
    rc = FakeRC(device_id="42")
    grid = FakeGrid({}, [rc])
    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["status"] == "ERROR_NO_BLOCK_METADATA"
    assert section["ok"] is False


def test_diagnose_missing_local_orientation():
    rc = FakeRC(device_id="42")
    block = FakeBlock(42, {"orientation": {"forward": {"x": 0, "y": 0, "z": 1}}})
    grid = FakeGrid({42: block}, [rc])
    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["status"] == "ERROR_NO_LOCAL_ORIENTATION"
    assert section["ok"] is False
    assert any("плагин" in rec for rec in section["recommendations"])


def test_diagnose_degenerate_world_basis():
    rc = FakeRC(device_id="42", telemetry={
        "orientation": {
            "forward": {"x": 1.0, "y": 0.0, "z": 0.0},
            "up": {"x": 0.5, "y": 0.5, "z": 0.0},
        }
    })
    block = FakeBlock(42, {"local_orientation": {"forward": "Forward", "up": "Up"}})
    grid = FakeGrid({42: block}, [rc])
    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["status"] == "WARN_DEGENERATE_ORIENTATION"
    assert section["ok"] is False
    assert any("вырожден" in w for w in section["warnings"])


def test_diagnose_updates_external_diagnostic_dict():
    rc = FakeRC(device_id="42", telemetry=_standard_orientation())
    block = FakeBlock(42, {"local_orientation": {"forward": "Forward", "up": "Up"}})
    grid = FakeGrid({42: block}, [rc])

    external: Dict[str, Any] = {"grid": "test"}
    result = diagnose_rc_placement(grid, external)
    assert result is external
    assert external["rc_alignment"]["status"] == "OK"


def test_diagnose_multiple_rcs_reports_each():
    rc1 = FakeRC(device_id="1", name="RC-front", telemetry=_standard_orientation())
    rc2 = FakeRC(
        device_id="2",
        name="RC-side",
        telemetry={
            "orientation": {
                "forward": {"x": 1.0, "y": 0.0, "z": 0.0},
                "up": {"x": 0.0, "y": 1.0, "z": 0.0},
            }
        },
    )
    block1 = FakeBlock(1, {"local_orientation": {"forward": "Forward", "up": "Up"}})
    block2 = FakeBlock(2, {"local_orientation": {"forward": "Right", "up": "Up"}})
    grid = FakeGrid({1: block1, 2: block2}, [rc1, rc2])

    diag = diagnose_rc_placement(grid)
    section = diag["rc_alignment"]
    assert section["ok"] is False
    assert len(section["rcs"]) == 2
    assert {r["status"] for r in section["rcs"]} == {"OK", "OFF_AXIS_HORIZONTAL"}
    assert section["primary_rc"]["status"] == "OK"


def test_update_is_called_on_each_rc():
    rc = FakeRC(device_id="42", telemetry=_standard_orientation())
    block = FakeBlock(42, {"local_orientation": {"forward": "Forward", "up": "Up"}})
    grid = FakeGrid({42: block}, [rc])
    diagnose_rc_placement(grid)
    assert rc.update_calls == 1
