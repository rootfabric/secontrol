from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path

HELPERS_BLOCK = r'''

def _coerce_bool(value: Any) -> bool:
    """Convert a loose telemetry value to bool."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return bool(value)


def _safe_float(value: Any) -> Optional[float]:
    """Convert value to float or return None."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _approx_equal(a: Optional[float], b: Optional[float], *, rel_tol: float = 1e-3) -> bool:
    """Compare two optional floats with relative tolerance."""

    if a is None or b is None:
        return a == b
    if a == b:
        return True
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1.0)
    return diff <= rel_tol * scale
'''

DAMAGE_BLOCK = r'''

@dataclass
class BlockInfo:
    """Representation of a block reported by the Space Engineers grid bridge."""

    block_id: int
    block_type: str
    subtype: Optional[str] = None
    name: Optional[str] = None
    state: Dict[str, Any] = field(default_factory=dict)
    local_position: Optional[tuple[float, ...]] = None
    relative_to_grid_center: Optional[tuple[float, ...]] = None
    mass: Optional[float] = None
    bounding_box: Optional[Dict[str, tuple[float, ...]]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_type(self) -> str:
        base = self.subtype or self.block_type
        if base is None:
            return ""
        return str(base).strip().lower()

    @property
    def is_damaged(self) -> bool:
        """True if the block is damaged, based on integrity < max integrity or damaged flag."""

        if _coerce_bool(self.state.get("damaged")):
            return True
        integrity = self.state.get("integrity")
        max_integrity = self.state.get("maxIntegrity")
        if isinstance(integrity, (int, float)) and isinstance(max_integrity, (int, float)):
            return integrity < max_integrity
        return False

    @staticmethod
    def _to_float_tuple(values: Any) -> Optional[tuple[float, ...]]:
        if not isinstance(values, (list, tuple)):
            return None
        try:
            return tuple(float(v) for v in values)
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "BlockInfo":
        raw_id = payload.get("id") or payload.get("blockId") or payload.get("entityId")
        if raw_id in (None, ""):
            raise ValueError("Block payload is missing identifier")
        block_id = int(raw_id)

        block_type = (
            payload.get("type")
            or payload.get("blockType")
            or payload.get("definition")
            or payload.get("SubtypeName")
            or payload.get("subtype")
            or "generic"
        )

        subtype = payload.get("subtype") or payload.get("SubtypeName")
        custom_name = payload.get("customName") or payload.get("CustomName")
        display_name = payload.get("displayName") or payload.get("DisplayName")
        raw_name = payload.get("name") or payload.get("Name")
        name = custom_name or display_name or raw_name

        state_payload = payload.get("state")
        state = state_payload if isinstance(state_payload, dict) else {}

        local_position = cls._to_float_tuple(
            payload.get("local_pos")
            or payload.get("localPos")
            or payload.get("localPosition")
        )
        relative_to_center = cls._to_float_tuple(
            payload.get("relative_to_grid_center")
            or payload.get("relativeToGridCenter")
        )

        bounding_box_payload = payload.get("bounding_box") or payload.get("boundingBox")
        bounding_box: Optional[Dict[str, tuple[float, ...]]] = None
        if isinstance(bounding_box_payload, dict):
            bounding_box = {}
            for key, value in bounding_box_payload.items():
                converted = cls._to_float_tuple(value)
                if converted is not None:
                    bounding_box[key] = converted

        mass = payload.get("mass")
        try:
            mass_value = float(mass)
        except (TypeError, ValueError):
            mass_value = None

        known_keys = {
            "id",
            "blockId",
            "entityId",
            "type",
            "blockType",
            "definition",
            "SubtypeName",
            "subtype",
            "customName",
            "CustomName",
            "displayName",
            "DisplayName",
            "name",
            "Name",
            "state",
            "local_pos",
            "localPos",
            "localPosition",
            "relative_to_grid_center",
            "relativeToGridCenter",
            "bounding_box",
            "boundingBox",
            "mass",
        }

        extra = {k: v for k, v in payload.items() if k not in known_keys}

        return cls(
            block_id=block_id,
            block_type=str(block_type),
            subtype=str(subtype) if subtype else None,
            name=str(name) if name else None,
            state=state,
            local_position=local_position,
            relative_to_grid_center=relative_to_center,
            mass=mass_value,
            bounding_box=bounding_box,
            extra=extra,
        )


@dataclass
class DamageDetails:
    """Damage payload details."""

    amount: float
    damage_type: str
    is_deformation: bool

    @classmethod
    def from_payload(cls, payload: Any) -> "DamageDetails":
        if not isinstance(payload, dict):
            return cls(amount=0.0, damage_type="Unknown", is_deformation=False)

        raw_amount = payload.get("amount")
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            amount = 0.0

        damage_type = payload.get("type") or payload.get("damageType") or "Unknown"
        is_deformation = (
            _coerce_bool(payload.get("isDeformation")) if "isDeformation" in payload else False
        )

        return cls(
            amount=amount,
            damage_type=str(damage_type),
            is_deformation=is_deformation,
        )


@dataclass
class DamageSource:
    """Damage source, usually attacker entity."""

    entity_id: Optional[int]
    name: Optional[str]
    type: Optional[str]

    @classmethod
    def from_payload(cls, payload: Any) -> "DamageSource":
        if not isinstance(payload, dict):
            return cls(entity_id=None, name=None, type=None)

        entity_id = _safe_int(payload.get("entityId") or payload.get("id"))
        name = payload.get("name")
        source_type = payload.get("type") or payload.get("definition") or payload.get("SubtypeName")

        return cls(
            entity_id=entity_id,
            name=str(name) if isinstance(name, str) and name.strip() else None,
            type=str(source_type) if isinstance(source_type, str) and source_type.strip() else None,
        )
'''


