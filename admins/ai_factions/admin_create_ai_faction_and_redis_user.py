#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import time
from typing import Any

import redis
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)


def make_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def publish_admin_command(client: redis.Redis, command: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    seq = int(time.time() * 1000)
    payload = {"seq": seq, "system": {"admin": command}}
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("se.commands.ack")
    last_ack: dict[str, Any] | None = None
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
                if data.get("ok"):
                    return data
                last_ack = data
                if data.get("err") != "unknown_action":
                    return data
        if last_ack is not None:
            return last_ack
        raise TimeoutError(f"No ack for seq={seq}")
    finally:
        pubsub.close()


def create_redis_acl_user(
    client: redis.Redis,
    owner_id: int,
    tag: str,
    username: str,
    password: str,
    readonly: bool = False,
) -> dict[str, Any]:
    owner = str(owner_id)
    commands = ["+@read", "+@pubsub"] if readonly else ["+@read", "+@write", "+@pubsub"]
    key_patterns = [
        f"~se:{owner}:*",
        f"~se:{owner}:grids",
        f"~se:system:players:{owner}",
        f"~se:system:players:{owner}:*",
        "~se:system:status",
        "~se:system:heartbeat",
        "~se:system:ai_factions",
        f"~se:system:ai_factions:{tag}",
    ]
    channel_patterns = [
        f"&se.{owner}.commands",
        f"&se.{owner}.commands.*",
        f"&se:{owner}:commands",
        f"&se:{owner}:commands:*",
        "&se.commands.ack",
        f"&se.{owner}.commands.ack",
        f"&se:{owner}:commands:ack",
    ]
    client.execute_command(
        "ACL",
        "SETUSER",
        username,
        "on",
        "resetpass",
        f">{password}",
        "resetkeys",
        "resetchannels",
        *commands,
        *key_patterns,
        *channel_patterns,
    )
    metadata = {
        "username": username,
        "password": password,
        "ownerId": owner_id,
        "tag": tag,
        "kind": "ai_faction_redis_user",
        "keyPatterns": key_patterns,
        "channelPatterns": channel_patterns,
    }
    client.set(f"se:system:players:{owner}:redis", json.dumps({k: v for k, v in metadata.items() if k != "password"}, ensure_ascii=False))
    client.set(f"se:system:ai_factions:{tag}:redis", json.dumps({k: v for k, v in metadata.items() if k != "password"}, ensure_ascii=False))
    return metadata


def create_admin_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD")
    if not admin_pass:
        raise SystemExit("REDIS_ADMIN_PASSWORD not set. Add it to .env or export in shell.")
    return redis.Redis.from_url(url, username=admin_user, password=admin_pass, decode_responses=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an AI faction in Space Engineers and a matching Redis ACL user.")
    parser.add_argument("--tag", default="AIMN", help="Faction tag")
    parser.add_argument("--name", default="AI Miners", help="Faction display name")
    parser.add_argument("--description", default="Autonomous AI-controlled faction")
    parser.add_argument("--npc-name", default="AI Miners Core")
    parser.add_argument("--redis-username", default=None, help="Redis username. Default: se_faction_<tag>_<ownerId>")
    parser.add_argument("--redis-password", default=None, help="Redis password. Generated when omitted.")
    parser.add_argument("--readonly", action="store_true", help="Create a read-only Redis user")
    args = parser.parse_args()

    admin = create_admin_client()
    ack = publish_admin_command(
        admin,
        {
            "action": "ai_faction_create",
            "tag": args.tag,
            "name": args.name,
            "description": args.description,
            "npcName": args.npc_name,
        },
    )
    if not ack.get("ok"):
        raise SystemExit(json.dumps(ack, ensure_ascii=False, indent=2))

    owner_id = int(ack["ownerIdentityId"])
    canonical_tag = str(ack.get("tag") or args.tag).upper()
    username = args.redis_username or f"se_faction_{canonical_tag.lower()}_{owner_id}"
    password = args.redis_password or make_password()
    acl = create_redis_acl_user(admin, owner_id, canonical_tag, username, password, readonly=args.readonly)

    print(json.dumps({"faction": ack, "redisUser": acl}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
