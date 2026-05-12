"""Переименование клона DroneBase."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.grids import Grids


def main() -> None:
    client = RedisEventClient()
    owner_id = "144115188075855919"
    
    # Находим грид по ID
    grids_manager = Grids(client, owner_id)
    grids = grids_manager.list()
    
    clone_id = "134540402238780591"
    
    for gs in grids:
        if gs.grid_id == clone_id:
            print(f"Нашёл: {gs.name} (ID: {gs.grid_id})")
            break
    
    grids_manager.close()
    
    # Подключаемся к гриду по ID
    grid = Grid(client, owner_id, clone_id, owner_id, auto_wake=True)
    print(f"Текущее имя: {grid.name}")
    
    print(f"\n✏️ Переименую в 'DroneBase 2'...")
    result = grid.rename("DroneBase 2")
    print(f"  Результат: {result}")
    
    time.sleep(2)
    grid.close()
    
    # Проверяем
    print("\n🔄 Проверяю...")
    grid2 = Grid.from_name("DroneBase 2", redis_client=client)
    print(f"✅ Новое имя: {grid2.name}")
    
    grid2.close()
    client.close()


if __name__ == "__main__":
    main()
