"""Включить сварщик на базе для ремонта RemoteControl дрона."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    
    # === База ===
    print("🏗️ DroneBase 2...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    welders = base.find_devices_by_type("ship_welder")
    if not welders:
        print("  ❌ Сварщик не найден!")
        base.close()
        return
    
    welder = welders[0]
    print(f"  Сварщик: {welder.telemetry.get('customName', 'unnamed')}")
    print(f"  enabled: {welder.telemetry.get('enabled')}")
    print(f"  working: {welder.telemetry.get('isWorking')}")
    
    print("\n⚡ Включаю сварщик...")
    welder.set_enabled(True)
    time.sleep(2)
    
    welder.update()
    print(f"  enabled: {welder.telemetry.get('enabled')}")
    print(f"  working: {welder.telemetry.get('isWorking')}")
    
    # Ждём ремонта
    print("\n⏳ Ремонт RemoteControl (до 60 сек)...")
    
    # === Дрон ===
    drone = Grid.from_name("taburet3", redis_client=client)
    
    for i in range(60):
        time.sleep(1)
        drone.refresh_devices()
        
        for block in drone.iter_blocks():
            if 'RemoteControl' in str(getattr(block, 'block_type', '')):
                state = block.state or {}
                integrity = state.get('integrity', 0)
                max_int = state.get('maxIntegrity', 1)
                damaged = state.get('damaged', True)
                
                pct = integrity / max_int * 100
                print(f"  Целостность: {integrity:.1f}/{max_int:.0f} ({pct:.0f}%) damaged={damaged}")
                
                if not damaged and pct >= 100:
                    print(f"\n✅ RemoteControl отремонтирован!")
                    
                    # Включаем RC
                    remotes = drone.find_devices_by_type("remote_control")
                    if remotes:
                        remotes[0].enable()
                        time.sleep(1)
                        remotes[0].update()
                        print(f"  enabled: {remotes[0].telemetry.get('enabled')}")
                    
                    drone.close()
                    base.close()
                    client.close()
                    return
                break
    else:
        print("\n⏰ Время вышло!")
        drone.refresh_devices()
        for block in drone.iter_blocks():
            if 'RemoteControl' in str(getattr(block, 'block_type', '')):
                state = block.state or {}
                print(f"  Целостность: {state.get('integrity', 0):.1f}/{state.get('maxIntegrity', 0)}")
    
    drone.close()
    base.close()
    client.close()


if __name__ == "__main__":
    main()
