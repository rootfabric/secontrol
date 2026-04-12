"""Достройка газогенератора на DroneBase."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("DroneBase", redis_client=client)
    print(f"Грид: {grid.name}\n")

    # Находим сварщик
    welders = grid.find_devices_by_type("ship_welder")
    if not welders:
        print("❌ Сварщик не найден!")
        grid.close()
        return

    welder = welders[0]
    print(f"🔧 Сварщик: {type(welder).__name__}")

    # Включаем сварщик
    print("⚡ Включаю сварщик...")
    welder.set_enabled(True)
    time.sleep(2)

    # Ждём достройку
    print("⏳ Достройка генератора (до 60 сек)...\n")
    
    for i in range(60):
        time.sleep(1)
        grid.refresh_devices()
        
        for block in grid.iter_blocks():
            if 'OxygenGenerator' in str(getattr(block, 'block_type', '')):
                state = block.state or {}
                build = state.get("buildRatio", 0)
                integrity = state.get("integrity", 0)
                max_int = state.get("maxIntegrity", 1)
                working = state.get("working", False)
                
                pct = float(build) * 100
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                print(f"  [{bar}] {pct:5.1f}%  ({integrity:.0f}/{max_int:.0f})  working={working}")
                
                if pct >= 100.0:
                    print(f"\n✅ Генератор достроен!")
                    grid.close()
                    client.close()
                    return
                break
    else:
        print("\n⏰ Время вышло!")
        grid.refresh_devices()
        for block in grid.iter_blocks():
            if 'OxygenGenerator' in str(getattr(block, 'block_type', '')):
                state = block.state or {}
                build = state.get("buildRatio", 0)
                print(f"  Финальный статус: {float(build)*100:.1f}%")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
