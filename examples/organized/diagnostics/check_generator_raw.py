"""Проверка генератора через raw Redis."""
from __future__ import annotations

import json
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    owner_id = "144115188075855919"
    grid_id = "138748817302648345"

    print("Смотрим raw данные грида...\n")
    
    # gridinfo
    gridinfo_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
    gridinfo = client.get_json(gridinfo_key)
    print(f"📋 gridinfo ({gridinfo_key}):")
    print(json.dumps(gridinfo, indent=2, ensure_ascii=False))
    
    # Ищем все ключи с blocks/devices
    print(f"\n🔍 Все ключи для грида {grid_id}:")
    pattern = f"se:{owner_id}:grid:{grid_id}:*"
    keys = client._redis.keys(pattern)
    for key in sorted(keys):
        print(f"  {key}")
    
    # Ищем генератор среди блоков
    print(f"\n🔍 Ищем генератор в gridinfo blocks:")
    if isinstance(gridinfo, dict):
        blocks = gridinfo.get("blocks", [])
        for block in blocks:
            name = block.get("name", block.get("DisplayName", ""))
            type_name = block.get("type", block.get("blockType", ""))
            if "generator" in type_name.lower() or "generator" in name.lower():
                print(f"\n  Найден: {name}")
                print(f"  Тип: {type_name}")
                for k, v in block.items():
                    print(f"    {k}: {v}")

    client.close()


if __name__ == "__main__":
    main()
