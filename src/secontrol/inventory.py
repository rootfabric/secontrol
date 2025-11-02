"""Helpers and data structures for inventory-aware devices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


@dataclass
class InventoryItem:
    """Normalized representation of an item inside an inventory."""

    type: str
    subtype: str
    amount: float
    display_name: Optional[str] = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "InventoryItem":
        """Create an :class:`InventoryItem` from telemetry payload."""

        type_id = _string_or_empty(payload.get("type") or payload.get("Type"))
        subtype = (
            payload.get("subtype")
            or payload.get("subType")
            or payload.get("name")
            or ""
        )
        display_name = payload.get("displayName")
        amount = _coerce_float(payload.get("amount"))
        return cls(type=type_id, subtype=str(subtype), amount=amount, display_name=display_name)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InventoryItem":
        """Backward compatible alias for :meth:`from_payload`."""

        return cls.from_payload(payload)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "type": self.type,
            "subtype": self.subtype,
            "amount": self.amount,
        }
        if self.display_name:
            payload["displayName"] = self.display_name
        return payload

    def to_dict(self) -> dict[str, Any]:
        """Backward compatible alias for :meth:`to_payload`."""

        return self.to_payload()


@dataclass
class InventorySnapshot:
    """Snapshot of a device inventory with normalized items."""

    device_id: int
    key: str
    index: int
    name: str
    current_volume: float
    max_volume: float
    current_mass: float
    fill_ratio: float
    items: list[InventoryItem] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "InventorySnapshot":
        return InventorySnapshot(
            device_id=self.device_id,
            key=self.key,
            index=self.index,
            name=self.name,
            current_volume=self.current_volume,
            max_volume=self.max_volume,
            current_mass=self.current_mass,
            fill_ratio=self.fill_ratio,
            items=[InventoryItem(it.type, it.subtype, it.amount, it.display_name) for it in self.items],
            raw=dict(self.raw),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deviceId": self.device_id,
            "inventoryKey": self.key,
            "inventoryIndex": self.index,
            "name": self.name,
            "currentVolume": self.current_volume,
            "maxVolume": self.max_volume,
            "currentMass": self.current_mass,
            "fillRatio": self.fill_ratio,
            "items": [item.to_payload() for item in self.items],
            "raw": dict(self.raw),
        }

    def describe_items(self) -> list[str]:
        description: list[str] = []
        for item in self.items:
            label = item.display_name or item.subtype or "?"
            description.append(f"{item.amount:.3f} × {label}")
        return description


def normalize_inventory_items(items: Iterable[Any]) -> list[InventoryItem]:
    normalized: list[InventoryItem] = []
    for entry in items:
        if isinstance(entry, InventoryItem):
            normalized.append(InventoryItem(entry.type, entry.subtype, entry.amount, entry.display_name))
        elif isinstance(entry, dict):
            normalized.append(InventoryItem.from_payload(entry))
    return normalized


def parse_inventory_payload(payload: Optional[dict[str, Any]]) -> tuple[list[InventoryItem], float, float, float, float]:
    if not isinstance(payload, dict):
        return ([], 0.0, 0.0, 0.0, 0.0)

    items_payload = payload.get("items")
    items: list[InventoryItem] = []
    if isinstance(items_payload, list):
        items = normalize_inventory_items(items_payload)

    current_volume = _coerce_float(payload.get("currentVolume"))
    max_volume = _coerce_float(payload.get("maxVolume"))
    current_mass = _coerce_float(payload.get("currentMass"))
    fill_ratio = payload.get("fillRatio")
    if fill_ratio is None and max_volume > 0:
        fill_ratio = current_volume / max_volume
    fill_ratio = _coerce_float(fill_ratio)

    return items, current_volume, max_volume, current_mass, fill_ratio


__all__ = ["InventoryItem", "InventorySnapshot", "normalize_inventory_items", "parse_inventory_payload"]