def _ensure_dataclasses_field(text: str) -> str:
    text = text.replace("from dataclasses import dataclass\n", "from dataclasses import dataclass, field\n")
    text = text.replace("from dataclasses import dataclass, field, field\n", "from dataclasses import dataclass, field\n")
    return text


def _ensure_typing_names(text: str) -> str:
    match = re.search(r"^from typing import ([^\n]+)$", text, flags=re.MULTILINE)
    if not match:
        return text

    names = []
    for raw in match.group(1).split(","):
        name = raw.strip()
        if name and name not in names:
            names.append(name)
    for required in ("Any", "Dict", "Optional"):
        if required not in names:
            names.append(required)
    new_line = "from typing import " + ", ".join(names)
    return text[: match.start()] + new_line + text[match.end():]


def _insert_helpers(text: str) -> str:
    missing = [name for name in ("_coerce_bool", "_safe_float", "_approx_equal") if f"def {name}(" not in text]
    if not missing:
        return text

    marker_candidates = [
        "\n\ndef _normalize_identity_text",
        "\n\ndef _clamp_unit",
        "\n@dataclass\nclass DeviceMetadata",
    ]
    for marker in marker_candidates:
        idx = text.find(marker)
        if idx != -1:
            return text[:idx] + HELPERS_BLOCK + text[idx:]

    raise RuntimeError("Failed to find a safe insertion point for compatibility helpers")


def _insert_damage_types(text: str) -> str:
    need_any = any(name not in text for name in ("class BlockInfo", "class DamageDetails", "class DamageSource"))
    if not need_any:
        return text

    if "class DeviceMetadata" not in text:
        raise RuntimeError("DeviceMetadata was not found in base_device.py")

    block_to_insert = DAMAGE_BLOCK
    if "class BlockInfo" in text:
        block_to_insert = block_to_insert.split("\n\n@dataclass\nclass DamageDetails", 1)[1]
        block_to_insert = "\n\n@dataclass\nclass DamageDetails" + block_to_insert
    if "class DamageDetails" in text and "class DamageSource" not in text:
        block_to_insert = block_to_insert.split("\n\n@dataclass\nclass DamageSource", 1)[1]
        block_to_insert = "\n\n@dataclass\nclass DamageSource" + block_to_insert
    elif "class DamageDetails" in text and "class DamageSource" in text:
        return text

    marker_candidates = [
        "\n\nclass Grid:",
        "\n\n@dataclass\nclass BaseDevice",
        "\n\nclass BaseDevice",
        "\n\n@dataclass\nclass GenericDevice",
    ]
    for marker in marker_candidates:
        idx = text.find(marker)
        if idx != -1:
            return text[:idx] + block_to_insert + text[idx:]

    raise RuntimeError("Failed to find a safe insertion point for BlockInfo/Damage types")


def patch_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    text = _ensure_dataclasses_field(text)
    text = _ensure_typing_names(text)
    text = _insert_helpers(text)
    text = _insert_damage_types(text)

    if text == original:
        return False

    backup = path.with_suffix(path.suffix + ".before_blockinfo_fix.bak")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    base_device = repo_root / "src" / "secontrol" / "base_device.py"
    grids = repo_root / "src" / "secontrol" / "grids.py"

    if not base_device.exists():
        print(f"ERROR: file not found: {base_device}")
        return 2
    if not grids.exists():
        print(f"ERROR: file not found: {grids}")
        return 2

    changed = patch_file(base_device)

    try:
        py_compile.compile(str(base_device), doraise=True)
        py_compile.compile(str(grids), doraise=True)
    except py_compile.PyCompileError as exc:
        print("ERROR: py_compile failed")
        print(exc)
        return 3

    if changed:
        print(f"Patched: {base_device}")
        print(f"Backup:  {base_device}.before_blockinfo_fix.bak")
    else:
        print(f"No changes needed: {base_device}")
    print("OK: base_device.py and grids.py compile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
