#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
telemetry_reader.py

Reads telemetry data from Space Engineers Redis bridge.

Subscribes to telemetry pub/sub channels and displays incoming messages.
Also checks persistent telemetry keys for verification.

Takes values from existing project environment variables:
  - REDIS_URL          — address Redis (e.g., redis://host:port/db)
  - REDIS_PORT         — port Redis (overrides port in URL if set)
  - REDIS_DB           — DB number (overrides DB in URL if set)
  - REDIS_USERNAME     — UID/username (also ownerId)
  - REDIS_PASSWORD     — user password

Load from .env file if present.

Usage:
    python -m secontrol.tools.telemetry_reader
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import redis
from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv(usecwd=True), override=False)


def _resolve_url_with_overrides() -> tuple[str, int]:
    """
    Returns (resolved_url, effective_db).
    Considers REDIS_URL and overrides REDIS_PORT / REDIS_DB.
    """

    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    port_env = os.getenv("REDIS_PORT")
    db_env = os.getenv("REDIS_DB")

    pu = urlparse(url)

    # Port: override if specified and valid
    try:
        if port_env is not None:
            port_val = int(port_env)
            if port_val > 0:
                netloc = pu.hostname or "127.0.0.1"
                if pu.username and pu.password:
                    auth = f"{pu.username}:{pu.password}@"
                elif pu.username:
                    auth = f"{pu.username}@"
                else:
                    auth = ""
                url = urlunparse((pu.scheme, f"{auth}{netloc}:{port_val}", pu.path, pu.params, pu.query, pu.fragment))
                pu = urlparse(url)
    except (TypeError, ValueError):
        pass

    # DB: if set — rewrite path in URL
    effective_db = None
    try:
        if db_env is not None:
            db_val = int(db_env)
            if db_val >= 0:
                effective_db = db_val
                url = urlunparse((pu.scheme, pu.netloc, f"/{db_val}", pu.params, pu.query, pu.fragment))
                pu = urlparse(url)
    except (TypeError, ValueError):
        pass

    # If DB not explicitly set — take from URL
    if effective_db is None:
        try:
            path = pu.path.lstrip("/")
            effective_db = int(path) if path else 0
        except (TypeError, ValueError):
            effective_db = 0

    return url, effective_db


def main() -> None:
    # Configure Redis connection
    resolved_url, effective_db = _resolve_url_with_overrides()
    username = os.getenv("REDIS_ADMIN_USERNAME")
    password = os.getenv("REDIS_ADMIN_PASSWORD")

    connection_kwargs = {
        "decode_responses": False,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "retry_on_timeout": True,
        "socket_timeout": 5,
    }
    if username:
        connection_kwargs["username"] = username
    if password:
        connection_kwargs["password"] = password

    client = redis.Redis.from_url(resolved_url, **connection_kwargs)

    # Test connection and display persistent telemetry data for verification
    print("Checking persistent telemetry keys...")
    persistent_keys = [
        "se:system:status",
        "se:system:load",
    ]

    # Try to get owner ID if available (from SE_PLAYER_ID or guess)
    owner_id = os.getenv("SE_PLAYER_ID") or "default"
    if owner_id != "default":
        # Add some owner-specific keys
        persistent_keys.extend([
            f"se:{owner_id}:grids",
            "se:bridge:self_test",
        ])

    for key in persistent_keys:
        value = client.get(key)
        if value is not None:
            try:
                decoded = json.loads(value.decode("utf-8"))
                print(f"{key}: {json.dumps(decoded, indent=2)}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"{key}: {value.decode('utf-8', 'replace')}")
        else:
            print(f"{key}: (no data)")

    # Check keys matching se:*
    se_keys = client.keys("se:*")
    print(f"\nTotal 'se:*' keys: {len(se_keys)}")
    for key in sorted(se_keys)[:20]:  # Show first 20
        decoded_key = key.decode("utf-8") if isinstance(key, bytes) else key
        print(f"  {decoded_key}")

    if len(se_keys) > 20:
        print(f"  ... and {len(se_keys) - 20} more")

    print("\nSubscribing to telemetry channels: se.telemetry.*")
    print("Press Ctrl+C to stop.\n")

    # Subscribe to telemetry patterns
    pubsub = client.pubsub(ignore_subscribe_messages=True)

    # Subscribe to patterns for all telemetry
    patterns = [
        "se.telemetry.*",
        # "se.system.status",  # Note: system/status might use this key space, but channel is se.system.status
        # "se.system.load",
    ]

    pubsub.psubscribe(*patterns)

    try:
        while True:
            message = pubsub.get_message(timeout=1.0)
            if message:
                handle_message(message)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        pubsub.close()
        client.close()


def handle_message(message: dict[str, Any]) -> None:
    """Process incoming pub/sub message."""
    # In Redis pubsub, messages come as:
    # {'type': 'pmessage', 'pattern': 'se.telemetry.*', 'channel': b'se.telemetry.heartbeat', 'data': b'{"timestamp": "..."}'}

    msg_type = message.get('type')
    if msg_type not in ('message', 'pmessage'):
        return  # Skip other messages like subscribe confirmations

    pattern = message.get('pattern')
    channel_bytes = message.get('channel')
    data_bytes = message.get('data')

    # Decode bytes
    channel = channel_bytes.decode('utf-8') if isinstance(channel_bytes, bytes) else str(channel_bytes)
    data = data_bytes.decode('utf-8') if isinstance(data_bytes, bytes) else str(data_bytes)

    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]  # HH:MM:SS.mmm

    print(f"[{timestamp}] Channel: {channel}")

    if pattern:
        print(f"  Pattern: {pattern}")

    # Try to parse as JSON
    try:
        parsed_data = json.loads(data)
        print(f"  Payload: {json.dumps(parsed_data, ensure_ascii=False, indent=2)}")
    except json.JSONDecodeError:
        print(f"  Payload: {data}")

    print("***************************************************")  # Empty line for readability


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
