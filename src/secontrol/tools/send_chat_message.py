"""
Example: Sending chat messages to the game chat using admin utilities.

This script demonstrates how to send a message to the in-game chat using
the AdminUtilitiesClient.send_chat_message method, which sends proper chat
messages in Space Engineers with support for broadcasting to all players
or targeting specific players.

Requirements:
- Redis bridge connection must be active
- Set environment variables:
  - REDIS_USERNAME or SE_OWNER_ID: Your Space Engineers owner ID
  - SE_PLAYER_ID (optional): Player ID to send message as (defaults to owner ID)
  - REDIS_ADMIN_PASSWORD: Admin password for Redis (required for admin commands)
  - REDIS_ADMIN_USERNAME (optional): Admin username (defaults to "default")
  - SE_ACK_CHANNEL (optional): Channel for acknowledgments (defaults to "se.commands.ack")

Usage:
  python send_chat_message.py

The script sends a broadcast message to all players by default. To customize:
- Edit the message, author, or broadcast settings in the main() function
- Set specific player_id, steam_id, or player_name to target individual players
- Set broadcast=True for all players, broadcast=False or omit to use targeting
"""

from __future__ import annotations

import os

from secontrol.admin import AdminUtilitiesClient
from secontrol.common import resolve_owner_id, resolve_player_id
from secontrol.redis_client import RedisEventClient


def main() -> None:
    # Resolve player and owner IDs from environment
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)

    print(f"Using owner_id: {owner_id}")
    print(f"Using player_id: {player_id}")

    # Create Redis client with admin credentials for admin commands
    admin_username = os.getenv("REDIS_ADMIN_USERNAME", "default")
    admin_password = os.getenv("REDIS_ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError("REDIS_ADMIN_PASSWORD environment variable is required for admin commands")

    redis_client = RedisEventClient(username=admin_username, password=admin_password)

    # Create admin client with authenticated redis connection
    with AdminUtilitiesClient(redis_client=redis_client, player_id=player_id) as admin:
        # Send a broadcast message to all players
        broadcast_message = "Hello from Python API! This is a broadcast message to all players."
        print(f"Sending broadcast message: {broadcast_message}")

        response = admin.send_chat_message(
            message=broadcast_message,
            # author="Server",
            broadcast=True
        )

        if response:
            print("Broadcast message sent successfully!")
            print(f"Response: {response}")
        else:
            print("Failed to send broadcast message or no acknowledgment received.")

        print()  # Spacing

        # Send a private message to one specific player
        private_message = "Private hello from the API!"
        target_player_name = "ChangeThisToActualPlayerName"  # Replace with actual player name
        print(f"Sending private message to '{target_player_name}': {private_message}")

        # response = admin.send_chat_message(
        #     message=private_message,
        #     author="Server",
        #     player_name=target_player_name  # Send to specific player by name
        # )

        if response:
            print("Private message sent successfully!")
            print(f"Response: {response}")
        else:
            print("Failed to send private message or no acknowledgment received.")


if __name__ == "__main__":
    main()
