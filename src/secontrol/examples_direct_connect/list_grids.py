from __future__ import annotations

import json

from secontrol.redis_client import RedisEventClient
from secontrol.common import resolve_owner_id
from secontrol.base_device import Grid


def main() -> None:
    owner_id = resolve_owner_id()
    print(owner_id)

    try:
        client = RedisEventClient()
        grids = client.list_grids("144115188075855919")
        if not grids:
            print("No grids found. Ensure the owner id is correct and the Redis bridge is running.")
            return

        print(f"Found {len(grids)} grids for owner {owner_id}:")
        for grid_info in grids:
            grid_id = grid_info.get("id")
            print(grid_id)

            # Создаём Grid и передаём известное имя из списка грида
            grid = Grid(client, owner_id, grid_id, owner_id, name=grid_info.get("name"))
            print(f"SimpleGrid object created for {grid.name}")




        print("\nRaw response:")
        print(json.dumps({"grids": grids}, indent=2, ensure_ascii=False))
    finally:
        client.close()


if __name__ == "__main__":
    main()
