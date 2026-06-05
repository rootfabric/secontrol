"""Включить режим парковки после стыковки."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    drone = Grid.from_name("taburet3", redis_client=client)
    
    # Проверяем коннектор
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        conn = connectors[0]
        conn.update()
        status = conn.telemetry.get("connectorStatus", "Unknown")
        print(f"Коннектор: {status}")
        
        if status == "Connected":
            print("\n🅿️ Включаю режим парковки...")
            drone.park_on()
            print("✅ Парковка включена!")
            
            # Выключаю RemoteControl
            remotes = drone.find_devices_by_type("remote_control")
            if remotes:
                remotes[0].disable()
                print("  RemoteControl выключен")
        else:
            print("❌ Не состыкован!")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
