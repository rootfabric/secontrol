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


def create_admin_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD")
    if not admin_pass:
        raise SystemExit("REDIS_ADMIN_PASSWORD not set. Add it to .env or export in shell.")
    return redis.Redis.from_url(url, username=admin_user, password=admin_pass, decode_responses=True)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Close/open an AI faction and manage join requests.")
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--action",
        choices=["close", "open", "set", "clear-requests", "kick-non-owner-members"],
        required=True,
    )
    parser.add_argument("--accept-humans", choices=["true", "false"], default=None)
    parser.add_argument("--auto-accept-members", choices=["true", "false"], default=None)
    parser.add_argument("--auto-accept-peace", choices=["true", "false"], default=None)
    parser.add_argument("--clear-join-requests", action="store_true")
    parser.add_argument("--kick-non-owner-members", action="store_true")
    args = parser.parse_args()

    action_map = {
        "close": "ai_faction_close",
        "open": "ai_faction_open",
        "set": "ai_faction_set_join_policy",
        "clear-requests": "ai_faction_clear_join_requests",
        "kick-non-owner-members": "ai_faction_kick_non_owner_members",
    }
    command: dict[str, Any] = {
        "action": action_map[args.action],
        "tag": args.tag,
    }

    def parse_bool(value: str | None) -> bool | None:
        if value is None:
            return None
        return value.lower() == "true"

    accept_humans = parse_bool(args.accept_humans)
    auto_accept_members = parse_bool(args.auto_accept_members)
    auto_accept_peace = parse_bool(args.auto_accept_peace)
    if accept_humans is not None:
        command["acceptHumans"] = accept_humans
    if auto_accept_members is not None:
        command["autoAcceptMembers"] = auto_accept_members
    if auto_accept_peace is not None:
        command["autoAcceptPeace"] = auto_accept_peace
    if args.clear_join_requests:
        command["clearJoinRequests"] = True
    if args.kick_non_owner_members:
        command["kickNonOwnerMembers"] = True

    admin = create_admin_client()
    ack = publish_admin_command(admin, command)
    print(json.dumps(ack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
