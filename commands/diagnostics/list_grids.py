from __future__ import annotations

import json

from secontrol.redis_client import RedisEventClient
from secontrol.common import resolve_owner_id
from secontrol import Grid, Grids


def main() -> None:
    client = RedisEventClient()
    # Создаём менеджер Grids для автоматического отслеживания гридов
    grids_manager = Grids(client, "144115188075855919")
    grids = grids_manager.list()
    if not grids:
        print("No grids found. Ensure the owner id is correct and the Redis bridge is running.")
        return

    print(f"Found {len(grids)} grids for owner :")
    for grid_state in grids:
        grid_id = grid_state.grid_id
        print(grid_state)

        # Создаём Grid и передаём известное имя из состояния грида
        grid = Grid.from_name(grid_state.grid_id)
        print(f"SimpleGrid object created for {grid.name}")

    print("\nRaw response:")
    print(json.dumps({"grids": [state.descriptor for state in grids]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
