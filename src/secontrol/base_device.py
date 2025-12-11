"""Base device functionality for Space Engineers grid control.

This module contains the base device class and shared helpers that all
specific devices build upon.
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
    "MyObjectBuilder_SmallMissileLauncher": "artillery",
    "MyObjectBuilder_SmallMissileLauncherReload": "weapon",
    "MyObjectBuilder_LargeGatlingGun": "weapon",
    "MyObjectBuilder_LargeMissileLauncher": "weapon",
    "MyObjectBuilder_InteriorTurret": "interior_turret",
    "weapon": "weapon",
    "artillery": "artillery",
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
            self._sync_name_with_telemetry()


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

        # всегда пытаться прочитать новое имя из telemetry
        new_name = None
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
                new_name = str(value).strip()
                if new_name:
                    break

        if new_name and new_name != self.name:
            self.name = new_name
            self._cache_name_in_metadata()
            changed = True

        # записать в telemetry, если отличается
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

    def wait_for_telemetry(self, timeout: float = 10.0, wait_for_new: bool = True, need_update: bool = True) -> bool:
        """Wait for telemetry to become available.

        Args:
            timeout: Maximum time to wait in seconds.
            wait_for_new: If True, wait for the next telemetry update even if telemetry exists.

        Returns True if telemetry is available within the timeout, False otherwise.
        """
        if need_update:
            self.update()

        if not wait_for_new and self.telemetry is not None:
            return True
        if wait_for_new:
            self._telemetry_event.clear()
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
    "drill": "ship_drill",
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
}


def create_device(grid: Grid, metadata: DeviceMetadata) -> BaseDevice:
    # Проверим, есть ли в DEVICE_REGISTRY прямое сопоставление
    device_cls_or_name = DEVICE_REGISTRY.get(metadata.device_type)
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


def normalize_device_type(raw_type: Optional[str], subtype: Optional[str] = None) -> str:
    if not raw_type:
        return "generic"
    t = str(raw_type)
    # специальные случаи
    if t == "MyObjectBuilder_Drill":
        if subtype and "nanobot" in subtype.lower():
            return "nanobot_drill_system"
        else:
            return "ship_drill"
    # точное совпадение по объект билдеру
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    # запасной вариант: "MyObjectBuilder_Xxx" -> "xxx"
    if t.startswith("MyObjectBuilder_"):
        return t.split("_", 1)[1].lower()
    return t.lower()


class GenericDevice(BaseDevice):
    """Fallback device that simply exposes telemetry."""
