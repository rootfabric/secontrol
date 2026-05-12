"""Переименование taburet2 на DroneBase 2."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("taburet2", redis_client=client)
    
    print(f"Текущее имя: {grid.name}")
    print(f"ID: {grid.grid_id}")
    
    print(f"\n✏️ Переименую в 'taburet3'...")
    grid.rename("taburet3")
    time.sleep(1)
    grid.close()
    
    # Проверяю
    grids_id = "105430401719413217"
    grid2 = Grid(client, "144115188075855919", grids_id, "144115188075855919", auto_wake=True)
    print(f"✅ Новое имя: {grid2.name}")
    grid2.close()
    client.close()


if __name__ == "__main__":
    main()
