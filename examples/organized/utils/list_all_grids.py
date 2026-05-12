"""Список всех гридов."""
from __future__ import annotations

from secontrol.redis_client import RedisEventClient
from secontrol.grids import Grids


def main() -> None:
    client = RedisEventClient()
    owner_id = "144115188075855919"
    grids_manager = Grids(client, owner_id)
    
    grids = grids_manager.list()
    
    if not grids:
        print("Гриды не найдены!")
        return

    print(f"Всего гридов: {len(grids)}\n")
    print(f"{'='*70}")
    
    for i, gs in enumerate(grids, 1):
        print(f"{i}. {gs.name} (ID: {gs.grid_id})")
        # Показываю все доступные поля
        for key in ('is_subgrid', 'is_static', 'parent_grid_id', 'owner_id'):
            val = getattr(gs, key, None)
            if val is not None:
                print(f"   {key}: {val}")
        print()

    grids_manager.close()
    client.close()


if __name__ == "__main__":
    main()
