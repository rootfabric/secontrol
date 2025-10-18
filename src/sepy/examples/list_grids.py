from __future__ import annotations

import json

from sepy.redis_client import RedisEventClient
from sepy.common import resolve_owner_id


def main() -> None:
    owner_id = resolve_owner_id()
    print(owner_id)

    try:
        client = RedisEventClient()
        grids = client.list_grids(owner_id)
        if not grids:
            print("No grids found. Ensure the owner id is correct and the Redis bridge is running.")
            return

        print(f"Found {len(grids)} grids for owner {owner_id}:")
        for grid_raw in grids:
            grid_id = grid_raw.get("id")
            print(grid_id)

            # Пример создания объекта SimpleGrid, который сам разбирается с зависимостями
            # grid_raw = GridConstructor(grid_id)
            # print(f"   SimpleGrid object created for {grid_raw.name}")

        print("\nRaw response:")
        print(json.dumps({"grids": grids}, indent=2, ensure_ascii=False))
    finally:
        client.close()


if __name__ == "__main__":
    main()
