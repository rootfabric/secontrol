"""Administrative helper utilities for Space Engineers Redis bridge.

This module exposes :class:`AdminUtilitiesClient`, a thin wrapper around
:class:`~sepy.redis_client.RedisEventClient` that publishes
administrative commands understood by the dedicated plugin.  Commands are sent
through the ``system/admin`` envelope and acknowledgements are read from the
``se.commands.ack`` channel so callers can inspect the response payload.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from typing import Any, Dict, Iterable, Optional

from .redis_client import RedisEventClient

Vector3Like = Mapping[str, float] | Sequence[float]
RotationLike = Mapping[str, float] | Sequence[float]

__all__ = ["AdminUtilitiesClient"]


class AdminUtilitiesClient:
    """Publish administrative commands and wait for acknowledgements.

    Parameters default to the environment variables described in the project
    README.  Only the player identifier is strictly required; the client reads
    ``SE_PLAYER_ID`` (falling back to ``SE_OWNER_ID``) when it is not supplied
    explicitly.
    """

    def __init__(
        self,
        redis_client: RedisEventClient | None = None,
        *,
        player_id: str | int | None = None,
        ack_channel: str | None = None,
    ) -> None:
        self._owns_client = redis_client is None
        self.redis = redis_client or RedisEventClient()

        owner_env = os.getenv("SE_OWNER_ID")
        player_env = os.getenv("SE_PLAYER_ID")

        resolved_player = player_id or player_env or owner_env
        if resolved_player is None:
            raise RuntimeError(
                "Set SE_OWNER_ID (or SE_PLAYER_ID) or pass player_id to route admin commands."
            )
        self.player_id = str(resolved_player)

        self.channel = f"se.{self.player_id}.commands.admin"
        self.ack_channel = ack_channel or os.getenv("SE_ACK_CHANNEL", "se.commands.ack")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def spawn_grid(
        self,
        xml: str,
        position: Vector3Like,
        *,
        forward: Vector3Like | None = None,
        up: Vector3Like | None = None,
        rotation: RotationLike | None = None,
        wait_for_ack: bool = True,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "xml": xml,
            "position": _coerce_vector(position),
        }
        payload.update(_build_orientation(forward, up, rotation))
        return self._send("spawn_grid", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def remove_grid(
        self,
        grid_id: int | str,
        *,
        wait_for_ack: bool = True,
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        payload = {"grid_id": _coerce_id(grid_id, "grid_id")}
        return self._send("remove_grid", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def remove_block(
        self,
        block_id: int | str,
        *,
        wait_for_ack: bool = True,
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        payload = {"block_id": _coerce_id(block_id, "block_id")}
        return self._send("remove_block", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def upgrade_block(
        self,
        block_id: int | str,
        *,
        wait_for_ack: bool = True,
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        payload = {"block_id": _coerce_id(block_id, "block_id")}
        return self._send("upgrade_block", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def remove_voxel(
        self,
        position: Vector3Like,
        *,
        radius: float = 0.5,
        wait_for_ack: bool = True,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "position": _coerce_vector(position),
            "radius": float(radius),
        }
        return self._send("remove_voxel", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def fill_voxel(
        self,
        position: Vector3Like,
        *,
        material: str,
        radius: float = 0.5,
        wait_for_ack: bool = True,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        if not material:
            raise ValueError("material must be a non-empty string")
        payload = {
            "position": _coerce_vector(position),
            "material": str(material),
            "radius": float(radius),
        }
        return self._send("fill_voxel", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def teleport_grid(
        self,
        grid_id: int | str,
        position: Vector3Like,
        *,
        forward: Vector3Like | None = None,
        up: Vector3Like | None = None,
        rotation: RotationLike | None = None,
        wait_for_ack: bool = True,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "grid_id": _coerce_id(grid_id, "grid_id"),
            "position": _coerce_vector(position),
        }
        payload.update(_build_orientation(forward, up, rotation))
        return self._send("teleport_grid", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def show_mission_screen(
        self,
        body: str,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        description: str | None = None,
        ok_text: str | None = None,
        broadcast: bool | None = None,
        player_id: int | str | None = None,
        steam_id: int | str | None = None,
        player_name: str | None = None,
        wait_for_ack: bool = True,
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        """Display a mission screen (chat-style popup) in-game.

        Parameters mirror the dedicated plugin API.  ``body`` is required;
        the rest of the fields are optional and default to broadcasting the
        message unless a specific target is provided.
        """

        if body is None:
            text = ""
        else:
            text = str(body).strip()
        if not text:
            raise ValueError("body must be a non-empty string")

        payload: Dict[str, Any] = {"body": text}

        def _assign(optional_value: str | None, key: str) -> None:
            if optional_value:
                trimmed = optional_value.strip()
                if trimmed:
                    payload[key] = trimmed

        _assign(title, "title")
        _assign(subtitle, "subtitle")
        _assign(description, "description")
        _assign(ok_text, "ok")
        _assign(player_name, "player_name")

        if broadcast is not None:
            payload["broadcast"] = bool(broadcast)
        if player_id is not None:
            payload["player_id"] = _coerce_id(player_id, "player_id")
        if steam_id is not None:
            payload["steam_id"] = _coerce_id(steam_id, "steam_id")

        return self._send("mission_screen", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    def send_chat_message(
        self,
        message: str,
        *,
        author: str | None = None,
        broadcast: bool | None = None,
        player_id: int | str | None = None,
        steam_id: int | str | None = None,
        player_name: str | None = None,
        wait_for_ack: bool = True,
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        """Send a message to the in-game chat.

        Parameters mirror the dedicated plugin API.  ``message`` is required;
        ``author`` is optional and defaults to "Server".  Use ``broadcast``
        for all players, or specify a target with ``player_id``, ``steam_id``,
        or ``player_name``.
        """

        if message is None:
            text = ""
        else:
            text = str(message).strip()
        if not text:
            raise ValueError("message must be a non-empty string")

        payload: Dict[str, Any] = {"message": text}

        if author is not None:
            trimmed = str(author).strip()
            if trimmed:
                payload["author"] = trimmed
            else:
                payload["author"] = "Server"
        else:
            payload["author"] = "Server"

        # Handle targeting: broadcast=True overrides specific targets
        if broadcast:
            payload["broadcast"] = True
        else:
            # Check for specific targets
            if player_id is not None:
                payload["player_id"] = _coerce_id(player_id, "player_id")
            if steam_id is not None:
                payload["steam_id"] = _coerce_id(steam_id, "steam_id")
            if player_name is not None:
                trimmed_name = str(player_name).strip()
                if trimmed_name:
                    payload["player_name"] = trimmed_name

        return self._send("chat_message", payload, wait_for_ack=wait_for_ack, timeout=timeout)

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self.redis.close()

    def __enter__(self) -> "AdminUtilitiesClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _send(
        self,
        action: str,
        admin_payload: Dict[str, Any],
        *,
        wait_for_ack: bool,
        timeout: float,
    ) -> Optional[Dict[str, Any]]:
        seq = _generate_sequence()
        envelope = {
            "seq": seq,
            "ts": int(time.time() * 1000),
            "system": {
                "admin": {
                    "action": action,
                    **admin_payload,
                }
            },
        }

        self.redis.publish(self.channel, envelope)

        if not wait_for_ack:
            return None

        return self._wait_for_ack(seq, timeout)

    def _wait_for_ack(self, seq: int, timeout: float) -> Optional[Dict[str, Any]]:
        client = self.redis.client
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            pubsub.subscribe(self.ack_channel)
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None

                message = pubsub.get_message(timeout=min(1.0, remaining))
                if not message or message.get("type") != "message":
                    continue

                data = message.get("data")
                if isinstance(data, bytes):
                    try:
                        decoded = data.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                elif isinstance(data, str):
                    decoded = data
                else:
                    continue

                try:
                    payload = json.loads(decoded)
                except json.JSONDecodeError:
                    continue

                if not isinstance(payload, dict):
                    continue

                if _matches_sequence(payload.get("seq"), seq) and (
                    not payload.get("channel")
                    or str(payload["channel"]).lower() == self.channel.lower()
                ):
                    return payload
        finally:
            try:
                pubsub.unsubscribe(self.ack_channel)
            finally:
                pubsub.close()


# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def _generate_sequence() -> int:
    return int(time.time() * 1000)


def _matches_sequence(candidate: Any, seq: int) -> bool:
    try:
        return int(candidate) == seq
    except (TypeError, ValueError):
        return False


def _coerce_id(value: int | str, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer value") from exc


def _coerce_vector(value: Vector3Like) -> Dict[str, float]:
    if isinstance(value, Mapping):
        return {
            "x": _component(value, ("x", "X")),
            "y": _component(value, ("y", "Y")),
            "z": _component(value, ("z", "Z")),
        }

    if isinstance(value, Sequence):
        items = list(value)
        if len(items) != 3:
            raise ValueError("vector must contain exactly three components")
        return {
            axis: float(items[idx])
            for idx, axis in enumerate(("x", "y", "z"))
        }

    raise TypeError("vector must be a mapping or a 3-component sequence")


def _build_orientation(
    forward: Vector3Like | None,
    up: Vector3Like | None,
    rotation: RotationLike | None,
) -> Dict[str, Any]:
    orientation: Dict[str, Any] = {}

    if forward is not None or up is not None:
        if forward is None or up is None:
            raise ValueError("both forward and up vectors must be provided together")
        orientation["forward"] = _coerce_vector(forward)
        orientation["up"] = _coerce_vector(up)
        return orientation

    if rotation is not None:
        orientation["rotation"] = _coerce_rotation(rotation)

    return orientation


def _coerce_rotation(value: RotationLike) -> Dict[str, float]:
    if isinstance(value, Mapping):
        return {
            "yaw": _component(value, ("yaw", "Yaw")),
            "pitch": _component(value, ("pitch", "Pitch")),
            "roll": _component(value, ("roll", "Roll")),
        }

    if isinstance(value, Sequence):
        items = list(value)
        if len(items) != 3:
            raise ValueError("rotation must contain yaw, pitch and roll components")
        return {
            key: float(items[idx])
            for idx, key in enumerate(("yaw", "pitch", "roll"))
        }

    raise TypeError("rotation must be a mapping or a 3-component sequence")


def _component(source: Mapping[str, Any], keys: Iterable[str]) -> float:
    first = None
    for key in keys:
        if first is None:
            first = key
        if key in source:
            try:
                return float(source[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"component {key!r} must be numeric") from exc
    if first is None:
        raise ValueError("component name is undefined")
    raise ValueError(f"component {first!r} is missing")
