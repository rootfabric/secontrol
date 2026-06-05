"""Финальная стыковка — проверка Connectable и connect()."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    drone = Grid.from_name("taburet3", redis_client=client)
    
    connectors = drone.find_devices_by_type("connector")
    if not connectors:
        print("❌ Коннектор не найден!")
        drone.close()
        client.close()
        return
    
    conn = connectors[0]
    
    # Мониторим статус
    print("⏳ Мониторю статус коннектора...")
    for i in range(60):
        conn.update()
        status = conn.telemetry.get("connectorStatus", "Unknown")
        
        if status == "Connectable":
            print(f"\n✅ STATUS_READY_TO_LOCK detected!")
            print("🔗 Подключаю...")
            conn.connect()
            time.sleep(1)
            conn.update()
            final = conn.telemetry.get("connectorStatus", "Unknown")
            print(f"  Финальный статус: {final}")
            
            if final == "Connected":
                print("✅ Стыковка успешна!")
            else:
                print(f"⚠️ Не удалось состыковать: {final}")
            break
        
        if status == "Connected":
            print(f"\n✅ Уже состыкован!")
            break
        
        if i % 5 == 0:
            print(f"  Статус: {status}")
        
        time.sleep(1)
    else:
        print("\n⏰ Время вышло!")
        conn.update()
        print(f"  Финальный статус: {conn.telemetry.get('connectorStatus', 'Unknown')}")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
