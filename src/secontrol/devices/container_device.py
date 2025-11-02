"""Inventory-enabled container helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP
from secontrol.inventory import InventoryItem, InventorySnapshot, normalize_inventory_items


class ContainerDevice(BaseDevice):
    """Inventory-aware base for cargo containers and similar devices."""

    device_type = "container"

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------
    def items(self, inventory: str | int | InventorySnapshot | None = None) -> List[InventoryItem]:
        """Return items from the requested inventory."""

        return self.inventory_items(inventory)

    def capacity(self, inventory: str | int | InventorySnapshot | None = None) -> Dict[str, float]:
        """Return capacity metrics for a specific inventory or for all combined."""

        if inventory is None:
            snapshots = self.inventories()
            if not snapshots:
                return {"currentVolume": 0.0, "maxVolume": 0.0, "currentMass": 0.0, "fillRatio": 0.0}
            if len(snapshots) == 1:
                snap = snapshots[0]
                return {
                    "currentVolume": snap.current_volume,
                    "maxVolume": snap.max_volume,
                    "currentMass": snap.current_mass,
                    "fillRatio": snap.fill_ratio,
                }
            current_volume = sum(s.current_volume for s in snapshots)
            max_volume = sum(s.max_volume for s in snapshots)
            current_mass = sum(s.current_mass for s in snapshots)
            fill_ratio = current_volume / max_volume if max_volume > 0 else 0.0
            return {
                "currentVolume": current_volume,
                "maxVolume": max_volume,
                "currentMass": current_mass,
                "fillRatio": fill_ratio,
            }

        snapshot = self.get_inventory(inventory)
        if snapshot is None:
            return {"currentVolume": 0.0, "maxVolume": 0.0, "currentMass": 0.0, "fillRatio": 0.0}
        return {
            "currentVolume": snapshot.current_volume,
            "maxVolume": snapshot.max_volume,
            "currentMass": snapshot.current_mass,
            "fillRatio": snapshot.fill_ratio,
        }

    def inventory(self, reference: str | int | InventorySnapshot | None = None) -> Optional[InventorySnapshot]:
        """Alias for :meth:`BaseDevice.get_inventory`."""

        return self.get_inventory(reference)

    # ------------------------------------------------------------------
    # Transfer helpers
    # ------------------------------------------------------------------
    def _send_transfer(
        self,
        *,
        from_id: int | str,
        to_id: int | str,
        items: Iterable[InventoryItem | dict[str, Any]],
        cmd: str = "transfer_items",
        from_inventory_index: Optional[int] = None,
        to_inventory_index: Optional[int] = None,
    ) -> int:
        norm_items: list[dict[str, Any]] = []
        for it in items:
            if isinstance(it, InventoryItem):
                it_dict = it.to_payload()
            elif isinstance(it, dict):
                it_dict = dict(it)
            else:
                continue
            subtype = it_dict.get("subtype") or it_dict.get("subType") or it_dict.get("name")
            if not subtype:
                continue
            entry = {"subtype": str(subtype)}
            if it_dict.get("type"):
                entry["type"] = str(it_dict["type"])
            if it_dict.get("amount") is not None:
                entry["amount"] = float(it_dict["amount"])
            target_slot_id = (
                it_dict.get("targetSlotId")
                or it_dict.get("slotId")
                or it_dict.get("targetSlot")
            )
            if target_slot_id is not None:
                entry["targetSlotId"] = int(target_slot_id)
            norm_items.append(entry)

        if not norm_items:
            return 0

        payload_obj: Dict[str, Any] = {
            "fromId": int(from_id),
            "toId": int(to_id),
            "items": norm_items,
        }
        if from_inventory_index is not None:
            payload_obj["fromInventoryIndex"] = int(from_inventory_index)
        if to_inventory_index is not None:
            payload_obj["toInventoryIndex"] = int(to_inventory_index)

        state_str = json.dumps(payload_obj, ensure_ascii=False)
        return self.send_command({"cmd": cmd, "state": state_str})

    def _resolve_device_inventory(
        self,
        target: int | str | BaseDevice | InventorySnapshot,
        inventory_reference: str | int | InventorySnapshot | None,
    ) -> tuple[int, Optional[int]]:
        if isinstance(target, InventorySnapshot):
            return int(target.device_id), target.index

        if isinstance(target, BaseDevice):
            device_id = target._numeric_device_id()
            if device_id is None:
                device_id = int(target.device_id)
            index: Optional[int] = None
            if isinstance(inventory_reference, InventorySnapshot):
                index = inventory_reference.index
            elif isinstance(inventory_reference, int):
                index = inventory_reference
            elif inventory_reference is not None:
                snapshot = target.get_inventory(inventory_reference)
                index = snapshot.index if snapshot else None
            return device_id, index

        try:
            device_id = int(target)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Unsupported device identifier: {target!r}") from exc

        if isinstance(inventory_reference, InventorySnapshot):
            return device_id, inventory_reference.index
        if isinstance(inventory_reference, int):
            return device_id, inventory_reference
        if isinstance(inventory_reference, str) and inventory_reference.strip():
            raise ValueError("String inventory reference requires a device instance")
        return device_id, None

    def move_items(
        self,
        destination: int | str | BaseDevice | InventorySnapshot,
        items: Iterable[InventoryItem | dict[str, Any]],
        *,
        source_inventory: str | int | InventorySnapshot | None = None,
        destination_inventory: str | int | InventorySnapshot | None = None,
    ) -> int:
        normalized = list(items)
        from_id = self._numeric_device_id()
        if from_id is None:
            from_id = int(self.device_id)

        source_index: Optional[int] = None
        if isinstance(source_inventory, InventorySnapshot):
            source_index = source_inventory.index
        elif isinstance(source_inventory, int):
            source_index = source_inventory
        elif source_inventory is not None:
            snapshot = self.get_inventory(source_inventory)
            source_index = snapshot.index if snapshot else None
        elif self.inventory_count() == 1:
            snapshot = self.get_inventory()
            source_index = snapshot.index if snapshot else None

        to_id, dest_index = self._resolve_device_inventory(destination, destination_inventory)

        return self._send_transfer(
            from_id=from_id,
            to_id=to_id,
            items=normalized,
            from_inventory_index=source_index,
            to_inventory_index=dest_index,
        )

    def move_subtype(
        self,
        destination: int | str | BaseDevice | InventorySnapshot,
        subtype: str,
        *,
        amount: float | None = None,
        type_id: str | None = None,
        target_slot_id: int | None = None,
        source_inventory: str | int | InventorySnapshot | None = None,
        destination_inventory: str | int | InventorySnapshot | None = None,
    ) -> int:
        entry: Dict[str, Any] = {"subtype": subtype}
        if type_id:
            entry["type"] = type_id
        if amount is not None:
            entry["amount"] = float(amount)
        if target_slot_id is not None:
            entry["targetSlotId"] = int(target_slot_id)
        return self.move_items(
            destination,
            [entry],
            source_inventory=source_inventory,
            destination_inventory=destination_inventory,
        )

    def move_items_to_slot(
        self,
        destination: int | str | BaseDevice | InventorySnapshot,
        items: Iterable[InventoryItem | dict[str, Any]],
        target_slot_id: int,
        *,
        source_inventory: str | int | InventorySnapshot | None = None,
        destination_inventory: str | int | InventorySnapshot | None = None,
    ) -> int:
        modified: List[Dict[str, Any]] = []
        for it in items:
            if isinstance(it, InventoryItem):
                payload = it.to_payload()
            elif isinstance(it, dict):
                payload = dict(it)
            else:
                continue
            payload["targetSlotId"] = int(target_slot_id)
            modified.append(payload)

        return self.move_items(
            destination,
            modified,
            source_inventory=source_inventory,
            destination_inventory=destination_inventory,
        )

    def move_all(
        self,
        destination: int | str | BaseDevice | InventorySnapshot,
        *,
        blacklist: Set[str] | None = None,
        source_inventory: str | int | InventorySnapshot | None = None,
        destination_inventory: str | int | InventorySnapshot | None = None,
    ) -> int:
        bl = {s.lower() for s in (blacklist or set())}
        batch: List[Dict[str, Any]] = []
        for item in self.items(source_inventory):
            subtype = (item.subtype or "").lower()
            if not subtype or subtype in bl:
                continue
            batch.append({"subtype": item.subtype})
        if not batch:
            return 0
        return self.move_items(
            destination,
            batch,
            source_inventory=source_inventory,
            destination_inventory=destination_inventory,
        )

    def drain_to(
        self,
        destination: int | str | BaseDevice | InventorySnapshot,
        subtypes: Iterable[str],
        *,
        source_inventory: str | int | InventorySnapshot | None = None,
        destination_inventory: str | int | InventorySnapshot | None = None,
    ) -> int:
        batch = [{"subtype": s} for s in subtypes if s]
        if not batch:
            return 0
        return self.move_items(
            destination,
            batch,
            source_inventory=source_inventory,
            destination_inventory=destination_inventory,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def find_items_by_type(
        self,
        item_type: str,
        *,
        inventory: str | int | InventorySnapshot | None = None,
    ) -> List[InventoryItem]:
        return [it for it in self.items(inventory) if it.type == item_type]

    def find_items_by_subtype(
        self,
        subtype: str,
        *,
        inventory: str | int | InventorySnapshot | None = None,
    ) -> List[InventoryItem]:
        return [it for it in self.items(inventory) if it.subtype == subtype]

    def find_items_by_display_name(
        self,
        display_name: str,
        *,
        inventory: str | int | InventorySnapshot | None = None,
    ) -> List[InventoryItem]:
        return [it for it in self.items(inventory) if it.display_name == display_name]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_items(payload: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [item.to_payload() for item in normalize_inventory_items(items)]

    @staticmethod
    def _items_signature(items: List[Any]) -> Tuple[Tuple[str, float], ...]:
        sig: List[Tuple[str, float]] = []
        for it in items:
            if isinstance(it, InventoryItem):
                name = str(it.display_name or it.subtype or "").strip()
                amount = it.amount
            else:
                name = str(it.get("displayName") or it.get("subtype") or "").strip()
                amount = float(it.get("amount") or 0.0)
            sig.append((name, amount))
        return tuple(sig)

    @staticmethod
    def _format_items(items: List[Any]) -> str:
        if not items:
            return "[]"
        parts = []
        for it in items:
            if isinstance(it, InventoryItem):
                name = it.display_name or it.subtype or "?"
                amount = it.amount
            else:
                name = it.get("displayName") or it.get("subtype") or "?"
                amount = it.get("amount")
            parts.append(f"{amount} x {name}")
        return "[" + ", ".join(parts) + "]"


Item = InventoryItem

# Backwards-compatible alias on the class itself
ContainerDevice.Item = InventoryItem


DEVICE_TYPE_MAP[ContainerDevice.device_type] = ContainerDevice
