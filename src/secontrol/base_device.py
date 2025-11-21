"""Base device functionality for Space Engineers grid control.

This module contains the base device class and grid management functionality
that all specific devices build upon.
"""

from __future__ import annotations

import colorsys
import copy
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Type

from .inventory import InventoryItem, InventorySnapshot, parse_inventory_payload


# DEVICE_TYPE_MAP пополняется модулями устройств и внешними плагинами при импорте
DEVICE_TYPE_MAP = {}

def get_device_class(device_type: str):
    """Возвращает класс устройства по его типу."""
    return DEVICE_TYPE_MAP.get(device_type, BaseDevice)

DEVICE_REGISTRY = {
    "MyObjectBuilder_Projector": "projector",  # будет разрешено через DEVICE_TYPE_MAP
    "MyObjectBuilder_BatteryBlock": "battery",  # будет разрешено через DEVICE_TYPE_MAP
    "MyObjectBuilder_SmallGatlingGun": "weapon",
    "MyObjectBuilder_SmallMissileLauncher": "weapon",
    "MyObjectBuilder_SmallMissileLauncherReload": "weapon",
    "MyObjectBuilder_LargeGatlingGun": "weapon",
    "MyObjectBuilder_LargeMissileLauncher": "weapon",
    "MyObjectBuilder_InteriorTurret": "interior_turret",
    "weapon": "weapon",
    "interior_turret": "interior_turret",
    # дополняй по мере надобности
}


def _safe_int(value: Any) -> Optional[int]:
    """Преобразует значение к ``int`` или возвращает ``None``."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool:
    """Преобразует произвольное значение к булеву типу."""

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
    """Преобразует значение к ``float`` или возвращает ``None``."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _approx_equal(a: Optional[float], b: Optional[float], *, rel_tol: float = 1e-3) -> bool:
    """Сравнивает два числа с учётом относительной погрешности."""

    if a is None or b is None:
        return a == b
    if a == b:
        return True
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1.0)
    return diff <= rel_tol * scale


def _clamp_unit(value: float) -> float:
    value = float(value)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _normalize_unit(value: float) -> float:
    value = float(value)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        if value <= 100.0:
            return _clamp_unit(value / 100.0)
        return _clamp_unit(value / 255.0)
    return value


def _normalize_hue(value: float) -> float:
    value = float(value)
    if value > 1.0 or value < 0.0:
        value %= 360.0
        if value < 0.0:
            value += 360.0
        return value / 360.0
    return _clamp_unit(value)


def _normalize_hsv_triplet(values: Sequence[Any]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("HSV value must contain exactly three components")
    h, s, v = (float(values[0]), float(values[1]), float(values[2]))
    return (
        _normalize_hue(h),
        _normalize_unit(s),
        _normalize_unit(v),
    )


def _normalize_rgb_triplet(values: Sequence[Any]) -> tuple[int, int, int]:
    if len(values) != 3:
        raise ValueError("RGB value must contain exactly three components")
    r, g, b = (float(values[0]), float(values[1]), float(values[2]))
    if max(abs(r), abs(g), abs(b)) <= 1.0:
        r *= 255.0
        g *= 255.0
        b *= 255.0
    return (
        max(0, min(255, int(round(r)))),
        max(0, min(255, int(round(g)))),
        max(0, min(255, int(round(b)))),
    )


def _parse_triplet_text(text: str) -> list[float]:
    parts = [p for p in re.split(r"[;,\s]+", text.strip()) if p]
    if len(parts) < 3:
        raise ValueError("Failed to parse color components from text")
    return [float(parts[0]), float(parts[1]), float(parts[2])]


def _parse_hex_color(text: str) -> tuple[int, int, int]:
    cleaned = text.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:]
    elif cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) not in (6, 8):
        raise ValueError("Hex color must be in RRGGBB or AARRGGBB format")
    cleaned = cleaned[-6:]
    r = int(cleaned[0:2], 16)
    g = int(cleaned[2:4], 16)
    b = int(cleaned[4:6], 16)
    return r, g, b


def _prepare_color_payload(
    *,
    color: Any = None,
    hsv: Sequence[Any] | None = None,
    rgb: Sequence[Any] | None = None,
    space: str | None = None,
) -> Dict[str, Any]:
    """Формирует полезную нагрузку с цветом для команды покраски."""

    if hsv is not None:
        h, s, v = _normalize_hsv_triplet(hsv)
        return {"hsv": {"h": h, "s": s, "v": v}}

    if rgb is not None:
        r, g, b = _normalize_rgb_triplet(rgb)
        return {"rgb": {"r": r, "g": g, "b": b}}

    if color is None:
        raise ValueError("Either hsv, rgb or color must be provided")

    if isinstance(color, str):
        color = color.strip()
        if not color:
            raise ValueError("color string must not be empty")
        if color.startswith("#") or color.lower().startswith("0x"):
            r, g, b = _parse_hex_color(color)
            return {"rgb": {"r": r, "g": g, "b": b}}
        values = _parse_triplet_text(color)
    elif isinstance(color, (list, tuple)):
        values = list(color)
    else:
        raise TypeError("color must be a string or a sequence of three numbers")

    if len(values) != 3:
        raise ValueError("color must contain exactly three components")

    normalized_space = (space or "").strip().lower()
    if normalized_space == "hsv":
        h, s, v = _normalize_hsv_triplet(values)
        return {"hsv": {"h": h, "s": s, "v": v}}

    if normalized_space == "rgb":
        r, g, b = _normalize_rgb_triplet(values)
        return {"rgb": {"r": r, "g": g, "b": b}}

    # Автоопределение: значения <= examples_direct_connect.0 трактуем как HSV, иначе как RGB.
    if max(abs(float(values[0])), abs(float(values[1])), abs(float(values[2]))) <= 1.0:
        h, s, v = _normalize_hsv_triplet(values)
        return {"hsv": {"h": h, "s": s, "v": v}}

    r, g, b = _normalize_rgb_triplet(values)
    return {"rgb": {"r": r, "g": g, "b": b}}
# Import from our own modules

@dataclass
class DeviceMetadata:
    """Representation of a device extracted from the grid info payload."""

    device_type: str
    device_id: str
    telemetry_key: str
    grid_id: str
    name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


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
    """Описание нанесённого урона."""

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
    """Источник урона (нападавший)."""

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


@dataclass
class DamageEvent:
    """Событие нанесения урона по блоку грида."""

    timestamp: str
    grid_id: Optional[int]
    grid_name: Optional[str]
    grid_is_static: Optional[bool]
    owner_id: Optional[int]
    attacker_id: Optional[int]
    block: Optional[BlockInfo]
    damage: DamageDetails
    attacker: DamageSource
    raw: Dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "DamageEvent":
        if not isinstance(payload, dict):
            raise TypeError("Damage event payload must be a dictionary")

        timestamp_raw = payload.get("timestamp") or payload.get("time")
        timestamp = str(timestamp_raw) if timestamp_raw is not None else ""

        grid_id = _safe_int(payload.get("gridId"))
        owner_id = _safe_int(payload.get("ownerId"))
        attacker_id = _safe_int(payload.get("attackerId"))

        grid_name = payload.get("gridName")
        grid_is_static_raw = payload.get("gridIsStatic")
        grid_is_static = (
            None if grid_is_static_raw is None else _coerce_bool(grid_is_static_raw)
        )

        block_payload = payload.get("block")
        block: Optional[BlockInfo] = None
        if isinstance(block_payload, dict):
            try:
                block = BlockInfo.from_payload(block_payload)
            except Exception:
                block = None

        damage_details = DamageDetails.from_payload(payload.get("damage"))
        attacker = DamageSource.from_payload(payload.get("attacker"))

        if attacker_id is None and attacker.entity_id is not None:
            attacker_id = attacker.entity_id

        raw_copy = dict(payload)

        return cls(
            timestamp=timestamp,
            grid_id=grid_id,
            grid_name=str(grid_name) if isinstance(grid_name, str) and grid_name.strip() else None,
            grid_is_static=grid_is_static,
            owner_id=owner_id,
            attacker_id=attacker_id,
            block=block,
            damage=damage_details,
            attacker=attacker,
            raw=raw_copy,
        )


@dataclass
class RemovedDeviceInfo:
    """Сведения об устройстве, удалённом из состава грида."""

    device_id: str
    device_type: Optional[str]
    name: Optional[str]


@dataclass
class GridDevicesEvent:
    """Набор изменений в составе устройств грида."""

    added: List["BaseDevice"]
    removed: List[RemovedDeviceInfo]


@dataclass
class GridIntegrityChange:
    """Изменение целостности отдельного блока."""

    block_id: int
    block: BlockInfo
    name: Optional[str]
    block_type: str
    subtype: Optional[str]
    previous_integrity: Optional[float]
    current_integrity: Optional[float]
    previous_max_integrity: Optional[float]
    current_max_integrity: Optional[float]
    was_damaged: bool
    is_damaged: bool


