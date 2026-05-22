#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

import redis
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)


def publish_admin_command(client: redis.Redis, command: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    seq = int(time.time() * 1000)
    payload = {"seq": seq, "system": {"admin": command}}
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("se.commands.ack")
    try:
        client.publish("se.commands", json.dumps(payload, ensure_ascii=False))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = pubsub.get_message(timeout=0.25)
            if not message:
                continue
            raw = message.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if data.get("seq") == seq:
                return data
        raise TimeoutError(f"No ack for seq={seq}")
    finally:
        pubsub.close()


def create_admin_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD")
    if not admin_pass:
        raise SystemExit("REDIS_ADMIN_PASSWORD not set. Add it to .env or export in shell.")
    return redis.Redis.from_url(url, username=admin_user, password=admin_pass, decode_responses=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign an existing grid to an AI faction or remove a faction grid.")
    parser.add_argument("--action", choices=["assign", "remove"], required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--grid-id", required=True, type=int)
    args = parser.parse_args()

    admin = create_admin_client()
    command = {
        "action": "ai_faction_assign_grid" if args.action == "assign" else "ai_faction_remove_grid",
        "tag": args.tag,
        "gridId": args.grid_id,
        "shareMode": "Faction",
        "wake": True,
    }
    ack = publish_admin_command(admin, command)
    print(json.dumps(ack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
