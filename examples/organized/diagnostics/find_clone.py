"""Поиск клона DroneBase."""
from __future__ import annotations

from secontrol.redis_client import RedisEventClient
from secontrol.grids import Grids, Grid


def main() -> None:
    client = RedisEventClient()
    owner_id = "144115188075855919"
    grids_manager = Grids(client, owner_id)
    grids = grids_manager.list()

    # Ищем гриды с похожим названием
    print("🔍 Ищу клон DroneBase...\n")
    
    for gs in grids:
        name = gs.name or ""
        if "drone" in name.lower() or "base" in name.lower():
            print(f"  Найдено: {name} (ID: {gs.grid_id})")
    
    # Проверяю состав гридов по ключевым блокам
    print("\n🔍 Проверяю состав каждого грида...")
    
    dronebase_blocks = set()
    for gs in grids:
        if gs.name == "DroneBase":
            gridinfo_key = f"se:{owner_id}:grid:{gs.grid_id}:gridinfo"
            info = client.get_json(gridinfo_key)
            if info and "blocks" in info:
                for b in info["blocks"]:
                    dronebase_blocks.add(b.get("type"))
            break
    
    print(f"  DroneBase типы блоков: {dronebase_blocks}\n")
    
    for gs in grids:
        if gs.name == "DroneBase":
            continue
            
        gridinfo_key = f"se:{owner_id}:grid:{gs.grid_id}:gridinfo"
        info = client.get_json(gridinfo_key)
        if not info or "blocks" not in info:
            continue
            
        grid_blocks = set()
        for b in info["blocks"]:
            grid_blocks.add(b.get("type"))
        
        # Считаем совпадение
        common = dronebase_blocks & grid_blocks
        if len(common) > 3:  # Если много совпадений
            match_pct = len(common) / max(len(dronebase_blocks), 1) * 100
            print(f"  🎯 {gs.name} (ID: {gs.grid_id})")
            print(f"     Совпадение блоков: {match_pct:.0f}% ({len(common)}/{len(dronebase_blocks)})")
            print(f"     Блоки: {grid_blocks}")

    grids_manager.close()
    client.close()


if __name__ == "__main__":
    main()
