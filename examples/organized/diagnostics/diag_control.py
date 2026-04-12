"""Диагностика ручного управления."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    drone = Grid.from_name("taburet3", redis_client=client)
    
    print("📊 Диагностика состояния дрона...\n")
    
    # RemoteControl
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        rc = remotes[0]
        t = rc.telemetry or {}
        print(f"🎮 RemoteControl:")
        print(f"  enabled: {t.get('enabled', 'N/A')}")
        print(f"  autopilotEnabled: {t.get('autopilotEnabled', 'N/A')}")
        print(f"  dampeners: {t.get('dampeners', 'N/A')}")
        print(f"  isUnderControl: {t.get('isUnderControl', 'N/A')}")
        print(f"  canControlShip: {t.get('canControlShip', 'N/A')}")
        print(f"  handBrake: {t.get('handBrake', 'N/A')}")
    
    # Коннектор
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        conn = connectors[0]
        conn.update()
        status = conn.telemetry.get("connectorStatus", "Unknown")
        print(f"\n🔌 Коннектор: {status}")
        if status == "Connected":
            print("  ⚠️ Состыкован — ручное управление может быть заблокировано!")
    
    # Гироскоп
    gyros = drone.find_devices_by_type("gyro")
    if gyros:
        gyro = gyros[0]
        t = gyro.telemetry or {}
        print(f"\n🔄 Гироскоп:")
        print(f"  enabled: {t.get('enabled', 'N/A')}")
        print(f"  override: {t.get('override', 'N/A')}")
        print(f"  power: {t.get('power', 'N/A')}")
    
    # Трастеры
    thrusters = drone.find_devices_by_type("thruster")
    if thrusters:
        active = sum(1 for t in thrusters if (t.telemetry or {}).get("enabled"))
        print(f"\n🔥 Трастеры: {active}/{len(thrusters)} включены")
    
    # Парковка
    print(f"\n🅿️ Парковка:")
    print(f"  is_subgrid: {drone.is_subgrid}")
    
    # Блоки
    print(f"\n🔨 Состояние ключевых блоков:")
    for block in drone.iter_blocks():
        bt = str(getattr(block, 'block_type', ''))
        if 'Remote' in bt or 'Gyro' in bt or 'Thrust' in bt or 'Connector' in bt:
            state = block.state or {}
            print(f"  {bt}: enabled={state.get('enabled')}, working={state.get('working')}")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