class Grid:
    """Representation of a Space Engineers grid."""

    def __init__(
        self,
        redis_client,
        owner_id: str,
        grid_id: str,
        player_id: str,
        name: str = None,
    ) -> None:
        self.redis = redis_client
        self.owner_id = owner_id
        self.grid_id = grid_id
        self.player_id = player_id
        self.name = name or f"Grid_{grid_id}"
        self.grid_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
        self.metadata: Optional[Dict[str, Any]] = None
        self.is_subgrid: bool = False
        self.devices: Dict[str, BaseDevice] = {}
        # NEW: индекс по числовому id
        self.devices_by_num: Dict[int, BaseDevice] = {}
        self.blocks: Dict[int, BlockInfo] = {}
        self._damage_channel = f"se:{owner_id}:grid:{grid_id}:damage"
        self._damage_subscriptions: list[Any] = []

        # Event listeners: event name -> list of callbacks
        # Callback signature: (grid: Grid, payload: Any, source_event: str) -> None
        self._listeners: dict[str, list[Callable[["Grid", Any, str], None]]] = {}


        self._subscription = self.redis.subscribe_to_key(
            self.grid_key, self._on_grid_change
        )
        initial = self.redis.get_json(self.grid_key)
        if initial is not None:
            self._on_grid_change(self.grid_key, initial, "initial")

        # Discover devices from telemetry keys if not already known
        self._discover_devices_from_telemetry_keys()

        # Aggregate devices from subgrids
        self._aggregate_devices_from_subgrids()

    # ------------------------------------------------------------------
    def on(
        self,
        event: str,
        callback: Callable[["Grid", Any, str], None],
    ) -> None:
        """Регистрирует обработчик событий грида."""

        if not isinstance(event, str) or not event:
            raise ValueError("event must be a non-empty string")
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._listeners.setdefault(event, []).append(callback)

    # ------------------------------------------------------------------
    def off(
        self,
        event: str,
        callback: Callable[["Grid", Any, str], None],
    ) -> None:
        """Удаляет обработчик событий грида."""

        listeners = self._listeners.get(event)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            return
        if not listeners:
            self._listeners.pop(event, None)

    def __str__(self) -> str:
        return f"{self.name}: {len(self.devices)} device(s)"


    # ------------------------------------------------------------------
    def _emit(self, event: str, payload: Any, source_event: str) -> None:
        listeners = list(self._listeners.get(event, []))
        if not listeners:
            return
        for callback in listeners:
            try:
                callback(self, payload, source_event)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _on_grid_change(self, key: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            return
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return
        # При наличии имени грида в payload — обновим локальное имя
        try:
            new_name = (
                payload.get("name")
                or payload.get("gridName")
                or payload.get("displayName")
                or payload.get("DisplayName")
            )
            if isinstance(new_name, str) and new_name.strip():
                self.name = new_name
        except Exception:
            pass

        previous_blocks = dict(self.blocks)

        self.metadata = payload
        from .common import _is_subgrid
        self.is_subgrid = _is_subgrid(self.metadata)
        device_metadata = list(self._extract_devices(payload))
        # Add devices from subgrids
        for sub_id in payload.get("subGridIds", []):
            if sub_id:
                sub_id_str = str(sub_id)
                sub_key = f"se:{self.owner_id}:grid:{sub_id_str}:gridinfo"
                subpayload = self.redis.get_json(sub_key)
                if subpayload:
                    device_metadata.extend(self._extract_devices_for_payload(subpayload, sub_id_str))
        metadata_ids = {meta.device_id for meta in device_metadata}

        added_devices: List[BaseDevice] = []
        removed_devices: List[RemovedDeviceInfo] = []

        # добавление/обновление устройств
        for metadata in device_metadata:
            device = self.devices.get(metadata.device_id)
            if device is None:
                device = create_device(self, metadata)
                self.devices[metadata.device_id] = device
                added_devices.append(device)
            else:
                # check if device class needs to be updated (e.g., upgrade from GenericDevice)
                if (device.__class__.__name__ == 'GenericDevice' and
                    metadata.device_type != 'generic' and
                    DEVICE_TYPE_MAP.get(metadata.device_type.lower())):
                    # replace with correct device class
                    self.devices[metadata.device_id] = None  # temp
                    old_device = device
                    device = create_device(self, metadata)
                    self.devices[metadata.device_id] = device
                    removed_devices.append(
                        RemovedDeviceInfo(
                            device_id=metadata.device_id,
                            device_type='generic',
                            name=getattr(old_device, "name", None),
                        )
                    )
                    added_devices.append(device)
                    old_device.close()
                else:
                    device.update_metadata(metadata)

            try:
                did_int = int(metadata.device_id)
            except Exception:
                pass
            else:
                self.devices_by_num[did_int] = device

        # удаление исчезнувших устройств
        for device_id in list(self.devices):
            if device_id in metadata_ids:
                continue
            device = self.devices.pop(device_id)
            removed_devices.append(
                RemovedDeviceInfo(
                    device_id=device_id,
                    device_type=getattr(device, "device_type", None),
                    name=getattr(device, "name", None),
                )
            )
            try:
                self.devices_by_num.pop(int(device_id), None)
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass

        # Upgrade GenericDevice to specific class if available
        for device in list(self.devices.values()):
            if (device.__class__.__name__ == 'GenericDevice' and
                getattr(device, 'device_type', '').lower() != 'generic'):
                cls_to_use = DEVICE_TYPE_MAP.get(getattr(device, 'device_type', '').lower())
                if cls_to_use and cls_to_use != GenericDevice:
                    new_device = create_device(self, device.metadata)
                    self.devices[device.metadata.device_id] = new_device
                    try:
                        num_id = int(device.metadata.device_id)
                        self.devices_by_num[num_id] = new_device
                    except ValueError:
                        pass
                    removed_devices.append(
                        RemovedDeviceInfo(
                            device_id=device.metadata.device_id,
                            device_type='generic',
                            name=getattr(device, 'name', None),
                        )
                    )
                    added_devices.append(new_device)
                    device.close()

        if added_devices or removed_devices:
            self._emit(
                "devices",
                GridDevicesEvent(added=added_devices, removed=removed_devices),
                event,
            )

        block_entries = list(self._extract_blocks(payload))
        # Add blocks from subgrids
        for sub_id in payload.get("subGridIds", []):
            if sub_id:
                sub_id_str = str(sub_id)
                sub_key = f"se:{self.owner_id}:grid:{sub_id_str}:gridinfo"
                subpayload = self.redis.get_json(sub_key)
                if subpayload:
                    block_entries.extend(self._extract_blocks(subpayload))
        new_blocks = {block.block_id: block for block in block_entries}
        if block_entries or self.blocks:
            integrity_changes = self._detect_integrity_changes(previous_blocks, new_blocks)
            self.blocks = new_blocks
            if integrity_changes:
                self._emit("integrity", {"changes": integrity_changes}, event)

    # ------------------------------------------------------------------
    def _detect_integrity_changes(
        self,
        previous_blocks: Dict[int, BlockInfo],
        current_blocks: Dict[int, BlockInfo],
    ) -> List[GridIntegrityChange]:
        changes: List[GridIntegrityChange] = []
        for block_id, current in current_blocks.items():
            previous = previous_blocks.get(block_id)
            if previous is None:
                continue

            prev_state = previous.state if isinstance(previous.state, dict) else {}
            curr_state = current.state if isinstance(current.state, dict) else {}

            prev_integrity = _safe_float(prev_state.get("integrity"))
            curr_integrity = _safe_float(curr_state.get("integrity"))
            prev_max = _safe_float(prev_state.get("maxIntegrity"))
            curr_max = _safe_float(curr_state.get("maxIntegrity"))

            was_damaged = previous.is_damaged
            is_damaged = current.is_damaged

            if (
                _approx_equal(prev_integrity, curr_integrity)
                and _approx_equal(prev_max, curr_max)
                and was_damaged == is_damaged
            ):
                continue

            changes.append(
                GridIntegrityChange(
                    block_id=block_id,
                    block=current,
                    name=current.name,
                    block_type=current.block_type,
                    subtype=current.subtype,
                    previous_integrity=prev_integrity,
                    current_integrity=curr_integrity,
                    previous_max_integrity=prev_max,
                    current_max_integrity=curr_max,
                    was_damaged=was_damaged,
                    is_damaged=is_damaged,
                )
            )

        return changes

    # ------------------------------------------------------------------
    def get_device(self, device_id: str) -> Optional["BaseDevice"]:
        return self.devices.get(str(device_id))

    # NEW: поиск по числовому идентификатору
    def get_device_num(self, device_id: int) -> Optional["BaseDevice"]:
        """Вернёт устройство по числовому device/entity ID или None, если не найдено."""

        return self.devices_by_num.get(int(device_id))

    # NEW: универсальный помощник — принимает и str, и int
    def get_device_any(self, device_id: int | str) -> Optional["BaseDevice"]:
        """
        Если пришёл int — ищем через devices_by_num.
        Если str — сначала точное совпадение, затем пробуем int(device_id).
        """

        if isinstance(device_id, int):
            return self.devices_by_num.get(device_id)
        dev = self.devices.get(device_id)
        if dev:
            return dev
        try:
            return self.devices_by_num.get(int(device_id))
        except Exception:
            return None

    # NEW: поиск устройств по типу
    def find_devices_by_type(self, device_type: str | Type[BaseDevice]) -> list["BaseDevice"]:
        """
        Возвращает список устройств указанного типа.

        Принимает как нормализованные типы (например, "battery", "projector"),
        как исходные имена из Space Engineers (например, "MyObjectBuilder_BatteryBlock"),
        так и классы устройств (например, DisplayDevice).
        Тип приводится к нормализованному виду через ``normalize_device_type``.
        """

        if isinstance(device_type, type):
            # if passed a class like DisplayDevice
            normalized = getattr(device_type, "device_type", "generic").lower()
        else:
            try:
                normalized = normalize_device_type(device_type)
            except Exception:
                normalized = str(device_type).lower()

        return [d for d in self.devices.values() if getattr(d, "device_type", "").lower() == normalized]

    def find_devices_by_name(self, name_pattern: str) -> list["BaseDevice"]:
        """
        Возвращает список устройств, чьи имена совпадают с паттерном (регистр не чувствителен).
        Поддерживает подстроки (contains) и регулярные выражения, если паттерн начинается/заканчивается '/' или содержит '.*'.
        """

        if not name_pattern:
            return []
        pattern_lower = name_pattern.lower()

        devices: list["BaseDevice"] = []
        for device in self.devices.values():
            device_name = (device.name or "").lower()
            # Проверяем на regex, если паттерн выглядит как regex
            if name_pattern.startswith("^") or name_pattern.endswith("$") or ".*" in name_pattern or "[^" in name_pattern:
                try:
                    if re.search(name_pattern, device_name, re.IGNORECASE):
                        devices.append(device)
                except re.error:
                    # Если regex неправильный, fallback на contains
                    if pattern_lower in device_name:
                        devices.append(device)
            else:
                # Иначе contains
                if pattern_lower in device_name:
                    devices.append(device)
        return devices

    def aggregate_device_load(self) -> Dict[str, float | int]:
        """Агрегирует показатели нагрузки всех устройств на гриде."""

        totals: Dict[str, float | int] = {
            "devices": 0,
            "spentMs": 0.0,
            "totalAvgMs": 0.0,
            "totalPeakMs": 0.0,
            "updateAvgMs": 0.0,
            "updatePeakMs": 0.0,
            "commandsAvgMs": 0.0,
            "commandsPeakMs": 0.0,
        }

        def _add(key: str, value: Any) -> None:
            if value is None:
                return
            try:
                totals[key] = float(totals[key]) + float(value)
            except (TypeError, ValueError):
                pass

        for device in self.devices.values():
            metrics = device.load_metrics()
            if not metrics:
                continue

            totals["devices"] = int(totals["devices"]) + 1

            _add("spentMs", metrics.get("spentMs"))

            total_bucket = metrics.get("total")
            if isinstance(total_bucket, dict):
                _add("totalAvgMs", total_bucket.get("avgMs"))
                _add("totalPeakMs", total_bucket.get("peakMs"))

            update_bucket = metrics.get("update")
            if isinstance(update_bucket, dict):
                _add("updateAvgMs", update_bucket.get("avgMs"))
                _add("updatePeakMs", update_bucket.get("peakMs"))

            commands_bucket = metrics.get("commands")
            if isinstance(commands_bucket, dict):
                _add("commandsAvgMs", commands_bucket.get("avgMs"))
                _add("commandsPeakMs", commands_bucket.get("peakMs"))

        if totals["devices"]:
            totals["avgSpentMsPerDevice"] = float(totals["spentMs"]) / int(totals["devices"])
        else:
            totals["avgSpentMsPerDevice"] = 0.0

        return totals

    def find_enabled_devices(self, device_type: Optional[str] = None) -> list["BaseDevice"]:
        """
        Возвращает список включенных устройств, опционально фильтруя по типу.
        Если device_type=None, возвращает все включенные устройства.
        """

        enabled: list["BaseDevice"] = []
        if device_type is not None:
            type_devices = self.find_devices_by_type(device_type)
        else:
            type_devices = self.devices.values()

        for device in type_devices:
            if device.is_enabled():
                enabled.append(device)
        return enabled

    def find_damaged_blocks(self) -> list[BlockInfo]:
        """
        Возвращает список поврежденных блоков, где integrity < maxIntegrity или damaged=True.
        """
        return [block for block in self.blocks.values() if block.is_damaged]

    def find_devices_containers(self) -> list["BaseDevice"]:
        """
        Возвращает список устройств, которые могут содержать предметы (имеют инвентари).
        """
        return [d for d in self.devices.values() if d.is_container]

    def get_all_grid_items(self) -> list[dict]:
        """
        Возвращает список всех предметов на гриде с информацией о расположении.

        Каждый элемент содержит:
        - device_id: ID устройства
        - device_name: имя устройства
        - device_type: тип устройства
        - inventory_name: имя внутреннего инвентаря
        - item_type: тип предмета
        - item_subtype: подтип предмета
        - amount: количество
        - display_name: отображаемое имя предмета
        """
        items = []
        for device in self.find_devices_containers():
            for inventory in device.inventories():
                for item in inventory.items:
                    items.append({
                        "device_id": device.device_id,
                        "device_name": device.name,
                        "device_type": device.device_type,
                        "inventory_name": inventory.name,
                        "item_type": item.type,
                        "item_subtype": item.subtype,
                        "amount": item.amount,
                        "display_name": item.display_name,
                    })
        return items

    def find_items_by_type(self, item_type: str) -> list[dict]:
        """
        Возвращает все предметы указанного типа на гриде.

        Args:
            item_type: Тип предмета (например, "MyObjectBuilder_Ore")

        Returns:
            Список словарей с информацией о предметах
        """
        return [item for item in self.get_all_grid_items() if item["item_type"] == item_type]

    def find_items_by_subtype(self, subtype: str) -> list[dict]:
        """
        Возвращает все предметы указанного подтипа на гриде.

        Args:
            subtype: Подтип предмета (например, "SteelPlate")

        Returns:
            Список словарей с информацией о предметах
        """
        return [item for item in self.get_all_grid_items() if item["item_subtype"] == subtype]

    def find_items_by_display_name(self, display_name: str) -> list[dict]:
        """
        Возвращает все предметы с указанным отображаемым именем на гриде.

        Args:
            display_name: Отображаемое имя предмета

        Returns:
            Список словарей с информацией о предметах
        """
        return [item for item in self.get_all_grid_items() if item["display_name"] == display_name]

    def get_total_amount(self, subtype: str) -> float:
        """
        Возвращает общее количество предмета указанного подтипа на гриде.

        Args:
            subtype: Подтип предмета

        Returns:
            Общее количество
        """
        items = self.find_items_by_subtype(subtype)
        return sum(item["amount"] for item in items)

    def find_containers_with_tag(self, tag: str) -> list["BaseDevice"]:
        """
        Возвращает все контейнеры с указанным тегом.

        Args:
            tag: Тег для поиска

        Returns:
            Список контейнеров
        """
        containers = []
        for device in self.find_devices_containers():
            if hasattr(device, 'has_tag') and device.has_tag(tag):
                containers.append(device)
        return containers

    def find_tagged_containers(self) -> list[tuple["BaseDevice", set[str]]]:
        """
        Возвращает все контейнеры с их тегами.

        Returns:
            Список кортежей (контейнер, теги)
        """
        result = []
        for device in self.find_devices_containers():
            if hasattr(device, 'tags'):
                tags = device.tags
                if tags:
                    result.append((device, tags))
        return result

    # ------------------------------------------------------------------
    def get_block(self, block_id: int | str) -> Optional[BlockInfo]:
        """Возвращает блок по его ``EntityId``."""

        try:
            resolved = int(block_id)
        except (TypeError, ValueError):
            return None
        return self.blocks.get(resolved)

    def iter_blocks(self) -> Iterable[BlockInfo]:
        """Итерируется по всем известным блокам грида."""

        return self.blocks.values()

    def find_blocks_by_type(self, block_type: str) -> list[BlockInfo]:
        """Возвращает блоки указанного типа или подтипа."""

        normalized = str(block_type or "").strip().lower()
        if not normalized:
            return []
        return [block for block in self.blocks.values() if block.normalized_type == normalized]

    def _normalize_block_id(self, block: int | str | BlockInfo) -> int:
        if isinstance(block, BlockInfo):
            block_id = block.block_id
        else:
            block_id = _safe_int(block)

        if block_id is None or block_id <= 0:
            raise ValueError("block identifier must be a positive integer")

        return block_id

    # ------------------------------------------------------------------
    def _grid_command_channel(self) -> str:
        return f"se.{self.player_id}.commands.grid.{self.grid_id}"

    # ------------------------------------------------------------------
    def send_grid_command(
        self,
        command: str,
        *,
        state: Any | None = None,
        payload: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> int:
        """Публикует команду на уровень грида."""

        if not command:
            raise ValueError("command must be a non-empty string")

        message: Dict[str, Any] = {}
        if payload:
            for key, value in payload.items():
                if value is not None:
                    message[key] = value

        for key, value in extra.items():
            if value is not None and key not in message:
                message[key] = value

        if state is not None:
            message.setdefault("state", state)

        now_ms = int(time.time() * 1000)
        message.setdefault("cmd", command)
        message.setdefault("seq", now_ms)
        message.setdefault("ts", now_ms)
        message.setdefault("targetType", "grid")

        grid_int = _safe_int(self.grid_id)
        if grid_int is not None:
            message.setdefault("gridId", grid_int)
            message.setdefault("gridEntityId", grid_int)
            message.setdefault("grid_id", grid_int)
            message.setdefault("targetId", grid_int)
            message.setdefault("target_id", grid_int)

        owner_int = _safe_int(self.owner_id)
        if owner_int is not None:
            message.setdefault("ownerId", owner_int)
            message.setdefault("owner_id", owner_int)

        player_int = _safe_int(self.player_id)
        if player_int is not None:
            message.setdefault("playerId", player_int)
            message.setdefault("player_id", player_int)
            message.setdefault("userId", player_int)

        meta = message.get("meta")
        if isinstance(meta, dict):
            meta.setdefault("user", "grid-wrapper")
        else:
            message["meta"] = {"user": "grid-wrapper"}

        channel = self._grid_command_channel()
        return self.redis.publish(channel, message)

    # ------------------------------------------------------------------
    def rename(self, new_name: str) -> int:
        """Изменяет отображаемое имя грида."""

        if not new_name or not new_name.strip():
            raise ValueError("new_name must be a non-empty string")

        trimmed = new_name.strip()
        return self.send_grid_command(
            "set_name",
            state=trimmed,
            payload={"name": trimmed, "gridName": trimmed},
        )

    # ------------------------------------------------------------------
    def set_owner(
        self,
        owner_id: int | str,
        *,
        share_mode: Optional[str] = None,
        share_with_all: Optional[bool] = None,
        share_with_faction: Optional[bool] = None,
    ) -> int:
        """Передаёт владение гридом выбранному игроку."""

        owner_int = _safe_int(owner_id)
        if owner_int is None or owner_int <= 0:
            raise ValueError("owner_id must be a positive integer")

        payload: Dict[str, Any] = {"ownerId": owner_int}
        if share_mode is not None:
            payload["shareMode"] = str(share_mode).strip()
        if share_with_all is not None:
            payload["shareWithAll"] = bool(share_with_all)
        if share_with_faction is not None:
            payload["shareWithFaction"] = bool(share_with_faction)

        return self.send_grid_command("set_owner", payload=payload)

    # ------------------------------------------------------------------
    def convert_to_ship(self) -> int:
        """Переводит грид в режим корабля."""

        return self.send_grid_command("convert_to_ship")

    # ------------------------------------------------------------------
    def convert_to_station(self) -> int:
        """Переводит грид в режим станции."""

        return self.send_grid_command("convert_to_station")

    # ------------------------------------------------------------------
    def paint_block(
        self,
        block_id: int | str | BlockInfo,
        *,
        color: Any = None,
        hsv: Sequence[Any] | None = None,
        rgb: Sequence[Any] | None = None,
        space: str | None = None,
        play_sound: bool | None = None,
    ) -> int:
        """Меняет цвет одного блока по его ``EntityId``."""

        block_int = self._normalize_block_id(block_id)

        color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)

        payload: Dict[str, Any] = {"blockId": block_int}
        payload.update(color_payload)

        if play_sound is not None:
            payload["playSound"] = bool(play_sound)

        return self.send_grid_command("paint_block", payload=payload)

    # ------------------------------------------------------------------
    def paint_blocks(
        self,
        blocks: Iterable[int | str | BlockInfo],
        *,
        color: Any = None,
        hsv: Sequence[Any] | None = None,
        rgb: Sequence[Any] | None = None,
        space: str | None = None,
        play_sound: bool | None = None,
    ) -> int:
        """Меняет цвет нескольких блоков одним запросом."""

        if isinstance(blocks, (BlockInfo, int, str)):
            candidates = [blocks]
        else:
            candidates = list(blocks)

        block_ids: list[int] = []
        for item in candidates:
            block_ids.append(self._normalize_block_id(item))

        if not block_ids:
            raise ValueError("blocks must contain at least one block identifier")

        # сохраняем порядок и убираем дубликаты
        unique_ids = list(dict.fromkeys(block_ids))

        color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)

        payload: Dict[str, Any] = {
            **color_payload,
            "blocks": [{"blockId": block_id} for block_id in unique_ids],
        }

        if play_sound is not None:
            payload["playSound"] = bool(play_sound)

        return self.send_grid_command("paint_blocks", payload=payload)

    # ------------------------------------------------------------------
    def create_gps_marker(
        self,
        name: str | None = None,
        *,
        gps: str | None = None,
        coordinates: Sequence[Any] | str | None = None,
        position: Sequence[Any] | str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        description: str | None = None,
        color: Any = None,
        rgb: Sequence[Any] | None = None,
        hsv: Sequence[Any] | None = None,
        space: str | None = None,
        show_on_hud: bool | None = None,
        show_on_terminal: bool | None = None,
        show_on_map: bool | None = None,
        temporary: bool | None = None,
        always_visible: bool | None = None,
        entity_id: int | str | None = None,
    ) -> int:
        """Создаёт GPS-метку для владельца грида.

        Если координаты не указаны, серверная часть использует текущую позицию
        грида. Можно передать готовую GPS-строку Space Engineers (`gps`),
        текстовые или числовые координаты (`coordinates`/`position`) либо три
        значения `x`, `y`, `z`.
        """

        payload: Dict[str, Any] = {}

        if name:
            payload["name"] = name.strip()
        if description:
            payload["description"] = description

        if gps:
            gps_text = gps.strip()
            if gps_text:
                payload["gps"] = gps_text

        def _normalize_vector(value: Sequence[Any] | str | None) -> Optional[tuple[float, float, float]]:
            if value is None:
                return None
            if isinstance(value, str):
                parts = [p for p in re.split(r"[;,\s]+", value.strip()) if p]
                if len(parts) < 3:
                    raise ValueError("coordinates string must contain three numbers")
                try:
                    vector = (float(parts[0]), float(parts[1]), float(parts[2]))
                except ValueError as exc:
                    raise ValueError("failed to parse coordinates from string") from exc
                return vector

            if isinstance(value, Sequence):
                if len(value) < 3:
                    raise ValueError("coordinate sequence must contain at least three values")
                try:
                    vector = (float(value[0]), float(value[1]), float(value[2]))
                except (TypeError, ValueError) as exc:
                    raise ValueError("failed to convert coordinates to float") from exc
                return vector

            raise TypeError("coordinates must be a string or a sequence of three numbers")

        vector = None
        for candidate in (coordinates, position):
            vector = _normalize_vector(candidate)
            if vector is not None:
                break

        if vector is None and any(v is not None for v in (x, y, z)):
            missing = [axis for axis, value in (("x", x), ("y", y), ("z", z)) if value is None]
            if missing:
                raise ValueError(f"coordinates require all three components (missing: {', '.join(missing)})")
            vector = (float(x), float(y), float(z))

        if vector is not None:
            payload["position"] = {"x": vector[0], "y": vector[1], "z": vector[2]}

        if show_on_hud is not None:
            payload["showOnHud"] = bool(show_on_hud)
        if show_on_terminal is not None:
            payload["showOnTerminal"] = bool(show_on_terminal)
        if show_on_map is not None:
            payload["showOnMap"] = bool(show_on_map)
        if temporary is not None:
            payload["temporary"] = bool(temporary)
        if always_visible is not None:
            payload["alwaysVisible"] = bool(always_visible)

        if entity_id is not None:
            entity_int = _safe_int(entity_id)
            if entity_int is None or entity_int <= 0:
                raise ValueError("entity_id must be a positive integer")
            payload["entityId"] = entity_int

        if color is not None or rgb is not None or hsv is not None:
            color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)
            if "hsv" in color_payload:
                hsv_values = color_payload["hsv"]
                h = float(hsv_values.get("h", 0.0))
                s = float(hsv_values.get("s", 0.0))
                v = float(hsv_values.get("v", 0.0))
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                color_payload = {
                    "rgb": {
                        "r": max(0, min(255, int(round(r * 255.0)))),
                        "g": max(0, min(255, int(round(g * 255.0)))),
                        "b": max(0, min(255, int(round(b * 255.0)))),
                    }
                }
            payload.update(color_payload)

        return self.send_grid_command("create_gps", payload=payload)

    # ------------------------------------------------------------------
    def list_gps_markers(
        self,
        *,
        show_on_hud: bool | None = None,
        show_on_map: bool | None = None,
        always_visible: bool | None = None,
        request_id: str | None = None,
    ) -> int:
        """Запрашивает у сервера список GPS-меток игрока."""

        payload: Dict[str, Any] = {}

        if show_on_hud is not None:
            payload["showOnHud"] = bool(show_on_hud)
        if show_on_map is not None:
            payload["showOnMap"] = bool(show_on_map)
        if always_visible is not None:
            payload["alwaysVisible"] = bool(always_visible)
        if request_id:
            payload["requestId"] = str(request_id)

        effective_payload = payload if payload else None
        return self.send_grid_command("list_gps", payload=effective_payload)

    # ------------------------------------------------------------------
    def park(
        self,
        enabled: bool,
        brake_wheels: bool,
        shutdown_thrusters: bool,
        lock_connectors: bool,
    ) -> int:
        """Активирует или деактивирует режим парковки грида."""

        payload: Dict[str, Any] = {
            "enabled": bool(enabled),
            "brakeWheels": bool(brake_wheels),
            "shutdownThrusters": bool(shutdown_thrusters),
            "lockConnectors": bool(lock_connectors),
        }
        return self.send_grid_command("park", payload=payload)

    def park_on(self):
        self.park(
            enabled=True,
            brake_wheels=True,
            shutdown_thrusters=True,
            lock_connectors=True
        )

    def park_off(self):
        self.park(
            enabled=False,
            brake_wheels=False,
            shutdown_thrusters=False,
            lock_connectors=False
        )

    # ------------------------------------------------------------------
    def power(self, mode: str) -> int:
        """Изменяет режим питания грида."""

        valid_modes = {"on", "soft_off", "hard_off"}
        if mode not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}, got {mode!r}")

        payload: Dict[str, Any] = {"mode": mode}
        return self.send_grid_command("power", payload=payload)

    def power_on(self):
        self.power("on")

    def power_off(self):
        self.power("soft_off")

    # ------------------------------------------------------------------
    def _extract_devices(self, payload: Dict[str, Any]) -> Iterable[DeviceMetadata]:
        """Extract devices from main grid's payload."""
        yield from self._extract_devices_for_payload(payload, self.grid_id)

    def _extract_devices_for_payload(self, payload: Dict[str, Any], grid_id: str) -> Iterable[DeviceMetadata]:
        # собираем кандидатов из новых мест: payload['blocks']
        candidates: list[Dict[str, Any]] = []

        # 1) devices из blocks (новый формат)
        blocks_entries = payload.get("blocks")
        if isinstance(blocks_entries, list):
            candidates.extend([b for b in blocks_entries if isinstance(b, dict)])

        if not candidates:
            return

        for entry in candidates:
            # Проверяем, является ли блок устройством
            if not entry.get("isDevice", False):
                continue

            # из вашего JSON: поля называются id/type/subtype/name
            raw_type = (
                entry.get("type")
                or entry.get("deviceType")
                or entry.get("subtype")
                or "generic"
            )
            device_type = normalize_device_type(raw_type)

            # id может быть int — приводим к строке
            raw_id = (
                entry.get("deviceId")
                or entry.get("entityId")
                or entry.get("id")
                or ""
            )
            if raw_id in ("", None):
                continue
            device_id = str(raw_id)

            # telemetryKey в вашем примере нет — синтезируем по нашей схеме
            telemetry_key = entry.get("telemetryKey") or entry.get("key")
            if not telemetry_key:
                telemetry_key = self.build_device_key(device_type, device_id)

            custom_name = entry.get("customName") or entry.get("CustomName")
            display_name = (
                entry.get("displayName")
                or entry.get("displayNameText")
                or entry.get("DisplayName")
                or entry.get("DisplayNameText")
            )
            raw_name = entry.get("name") or entry.get("Name")
            name = custom_name or display_name or raw_name
            extra = dict(entry)
            # Приоритезация имен
            if custom_name is not None:
                extra["customName"] = custom_name
            if raw_name is not None:
                extra["name"] = raw_name
            if display_name is not None:
                extra["displayName"] = display_name

            yield DeviceMetadata(
                device_type=device_type,
                device_id=device_id,
                telemetry_key=str(telemetry_key),
                grid_id=grid_id,
                name=name,
                extra=extra,
            )

    def _extract_blocks(self, payload: Dict[str, Any]) -> Iterable[BlockInfo]:
        candidates: list[Dict[str, Any]] = []

        root_blocks = payload.get("blocks")
        if isinstance(root_blocks, dict):
            candidates.extend([b for b in root_blocks.values() if isinstance(b, dict)])
        elif isinstance(root_blocks, list):
            candidates.extend([b for b in root_blocks if isinstance(b, dict)])

        comp = payload.get("comp")
        if isinstance(comp, dict):
            comp_blocks = comp.get("blocks")
            if isinstance(comp_blocks, dict):
                candidates.extend([b for b in comp_blocks.values() if isinstance(b, dict)])
            elif isinstance(comp_blocks, list):
                candidates.extend([b for b in comp_blocks if isinstance(b, dict)])

        seen: Dict[int, BlockInfo] = {}
        for entry in candidates:
            try:
                block = BlockInfo.from_payload(entry)
            except Exception:
                continue
            seen[block.block_id] = block

        return seen.values()

    # ------------------------------------------------------------------
    def _discover_devices_from_telemetry_keys(self) -> None:
        """
        Scans for existing telemetry keys and adds devices that are not already known.
        This helps discover devices that exist in telemetry but not listed in gridinfo (e.g., for rovers).
        """
        pattern = f"se:{self.owner_id}:grid:{self.grid_id}:*:*:telemetry"
        existing_device_ids = set(self.devices.keys())

        try:
            keys_found = []
            for key in self.redis.client.scan_iter(match=pattern, count=100):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")

                # Parse key: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
                parts = key.split(":")
                if len(parts) != 7 or parts[6] != "telemetry":
                    continue

                device_type_raw = parts[4]
                device_id = parts[5]

                if device_id in existing_device_ids:
                    continue
                keys_found.append(key)

                device_type_normalized = normalize_device_type(device_type_raw)
                telemetry_key = key

                # Fetch snapshot to get name and potentially correct device type for AI blocks
                snapshot = self.redis.get_json(telemetry_key)
                name = None
                if isinstance(snapshot, dict):
                    for name_key in ("name", "customName", "displayName", "CustomName"):
                        if snapshot.get(name_key):
                            name = str(snapshot[name_key])
                            break

                    # Special handling for AI blocks
                    ai_role = snapshot.get("aiRole")
                    ai_subtype = snapshot.get("aiSubtype")
                    if ai_role:
                        if ai_role == "Mission" and ai_subtype == "FlightAutopilot":
                            device_type_normalized = "ai_flight_autopilot"
                        elif ai_role == "Behavior":
                            device_type_normalized = "ai_behavior"
                        elif ai_role == "Task":
                            if ai_subtype == "Defensive":
                                device_type_normalized = "ai_defensive"
                            elif ai_subtype == "Offensive":
                                device_type_normalized = "ai_offensive"
                        elif ai_role == "Recorder":
                            device_type_normalized = "ai_recorder"

                metadata = DeviceMetadata(
                    device_type=device_type_normalized,
                    device_id=device_id,
                    telemetry_key=telemetry_key,
                    grid_id=self.grid_id,
                    name=name or f"{device_type_normalized}:{device_id}",
                    extra={},
                )

                device = create_device(self, metadata)
                self.devices[device_id] = device
                try:
                    num_id = int(device_id)
                    self.devices_by_num[num_id] = device
                except ValueError:
                    pass

            print(f"Keys found: {keys_found}")

        except Exception:
            # Ignore errors during discovery to avoid breaking initialization
            pass

    def _aggregate_devices_from_subgrids(self) -> None:
        """
        Scans telemetry keys for subgrids and creates devices for them.
        """
        if not self.metadata:
            return
        subGridIds = self.metadata.get("subGridIds") or []
        if not isinstance(subGridIds, list):
            return
        for sub_id in subGridIds:
            sub_id_str = str(sub_id)
            # Discover for this subgrid
            self._discover_devices_from_telemetry_keys_for_grid(sub_id_str)

    def _discover_devices_from_telemetry_keys_for_grid(self, sub_grid_id: str) -> None:
        """
        Scans for existing telemetry keys for a specific subgrid and adds devices that are not already known.
        """
        # se:{owner}:grid:{sub_grid_id}:*:*:telemetry but wait, no:
        # For subgrids, if they have their own keys, the pattern is grid:{sub_grid_id}
        pattern = f"se:{self.owner_id}:grid:{sub_grid_id}:*:*:telemetry"
        existing_device_ids = set(self.devices.keys())

        try:
            keys_found = []
            for key in self.redis.client.scan_iter(match=pattern, count=100):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")

                # Parse key: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
                parts = key.split(":")
                if len(parts) != 7 or parts[6] != "telemetry":
                    continue

                device_type_raw = parts[4]
                device_id = parts[5]

                if device_id in existing_device_ids:
                    continue
                keys_found.append(key)

                device_type_normalized = normalize_device_type(device_type_raw)
                telemetry_key = key

                # Fetch snapshot to get name
                snapshot = self.redis.get_json(telemetry_key)
                name = None
                if isinstance(snapshot, dict):
                    for name_key in ("name", "customName", "displayName", "CustomName"):
                        if snapshot.get(name_key):
                            name = str(snapshot[name_key])
                            break

                metadata = DeviceMetadata(
                    device_type=device_type_normalized,
                    device_id=device_id,
                    telemetry_key=telemetry_key,
                    grid_id=sub_grid_id,  # use subgrid id as metadata.grid_id
                    name=name or f"{device_type_normalized}:{device_id}",
                    extra={},
                )

                device = create_device(self, metadata)  # grid=self, so commands will use self.grid_id, but for subgrids it might be wrong, but perhaps okay if using device.grid_id
                self.devices[device_id] = device
                try:
                    num_id = int(device_id)
                    self.devices_by_num[num_id] = device
                except ValueError:
                    pass

            # print(f"Subgrid {sub_grid_id} keys found: {keys_found}")

        except Exception:
            # Ignore errors
            pass

    # ------------------------------------------------------------------
    def build_device_key(self, device_type: str, device_id: str) -> str:
        # Normalize type to the snake_case form used in telemetry keys
        type_key = self._normalize_type_for_telemetry(str(device_type))
        return f"se:{self.owner_id}:grid:{self.grid_id}:{type_key}:{device_id}:telemetry"

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._subscription.close()
        except Exception:
            pass
        for damage_subscription in list(self._damage_subscriptions):
            try:
                damage_subscription.close()
            except Exception:
                pass
        self._damage_subscriptions.clear()
        for device in list(self.devices.values()):
            device.close()
        self.devices.clear()
        self.devices_by_num.clear()
        self.blocks.clear()

    def get_device_by_id(self, device_id: int) -> BaseDevice | None:
        """Быстрый поиск устройства по числовому ID."""

        return self.devices_by_num.get(int(device_id))

    def refresh_devices(self) -> int:
        """
        Перечитывает gridinfo и обновляет self.devices.
        Возвращает число обнаруженных (актуализированных) устройств.
        """

        info_key = f"se:{self.owner_id}:grid:{self.grid_id}:gridinfo"
        payload = self.redis.get_json(info_key) or {}

        # Нормализуем секцию с устройствами:
        devices_section = None
        if isinstance(payload, dict):
            if "devices" in payload:
                devices_section = payload["devices"]
            elif isinstance(payload.get("comp"), dict) and "devices" in payload["comp"]:
                devices_section = payload["comp"]["devices"]

        if not devices_section:
            # Нет устройств в gridinfo — ничего не делаем
            return 0

        # Преобразуем devices_section к списку словарей устройств
        dev_items: list[dict] = []
        if isinstance(devices_section, list):
            dev_items = [d for d in devices_section if isinstance(d, dict)]
        elif isinstance(devices_section, dict):
            # варианты: { "Projector": [ {...}, ... ], "Battery": [ ... ] } ИЛИ { "8788": {...}, ... }
            if devices_section and all(
                isinstance(k, str) and k.isdigit() for k in devices_section.keys()
            ):
                dev_items = [v for v in devices_section.values() if isinstance(v, dict)]
            else:
                for v in devices_section.values():
                    if isinstance(v, list):
                        dev_items.extend([d for d in v if isinstance(d, dict)])
                    elif isinstance(v, dict):
                        dev_items.append(v)

        updated = 0
        for d in dev_items:
            try:
                dev_id = int(d.get("id"))
            except Exception:
                continue

            dev_type = d.get("type") or d.get("blockType") or ""
            dev_subtype = d.get("subtype") or d.get("subType") or ""
            dev_name = d.get("name") or f"{dev_type}:{dev_id}"

            device = self.devices_by_num.get(dev_id)
            if device is None:
                # Подбираем класс
                device_cls_or_name = DEVICE_REGISTRY.get(dev_type, None)
                if device_cls_or_name is None:
                    # Используем DEVICE_TYPE_MAP для разрешения по типу
                    cls = DEVICE_TYPE_MAP.get(normalize_device_type(dev_type), BaseDevice)
                else:
                    # Если в DEVICE_REGISTRY есть запись, проверим, является ли она строкой (именем типа)
                    if isinstance(device_cls_or_name, str):
                        cls = DEVICE_TYPE_MAP.get(device_cls_or_name, BaseDevice)
                    else:
                        # иначе это уже сам класс устройства
                        cls = device_cls_or_name

                # Конструктор BaseDevice/наследников может отличаться — приведи под свой
                # Создаем DeviceMetadata для передачи в конструктор
                telemetry_key = self.build_device_key(
                    normalize_device_type(dev_type), str(dev_id)
                )
                metadata = DeviceMetadata(
                    device_type=normalize_device_type(dev_type),
                    device_id=str(dev_id),
                    telemetry_key=telemetry_key,
                    grid_id=self.grid_id,
                    name=dev_name,
                    extra={
                        "type": dev_type,
                        "subtype": dev_subtype,
                    },
                )
                device = cls(
                    grid=self,
                    metadata=metadata,
                )
                self.devices[str(dev_id)] = device
                self.devices_by_num[dev_id] = device
            else:
                # Обновим имя/типы, если поменялись
                setattr(device, "name", dev_name)
                setattr(device, "type", dev_type)
                setattr(device, "subtype", dev_subtype)

            # Пробуем подтянуть снимок телеметрии
            self._refresh_device_telemetry(device, dev_type, dev_id)
            updated += 1

        return updated

    # ------------------------------------------------------------------
    def subscribe_to_damage(
        self, callback: Callable[[DamageEvent | Dict[str, Any] | str], None]
    ):
        """Подписывается на события урона по текущему гриду.

        Callback получает экземпляр :class:`DamageEvent` при успешном разборе
        сообщения. Если полезную нагрузку не удалось разобрать, в callback
        передаются исходные данные (dict или строка).
        """

        if not callable(callback):
            raise TypeError("callback must be callable")

        def _handle_damage(_channel: str, payload: Any, event_name: str) -> None:
            message = payload if payload is not None else event_name
            if message is None:
                return

            if isinstance(message, dict):
                data = message
            elif isinstance(message, str):
                text = message.strip()
                if not text:
                    return
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    callback(text)
                    return
            else:
                callback(message)
                return

            try:
                damage_event = DamageEvent.from_payload(data)
            except Exception:
                callback(data)
                return

            callback(damage_event)

        subscription = self.redis.subscribe_to_key(self._damage_channel, _handle_damage)
        self._damage_subscriptions.append(subscription)
        return subscription

    def _refresh_device_telemetry(
        self, device: BaseDevice, dev_type: str, dev_id: int
    ) -> None:
        """
        Заполняет последнюю известную телеметрию устройства, если ключ существует.
        Ключ: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
        """

        # dev_type в телеметрии обычно «чистый» (например, battery_block, projector и т.п.).
        # Если у тебя в Redis тип — уже нормализован, замапь тут при необходимости.
        type_key = self._normalize_type_for_telemetry(dev_type)
        tkey = f"se:{self.owner_id}:grid:{self.grid_id}:{type_key}:{dev_id}:telemetry"
        snap = self.redis.get_json(tkey)
        if isinstance(snap, dict):
            # под свою модель: device.telemetry / device.state / device.cache …
            setattr(device, "telemetry", snap)
            # Обновляем ключ с expire=180
            try:
                self.redis.set_json(tkey, snap, expire=180)
            except Exception:
                pass

    def _normalize_type_for_telemetry(self, dev_type: str) -> str:
        """
        Приведение типа к сегменту ключа телеметрии.
        Пример: 'MyObjectBuilder_BatteryBlock' -> 'battery_block'.

        Также учитывает различия между нормализованным типом устройства и
        фактическим сегментом ключа телеметрии. Например, для контейнеров
        нормализованный тип — 'container', а в ключе используется 'cargo_container'.
        """

        # Частные соответствия "тип устройства" -> "тип в ключе"
        special: dict[str, str] = {
            # Cargo containers публикуют телеметрию как 'cargo_container'
            "container": "cargo_container",
            # Connectors публикуют телеметрию как 'ship_connector'
            "connector": "ship_connector",
            # Text panels (LCD) используют сегмент 'text_panel'
            "textpanel": "text_panel",
            # Wheels публикуют телеметрию как 'motor_suspension'
            "wheel": "motor_suspension",
        }

        key = dev_type
        if key in special:
            return special[key]

        if key.startswith("MyObjectBuilder_"):
            key = key.removeprefix("MyObjectBuilder_")
        # Простейшая snake_case нормализация
        return "".join([("_" + c.lower() if c.isupper() else c) for c in key]).lstrip("_")

