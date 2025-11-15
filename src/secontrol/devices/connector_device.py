"""Connector device implementation for Space Engineers grid control.

This module provides functionality to control ship connectors on SE grids,
including locking/unlocking, connecting/disconnecting, and remote item transfer.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from secontrol.devices.container_device import ContainerDevice, DEVICE_TYPE_MAP


class ConnectorDevice(ContainerDevice):
    device_type = "connector"

    def set_state(self, *, locked: Optional[bool] = None, enabled: Optional[bool] = None) -> int:
        state: dict[str, any] = {}
        if locked is not None:
            state["locked"] = bool(locked)
        if enabled is not None:
            state["enabled"] = bool(enabled)
        return self.send_command({
            "cmd": "connector_state",
            "state": state,
        })

    # ------------------------------------------------------------------
    # Connection commands
    # ------------------------------------------------------------------
    def connect(self) -> int:
        """Connect the connector to another connector."""
        return self.send_command({"cmd": "connect"})

    def disconnect(self) -> int:
        """Disconnect the connector."""
        return self.send_command({"cmd": "disconnect"})

    def toggle_connect(self) -> int:
        """Toggle the connection state of the connector."""
        return self.send_command({"cmd": "toggle_connect"})

    # ------------------------------------------------------------------
    # Configuration commands
    # ------------------------------------------------------------------
    def set_throw_out(self, throw_out: bool) -> int:
        """Set whether the connector throws out items when disconnecting."""
        return self.send_command({
            "cmd": "set_throw_out",
            "state": {"throwOut": bool(throw_out)},
        })

    def set_collect_all(self, collect_all: bool) -> int:
        """Set whether the connector collects all items in range."""
        return self.send_command({
            "cmd": "set_collect_all",
            "state": {"collectAll": bool(collect_all)},
        })

    def nearbyConnectors(self):
        return self.telemetry.get("nearbyConnectors")
    # ------------------------------------------------------------------
    # Remote transfer commands
    # ------------------------------------------------------------------
    def transfer_remote(
        self,
        target_connector_id: int,
        items: List[Dict[str, Any]],
        radius: float = 100.0
    ) -> int:
        """Transfer items to a remote connector.

        Args:
            target_connector_id: Entity ID of the target connector
            items: List of items to transfer, each dict should contain:
                - subtype: Item subtype (required)
                - type: Item type (optional)
                - amount: Amount to transfer (optional, defaults to all)
            radius: Search radius for target connector (default 100.0)

        Returns:
            Number of commands sent
        """
        normalized_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            subtype = item.get("subtype") or item.get("subType")
            if not subtype:
                continue
            entry = {"subtype": str(subtype)}
            if item.get("type"):
                entry["type"] = str(item["type"])
            if item.get("amount") is not None:
                entry["amount"] = float(item["amount"])
            normalized_items.append(entry)

        if not normalized_items:
            return 0

        return self.send_command({
            "cmd": "transfer_remote",
            "state": {
                "targetConnectorId": int(target_connector_id),
                "radius": float(radius),
                "items": normalized_items,
            },
        })

    # ------------------------------------------------------------------
    # Scanning commands
    # ------------------------------------------------------------------
    def scan(self, radius: float = 100.0) -> int:
        """Scan for nearby connectors within the specified radius.

        Results will be published to telemetry or logs.
        """
        return self.send_command({
            "cmd": "scan",
            "state": {"radius": float(radius)},
        })

    def transfer_to_nearby(self, items: List[Dict[str, Any]], radius: float = 100.0) -> int:
        """Transfer items to the first nearby connector found in telemetry.

        Assumes scan() has been called and nearbyConnectors are in telemetry.

        Args:
            items: List of items to transfer
            radius: Search radius (default 100.0)

        Returns:
            Number of commands sent, or 0 if no nearby connectors found
        """
        if not isinstance(self.telemetry, dict):
            return 0
        nearby = self.telemetry.get("nearbyConnectors")
        if not isinstance(nearby, list) or not nearby:
            return 0
        first_connector = nearby[0]
        target_id = first_connector.get("id")
        if target_id is None:
            return 0
        return self.transfer_remote(int(target_id), items, radius)


DEVICE_TYPE_MAP[ConnectorDevice.device_type] = ConnectorDevice
