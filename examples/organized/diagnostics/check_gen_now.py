"""Свежее состояние газогенератора."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("DroneBase", redis_client=client)
    
    # Принудительно обновляем
    grid.refresh_devices()
    
    print(f"Грид: {grid.name}\n")

    for block in grid.iter_blocks():
        block_type = str(getattr(block, 'block_type', ''))
        if 'OxygenGenerator' in block_type:
            print(f"🔧 OxygenGenerator (ID: {block.block_id})")
            state = block.state or {}
            
            print(f"\n📋 Все поля state:")
            for key, value in state.items():
                print(f"  {key}: {value}")
            
            # Вычисляем процент
            build = state.get("buildRatio", 0)
            integ = state.get("integrity", 0)
            max_int = state.get("maxIntegrity", 1)
            
            print(f"\n🔨 Итог:")
            print(f"  Построен:    {float(build)*100:.1f}%")
            print(f"  Целостность: {integ} / {max_int} ({float(integ)/float(max_int)*100:.1f}%)")
            print(f"  Работает:    {state.get('working', False)}")
            print(f"  Включён:     {state.get('enabled', False)}")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
