#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import redis
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)


def publish_admin_command(client: redis.Redis, command: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
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


def parse_vector(value: str) -> dict[str, float]:
    parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Vector must contain exactly three numbers: x,y,z")
    return {"x": float(parts[0]), "y": float(parts[1]), "z": float(parts[2])}


def create_admin_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD")
    if not admin_pass:
        raise SystemExit("REDIS_ADMIN_PASSWORD not set. Add it to .env or export in shell.")
    return redis.Redis.from_url(url, username=admin_user, password=admin_pass, decode_responses=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Spawn an XML grid and transfer it to an AI faction.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--xml-file", required=True, type=Path)
    parser.add_argument("--grid-name", default=None)
    parser.add_argument("--position", required=True, type=parse_vector, help="x,y,z")
    parser.add_argument("--forward", default={"x": 0.0, "y": 0.0, "z": -1.0}, type=parse_vector)
    parser.add_argument("--up", default={"x": 0.0, "y": 1.0, "z": 0.0}, type=parse_vector)
    args = parser.parse_args()

    xml = args.xml_file.read_text(encoding="utf-8")
    admin = create_admin_client()
    ack = publish_admin_command(
        admin,
        {
            "action": "ai_faction_spawn_grid",
            "tag": args.tag,
            "xml": xml,
            "gridName": args.grid_name,
            "position": args.position,
            "forward": args.forward,
            "up": args.up,
            "shareMode": "Faction",
            "wake": True,
        },
    )
    print(json.dumps(ack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
