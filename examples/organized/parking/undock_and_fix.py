"""Отстыковка и проверка RC."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    drone = Grid.from_name("taburet3", redis_client=client)
    
    print("🔓 Отстыковка...")
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        conn = connectors[0]
        print(f"  Текущий статус: {conn.telemetry.get('connectorStatus')}")
        
        # Отстыковываем
        conn.disconnect()
        time.sleep(2)
        conn.update()
        print(f"  Новый статус: {conn.telemetry.get('connectorStatus')}")
    
    print("\n📡 Проверяю RemoteControl...")
    drone.refresh_devices()
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        rc = remotes[0]
        t = rc.telemetry or {}
        print(f"  enabled: {t.get('enabled')}")
        
        # Пробуем включить
        print("\n⚡ Включаю RC...")
        rc.enable()
        time.sleep(1)
        rc.update()
        print(f"  enabled: {rc.telemetry.get('enabled')}")
        
        # Проверяю целостность
        for block in drone.iter_blocks():
            if 'RemoteControl' in str(getattr(block, 'block_type', '')):
                state = block.state or {}
                print(f"\n  🔨 RemoteControl состояние:")
                print(f"    integrity: {state.get('integrity'):.1f}/{state.get('maxIntegrity')}")
                print(f"    damaged: {state.get('damaged')}")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