class BaseDevice:
    """Base class for all telemetry driven devices."""

    device_type: str = "generic"

    def __init__(self, grid: Grid, metadata: DeviceMetadata) -> None:
        # Слушатели событий устройства: {event_name: [callback, ...]}
        # callback(device, telemetry_dict, source_event_str) -> None
        self._listeners: dict[str, list[Callable[["BaseDevice", Dict[str, Any], str], None]]] = {}

        self.grid = grid
        self.redis = grid.redis
        self.device_id = metadata.device_id
        self.device_type = metadata.device_type
        self.telemetry_key = metadata.telemetry_key
        self.grid_id = metadata.grid_id
        self.name = (
            metadata.name
            or metadata.extra.get("customName")
            or metadata.extra.get("name")
            or metadata.extra.get("displayName")
            or metadata.extra.get("displayNameText")
        )
        self.metadata = metadata
        self.telemetry: Optional[Dict[str, Any]] = None
        self._telemetry_event = threading.Event()

        self._enabled: bool = self._extract_optional_bool(
            metadata.extra,
            "enabled",
            "isEnabled",
            "isWorking",
            "isFunctional",
        ) or False
        self._show_in_terminal: bool = self._extract_optional_bool(metadata.extra, "showInTerminal") or False
        self._show_in_toolbar: bool = self._extract_optional_bool(metadata.extra, "showInToolbar") or False
        self._show_on_screen: bool = self._extract_optional_bool(metadata.extra, "showOnScreen") or False

        raw_custom = metadata.extra.get("customData")
        self._custom_data: str = "" if raw_custom is None else str(raw_custom)

        self._load_metrics: Optional[Dict[str, Any]] = None
        self._load_spent_ms: Optional[float] = None

        self._inventories: Dict[str, InventorySnapshot] = {}
        self._inventory_index_map: Dict[str, int] = {}

        # Подписка на телеметрию устройства (устойчивая: keyspace + channel + polling)
        self._subscription = self.redis.subscribe_to_key_resilient(
            self.telemetry_key,
            self._on_telemetry_change,
        )
        snapshot = self.redis.get_json(self.telemetry_key)

        # fallback: попытка найти реальный ключ телеметрии по шаблону
        if snapshot is None:
            resolved = self._resolve_existing_telemetry_key()
            if resolved and resolved != self.telemetry_key:
                try:
                    self._subscription.close()
                except Exception:
                    pass
                self.telemetry_key = resolved
                self._subscription = self.redis.subscribe_to_key_resilient(
                    self.telemetry_key,
                    self._on_telemetry_change,
                )
                snapshot = self.redis.get_json(self.telemetry_key)

        if self.name:
            self._cache_name_in_metadata()

        if snapshot is not None:
            self._on_telemetry_change(self.telemetry_key, snapshot, "initial")
            self._telemetry_event.set()

    # ------------------------------------------------------------------
    # Публичный событийный API
    # ------------------------------------------------------------------

    def on(
        self,
        event: str,
        callback: Callable[["BaseDevice", Dict[str, Any], str], None],
    ) -> None:
        if not isinstance(event, str) or not event:
            raise ValueError("event must be a non-empty string")
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._listeners.setdefault(event, []).append(callback)

    def off(
        self,
        event: str,
        callback: Callable[["BaseDevice", Dict[str, Any], str], None],
    ) -> None:
        listeners = self._listeners.get(event)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            pass
        if not listeners:
            self._listeners.pop(event, None)

    def _emit(self, event: str, telemetry: Dict[str, Any], source_event: str) -> None:
        listeners = list(self._listeners.get(event, []))
        for cb in listeners:
            try:
                cb(self, telemetry, source_event)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _resolve_existing_telemetry_key(self) -> Optional[str]:
        owner = self.grid.owner_id
        grid_id = self.grid.grid_id
        did = self.device_id
        pattern = f"se:{owner}:grid:{grid_id}:*:{did}:telemetry"
        try:
            for key in self.redis.client.scan_iter(match=pattern, count=100):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")
                return key
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    def update_metadata(self, metadata: DeviceMetadata) -> None:
        self.metadata = metadata
        new_name = (
            metadata.name
            or metadata.extra.get("customName")
            or metadata.extra.get("name")
            or metadata.extra.get("displayName")
            or metadata.extra.get("displayNameText")
        )
        if new_name:
            self.name = new_name
            self._cache_name_in_metadata()
        if self.telemetry is not None:
            if self._sync_name_with_telemetry():
                self._persist_common_telemetry()

    # ------------------------------------------------------------------
    def _on_telemetry_change(self, key: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            self._emit("telemetry_cleared", {}, event)
            return

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {"raw": payload}

        if not isinstance(payload, dict):
            return

        telemetry_payload = dict(payload)

        changed = self._merge_common_telemetry(telemetry_payload)
        self.telemetry = telemetry_payload

        self._refresh_inventories(telemetry_payload)

        if changed:
            self._persist_common_telemetry()

        # Хук дочерних классов
        self.handle_telemetry(telemetry_payload)

        # Сообщаем наружу
        self._emit("telemetry", telemetry_payload, event)

        self._telemetry_event.set()

    # ------------------------------------------------------------------
    def handle_telemetry(self, telemetry: Dict[str, Any]) -> None:
        return

    # ------------------------------------------------------------------
    # Inventory helpers
    # ------------------------------------------------------------------
    def inventories(self) -> List[InventorySnapshot]:
        """Return a list of inventory snapshots sorted by index."""

        return [inv.copy() for inv in sorted(self._inventories.values(), key=lambda inv: (inv.index, inv.key))]

    def inventory_map(self) -> Dict[str, InventorySnapshot]:
        """Return a mapping of inventory key -> snapshot."""

        return {key: inv.copy() for key, inv in self._inventories.items()}

    def inventory_count(self) -> int:
        return len(self._inventories)

    def get_inventory(self, reference: str | int | InventorySnapshot | None = None) -> Optional[InventorySnapshot]:
        """Resolve a specific inventory by key, index, name or snapshot."""

        if reference is None:
            snapshots = self.inventories()
            if len(snapshots) == 1:
                return snapshots[0]
            return None

        if isinstance(reference, InventorySnapshot):
            existing = self._inventories.get(reference.key)
            if existing and existing.index == reference.index:
                return existing.copy()
            if reference.device_id == self._numeric_device_id():
                return reference.copy()
            return reference.copy()

        if isinstance(reference, int):
            for snapshot in self._inventories.values():
                if snapshot.index == reference:
                    return snapshot.copy()
            return None

        lookup = str(reference).strip().lower()
        for key, snapshot in self._inventories.items():
            if key.lower() == lookup:
                return snapshot.copy()
            if snapshot.name.lower() == lookup:
                return snapshot.copy()
            if snapshot.name.lower().startswith(lookup) and lookup:
                return snapshot.copy()
        return None

    def inventory_items(self, reference: str | int | InventorySnapshot | None = None) -> List[InventoryItem]:
        if reference is None:
            aggregated: List[InventoryItem] = []
            for snapshot in self._inventories.values():
                aggregated.extend(
                    InventoryItem(item.type, item.subtype, item.amount, item.display_name)
                    for item in snapshot.items
                )
            return aggregated

        inventory = self.get_inventory(reference)
        if inventory is None:
            return []
        return [InventoryItem(item.type, item.subtype, item.amount, item.display_name) for item in inventory.items]

    def _numeric_device_id(self) -> Optional[int]:
        try:
            return int(self.device_id)
        except Exception:
            return None

    def _refresh_inventories(self, telemetry: Dict[str, Any]) -> None:
        if not isinstance(telemetry, dict):
            if self._inventories:
                self._inventories = {}
            return

        entries = self._collect_inventory_payloads(telemetry)
        if not entries:
            if self._inventories:
                self._inventories = {}
            return

        device_id = self._numeric_device_id() or 0
        new_map: Dict[str, InventorySnapshot] = {}
        for key, payload, name, index_hint in entries:
            if not isinstance(payload, dict):
                continue
            index_value = self._assign_inventory_index(key, index_hint)
            items, current_volume, max_volume, current_mass, fill_ratio = parse_inventory_payload(payload)
            name_text = str(name).strip()
            if not name_text:
                name_text = self._format_inventory_name(key)
            snapshot = InventorySnapshot(
                device_id=device_id,
                key=key,
                index=index_value,
                name=name_text,
                current_volume=current_volume,
                max_volume=max_volume,
                current_mass=current_mass,
                fill_ratio=fill_ratio,
                items=items,
                raw=dict(payload),
            )
            new_map[key] = snapshot

        self._inventories = new_map

    def _assign_inventory_index(self, key: str, index_hint: Optional[int]) -> int:
        if index_hint is not None:
            try:
                index = int(index_hint)
            except (TypeError, ValueError):
                index = self._inventory_index_map.get(key, len(self._inventory_index_map))
            else:
                self._inventory_index_map[key] = index
                return index

        if key not in self._inventory_index_map:
            self._inventory_index_map[key] = len(self._inventory_index_map)
        return self._inventory_index_map[key]

    def _collect_inventory_payloads(self, telemetry: Dict[str, Any]) -> List[tuple[str, Dict[str, Any], str, Optional[int]]]:
        entries: List[tuple[str, Dict[str, Any], str, Optional[int]]] = []
        seen: set[str] = set()

        raw_list = telemetry.get("inventories")
        if isinstance(raw_list, list):
            for idx, entry in enumerate(raw_list):
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("inventoryKey") or entry.get("key") or f"inventories[{idx}]")
                seen.add(key)
                name = entry.get("name") or entry.get("displayName") or self._format_inventory_name(key)
                index_hint = entry.get("inventoryIndex")
                if index_hint is None:
                    index_hint = entry.get("index")
                if index_hint is None:
                    index_hint = idx
                entries.append((key, entry, str(name), index_hint))

        for key, value in telemetry.items():
            if not isinstance(value, dict):
                continue
            if key in seen:
                continue
            lowered = key.lower()
            if "inventory" not in lowered:
                continue
            seen.add(key)
            name = value.get("name") or value.get("displayName") or self._format_inventory_name(key)
            index_hint = value.get("inventoryIndex")
            entries.append((key, value, str(name), index_hint))

        if isinstance(telemetry.get("items"), list):
            key = "inventory"
            if key not in seen:
                name = telemetry.get("inventoryName") or self._format_inventory_name(key)
                index_hint = telemetry.get("inventoryIndex")
                entries.append((key, telemetry, str(name), index_hint))

        return entries

    def _format_inventory_name(self, key: str) -> str:
        text = str(key or "").strip()
        if not text:
            return "Inventory"
        cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        cleaned = cleaned.replace("_", " ").replace("[", " ").replace("]", " ").strip()
        if not cleaned:
            cleaned = "Inventory"
        if "inventory" not in cleaned.lower():
            cleaned = f"{cleaned} Inventory"
        return cleaned.title()

    # ------------------------------------------------------------------
    def is_enabled(self) -> bool:
        if isinstance(self.telemetry, dict) and "enabled" in self.telemetry:
            return bool(self.telemetry["enabled"])
        return self._enabled

    @property
    def enabled(self) -> bool:
        return self.is_enabled()

    def enable(self) -> int:
        return self.set_enabled(True)

    def disable(self) -> int:
        return self.set_enabled(False)

    def toggle_enabled(self) -> int:
        result = self.send_command({"cmd": "toggle"})
        if result:
            self._update_common_flag("enabled", not self.is_enabled())
        return result

    def set_enabled(self, enabled: bool) -> int:
        command = "enable" if enabled else "disable"
        result = self.send_command({"cmd": command})
        if result:
            self._update_common_flag("enabled", bool(enabled))
        return result

    # ------------------------------------------------------------------
    def show_in_terminal(self) -> Optional[bool]:
        return self._read_bool_flag("showInTerminal")

    def set_show_in_terminal(self, visible: bool) -> int:
        return self._send_boolean_command("set_show_in_terminal", "showInTerminal", visible)

    def show_in_toolbar(self) -> Optional[bool]:
        return self._read_bool_flag("showInToolbar")

    def set_show_in_toolbar(self, visible: bool) -> int:
        return self._send_boolean_command("set_show_in_toolbar", "showInToolbar", visible)

    def show_on_screen(self) -> Optional[bool]:
        return self._read_bool_flag("showOnScreen")

    def set_show_on_screen(self, visible: bool) -> int:
        return self._send_boolean_command("set_show_on_screen", "showOnScreen", visible)

    def custom_data(self) -> str:
        if isinstance(self.telemetry, dict):
            value = self.telemetry.get("customData")
            if value is None:
                if "customData" not in self.telemetry:
                    self.telemetry["customData"] = self._custom_data
                return self._custom_data
            text_value = str(value)
            if text_value != self._custom_data:
                self._custom_data = text_value
            return self._custom_data
        return self._custom_data

    def load_spent_ms(self) -> Optional[float]:
        return self._load_spent_ms

    def load_metrics(self) -> Optional[Dict[str, Any]]:
        if self._load_metrics is None:
            return None
        return copy.deepcopy(self._load_metrics)

    def set_custom_data(self, data: str) -> int:
        payload = {
            "cmd": "set_custom_data",
            "state": {"customData": str(data)},
        }
        result = self.send_command(payload)
        if result:
            self._update_common_flag("customData", str(data))
        return result

    # ------------------------------------------------------------------
    def _read_bool_flag(self, key: str) -> Optional[bool]:
        if isinstance(self.telemetry, dict) and key in self.telemetry:
            return bool(self.telemetry[key])
        attr = {
            "showInTerminal": self._show_in_terminal,
            "showInToolbar": self._show_in_toolbar,
            "showOnScreen": self._show_on_screen,
        }.get(key)
        return attr if attr is None else bool(attr)

    def _send_boolean_command(self, command: str, telemetry_key: str, value: bool) -> int:
        payload = {
            "cmd": command,
            "state": {telemetry_key: bool(value)},
        }
        result = self.send_command(payload)
        if result:
            self._update_common_flag(telemetry_key, bool(value))
        return result

    def _update_common_flag(self, key: str, value: Any) -> None:
        telemetry = self._ensure_telemetry_dict()
        telemetry[key] = value
        if key == "enabled":
            self._enabled = bool(value)
        elif key == "showInTerminal":
            self._show_in_terminal = bool(value)
        elif key == "showInToolbar":
            self._show_in_toolbar = bool(value)
        elif key == "showOnScreen":
            self._show_on_screen = bool(value)
        elif key == "customData":
            self._custom_data = str(value)
        self._persist_common_telemetry()

    def _ensure_telemetry_dict(self) -> Dict[str, Any]:
        if not isinstance(self.telemetry, dict):
            self.telemetry = {}
        return self.telemetry

    def _merge_common_telemetry(self, telemetry: Dict[str, Any]) -> bool:
        changed = False

        if "enabled" in telemetry:
            self._enabled = bool(telemetry["enabled"])
        else:
            telemetry["enabled"] = bool(self._enabled)
            changed = True

        if "showInTerminal" in telemetry:
            self._show_in_terminal = bool(telemetry["showInTerminal"])
        else:
            telemetry["showInTerminal"] = bool(self._show_in_terminal)
            changed = True

        if "showInToolbar" in telemetry:
            self._show_in_toolbar = bool(telemetry["showInToolbar"])
        else:
            telemetry["showInToolbar"] = bool(self._show_in_toolbar)
            changed = True

        if "showOnScreen" in telemetry:
            self._show_on_screen = bool(telemetry["showOnScreen"])
        else:
            telemetry["showOnScreen"] = bool(self._show_on_screen)
            changed = True

        if "customData" in telemetry:
            raw_custom = telemetry["customData"]
            if raw_custom is None:
                telemetry["customData"] = ""
                self._custom_data = ""
                changed = True
            else:
                text_value = str(raw_custom)
                if text_value != self._custom_data:
                    self._custom_data = text_value
        else:
            telemetry["customData"] = self._custom_data
            changed = True

        if self._update_load_metrics(telemetry):
            changed = True

        if self._sync_name_with_telemetry(telemetry):
            changed = True

        return changed

    def _sync_name_with_telemetry(self, telemetry: Optional[Dict[str, Any]] = None) -> bool:
        target = telemetry if telemetry is not None else self._ensure_telemetry_dict()
        changed = False

        if self.name:
            for key in (
                "name",
                "customName",
                "displayName",
                "displayNameText",
                "CustomName",
                "DisplayName",
            ):
                if target.get(key) != self.name:
                    target[key] = self.name
                    changed = True
            self._cache_name_in_metadata()
        else:
            for key in (
                "customName",
                "name",
                "displayName",
                "displayNameText",
                "CustomName",
                "DisplayName",
            ):
                value = target.get(key)
                if value:
                    text_value = str(value)
                    if text_value != self.name:
                        self.name = text_value
                        self._cache_name_in_metadata()
                    break

        return changed

    def _cache_name_in_metadata(self) -> None:
        if not getattr(self, "metadata", None):
            return
        if self.name:
            try:
                self.metadata.name = self.name
            except Exception:
                pass

        extra = getattr(self.metadata, "extra", None)
        if not isinstance(extra, dict):
            extra = {}
            try:
                self.metadata.extra = extra  # type: ignore[assignment]
            except Exception:
                return

        if not self.name:
            return

        for key in ("customName", "name", "displayName", "displayNameText"):
            extra[key] = self.name

    def _persist_common_telemetry(self) -> None:
        if not isinstance(self.telemetry, dict):
            return
        try:
            self.redis.set_json(self.telemetry_key, self.telemetry, expire=180)
        except Exception:
            pass

    @staticmethod
    def _extract_optional_bool(data: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
        return None

    def _update_load_metrics(self, telemetry: Dict[str, Any]) -> bool:
        raw_load = telemetry.get("load")
        normalized = self._normalize_load_metrics(raw_load)
        changed = False

        if normalized is None:
            if self._load_metrics is not None or self._load_spent_ms is not None:
                self._load_metrics = None
                self._load_spent_ms = None
                changed = True
            if "loadSpentMs" in telemetry:
                telemetry.pop("loadSpentMs", None)
                changed = True
            return changed

        spent = normalized.get("spentMs")
        if spent is not None:
            if telemetry.get("loadSpentMs") != spent:
                telemetry["loadSpentMs"] = spent
                changed = True
        elif "loadSpentMs" in telemetry:
            telemetry.pop("loadSpentMs", None)
            changed = True

        if self._load_metrics != normalized:
            self._load_metrics = normalized
            self._load_spent_ms = normalized.get("spentMs")
            changed = True
        else:
            new_spent = normalized.get("spentMs")
            if self._load_spent_ms != new_spent:
                self._load_spent_ms = new_spent
                changed = True

        return changed

    @staticmethod
    def _normalize_load_metrics(load_payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(load_payload, dict):
            return None

        metrics: Dict[str, Any] = {}

        window = load_payload.get("window")
        if window is not None:
            try:
                metrics["window"] = int(window)
            except (TypeError, ValueError):
                pass

        for bucket_name in ("update", "commands", "total"):
            bucket = BaseDevice._normalize_load_bucket(load_payload.get(bucket_name))
            if bucket:
                metrics[bucket_name] = bucket

        spent = BaseDevice._extract_spent_time(metrics)
        if spent is not None:
            metrics["spentMs"] = spent

        return metrics or None

    @staticmethod
    def _normalize_load_bucket(bucket_payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(bucket_payload, dict):
            return None

        bucket: Dict[str, Any] = {}

        for key in ("lastMs", "avgMs", "peakMs"):
            if key not in bucket_payload:
                continue
            value = bucket_payload.get(key)
            try:
                bucket[key] = float(value)
            except (TypeError, ValueError):
                continue

        samples = bucket_payload.get("samples")
        if samples is not None:
            try:
                bucket["samples"] = int(samples)
            except (TypeError, ValueError):
                pass

        return bucket or None

    @staticmethod
    def _extract_spent_time(metrics: Dict[str, Any]) -> Optional[float]:
        candidates: list[Any] = []

        total_bucket = metrics.get("total")
        if isinstance(total_bucket, dict):
            candidates.extend(total_bucket.get(key) for key in ("avgMs", "lastMs", "peakMs"))

        update_bucket = metrics.get("update")
        if isinstance(update_bucket, dict):
            candidates.append(update_bucket.get("avgMs"))

        for candidate in candidates:
            if candidate is None:
                continue
            try:
                return float(candidate)
            except (TypeError, ValueError):
                continue
        return None

    # ------------------------------------------------------------------
    @property
    def is_container(self) -> bool:
        """True if this device can contain items (has inventories)."""
        return self.inventory_count() > 0

    # ------------------------------------------------------------------
    def command_channel(self) -> str:
        return f"se.{self.grid.player_id}.commands.device.{self.device_id}"

    def _command_channels(self) -> list[str]:
        return [self.command_channel()]

    def send_command(self, command: Dict[str, Any]) -> int:
        def to_int(x):
            try:
                return int(x)
            except Exception:
                return None

        did = to_int(self.device_id)
        gid = to_int(self.grid_id)
        pid = to_int(self.grid.player_id)

        if did is not None:
            command.setdefault("deviceId", did)
            command.setdefault("entityId", did)
        if gid is not None:
            command.setdefault("gridId", gid)
            command.setdefault("gridEntityId", gid)
            command.setdefault("grid_id", gid)
        if pid is not None:
            command.setdefault("playerId", pid)
            command.setdefault("player_id", pid)
            command.setdefault("userId", pid)

        command.setdefault("meta", {}).setdefault("user", "grid-wrapper")
        now_ms = int(time.time() * 1000)
        command.setdefault("seq", now_ms)
        command.setdefault("ts", now_ms)

        sent = 0
        for ch in self._command_channels():
            sent += self.redis.publish(ch, command)
        return sent

    def update(self):
        self.send_command({"cmd": "update"})

    def wait_for_telemetry(self, timeout: float = 10.0) -> bool:
        """Wait for telemetry to become available.

        Returns True if telemetry is available within the timeout, False otherwise.
        """
        if self.telemetry is not None:
            return True
        return self._telemetry_event.wait(timeout)

    # ------------------------------------------------------------------
    def close(self) -> None:
        """Отписываемся от Redis и чистим слушателей."""
        try:
            self._subscription.close()
        except Exception:
            pass
        try:
            self._listeners.clear()
        except Exception:
            pass


# Карта: нормализованный тип -> класс устройства
DEVICE_TYPE_MAP: Dict[str, Type[BaseDevice]] = {}

TYPE_ALIASES = {
    "MyObjectBuilder_Thrust": "thruster",
    "MyObjectBuilder_Gyro": "gyro",
    "MyObjectBuilder_BatteryBlock": "battery",
    "MyObjectBuilder_Reactor": "reactor",
    "MyObjectBuilder_ShipConnector": "connector",
    "MyObjectBuilder_RemoteControl": "remote_control",
    "SmallBlockRemoteControl": "remote_control",
    "Connector": "connector",
    "MyObjectBuilder_CargoContainer": "container",
    "MyObjectBuilder_Cockpit": "cockpit",
    "MyObjectBuilder_OxygenGenerator": "gas_generator",
    "MyObjectBuilder_Refinery": "refinery",
    "MyObjectBuilder_Assembler": "assembler",
    "MyObjectBuilder_ConveyorSorter": "conveyor_sorter",
    "MyObjectBuilder_ShipWelder": "ship_welder",
    "MyObjectBuilder_ShipGrinder": "ship_grinder",
    "MyObjectBuilder_ShipDrill": "ship_drill",
    "MyObjectBuilder_LargeTurretBase": "large_turret",
    "MyObjectBuilder_LargeGatlingTurret": "large_turret",
    "MyObjectBuilder_LargeMissileTurret": "large_turret",
    "MyObjectBuilder_InteriorTurret": "interior_turret",
    "MyObjectBuilder_SmallGatlingGun": "weapon",
    "MyObjectBuilder_LargeGatlingGun": "weapon",
    "MyObjectBuilder_SmallMissileLauncher": "weapon",
    "MyObjectBuilder_LargeMissileLauncher": "weapon",
    "MyObjectBuilder_SmallMissileLauncherReload": "weapon",
    "MyObjectBuilder_OreDetector": "ore_detector",
    "MyObjectBuilder_InteriorLight": "lamp",
    "MyObjectBuilder_ReflectorLight": "lamp",
    "MyObjectBuilder_LightingBlock": "lamp",
    "MyObjectBuilder_TextPanel": "textpanel",
    "MyObjectBuilder_Wheel": "wheel",
    "MyObjectBuilder_MotorSuspension": "wheel",
    "motor_suspension": "wheel",
    "cargo_container": "container",
    "container": "container",
    "MyObjectBuilder_Projector": "projector",
    "projector": "projector",
    "cockpit": "cockpit",
    "oxygen_generator": "gas_generator",
    "gas_generator": "gas_generator",
    "conveyorsorter": "conveyor_sorter",
    "conveyor_sorter": "conveyor_sorter",
    "shipwelder": "ship_welder",
    "ship_welder": "ship_welder",
    "shipgrinder": "ship_grinder",
    "ship_grinder": "ship_grinder",
    "shipdrill": "ship_drill",
    "ship_drill": "ship_drill",
    "largeturret": "large_turret",
    "large_turret": "large_turret",
    "interior_turret": "interior_turret",
    "interiorturret": "interior_turret",
    "aimoveground": "ai_move_ground",
    "ai_move_ground": "ai_move_ground",
    "aiflightautopilot": "ai_flight_autopilot",
    "ai_flight_autopilot": "ai_flight_autopilot",
    "aioffensive": "ai_offensive",
    "ai_offensive": "ai_offensive",
    "aidefensive": "ai_defensive",
    "ai_defensive": "ai_defensive",
    "airecorder": "ai_recorder",
    "ai_recorder": "ai_recorder",
    "aibehavior": "ai_behavior",
    "ai_behavior": "ai_behavior",
    "weapon": "weapon",
    "weapons": "weapon",
    "usercontrollablegun": "weapon",
    "user_controllable_gun": "weapon",
    "lamp": "lamp",
    "light": "lamp",
    "lighting_block": "lamp",
    "interior_light": "lamp",
    "reflector_light": "lamp",
    "textpanel": "textpanel",
    "display": "textpanel",
    "panel": "textpanel",
    "text_panel": "textpanel",
    "wheel": "wheel",
    "MyObjectBuilder_Drill": "nanobot_drill_system",
}


def normalize_device_type(raw_type: Optional[str]) -> str:
    if not raw_type:
        return "generic"
    t = str(raw_type)
    # точное совпадение по объект билдеру
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    # запасной вариант: "MyObjectBuilder_Xxx" -> "xxx"
    if t.startswith("MyObjectBuilder_"):
        return t.split("_", 1)[1].lower()
    return t.lower()


def create_device(grid: Grid, metadata: DeviceMetadata) -> BaseDevice:
    # Проверим, есть ли в DEVICE_REGISTRY прямое сопоставление
    device_cls_or_name = DEVICE_REGISTRY.get(metadata.device_type, None)
    if device_cls_or_name is None:
        # Используем DEVICE_TYPE_MAP для разрешения по типу из метаданных
        device_cls = DEVICE_TYPE_MAP.get(metadata.device_type.lower(), GenericDevice)
    else:
        # Если в DEVICE_REGISTRY есть запись, проверим, является ли она строкой (именем типа)
        if isinstance(device_cls_or_name, str):
            device_cls = DEVICE_TYPE_MAP.get(device_cls_or_name, GenericDevice)
        else:
            # иначе это уже сам класс устройства
            device_cls = device_cls_or_name

    return device_cls(grid, metadata)


class GenericDevice(BaseDevice):
    """Fallback device that simply exposes telemetry."""
