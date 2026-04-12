"""Отстыковка дрона и тест новой логики парковки."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    drone = Grid.from_name("taburet3", redis_client=client)
    
    # Проверяю коннектор
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        conn = connectors[0]
        status = conn.telemetry.get("connectorStatus", "Unknown")
        print(f"Коннектор: {status}")
        
        if status == "Connected":
            print("Отстыковываю...")
            conn.disconnect()
            time.sleep(2)
            conn.update()
            new_status = conn.telemetry.get("connectorStatus", "Unknown")
            print(f"Новый статус: {new_status}")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
