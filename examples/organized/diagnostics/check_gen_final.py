"""Состояние газогенератора через блоки."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("DroneBase", redis_client=client)
    print(f"Грид: {grid.name}\n")

    for block in grid.iter_blocks():
        block_type = str(getattr(block, 'block_type', ''))
        if 'OxygenGenerator' in block_type:
            print(f"🔧 OxygenGenerator")
            print(f"  block_id: {block.block_id}")
            print(f"  block_type: {block.block_type}")
            print(f"\n📋 state:")
            for key, value in (block.state or {}).items():
                print(f"  {key}: {value}")
            
            # Ключевые параметры
            state = block.state or {}
            build_ratio = state.get("buildRatio", 0)
            integrity = state.get("integrity")
            max_integrity = state.get("maxIntegrity")
            
            print(f"\n🔨 Целостность:")
            print(f"  Построен:     {float(build_ratio)*100:.1f}%")
            if integrity and max_integrity:
                print(f"  Integrity:    {integrity} / {max_integrity} ({integrity/max_integrity*100:.1f}%)")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
