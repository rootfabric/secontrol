"""Проверка состояния дрона."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    
    print("📡 Подключение к дрону (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    # RemoteControl
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        pos = remotes[0].telemetry.get("position", {})
        speed = remotes[0].telemetry.get("speed", 0)
        print(f"  Позиция: x={pos.get('x', 0):.0f}, y={pos.get('y', 0):.0f}, z={pos.get('z', 0):.0f}")
        print(f"  Скорость: {speed:.1f} m/s")
    
    # Коннектор
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        conn = connectors[0].telemetry or {}
        print(f"  Коннектор: {conn.get('connectorStatus')}")
        print(f"  Подключён к: {conn.get('otherConnectorGridId')}")
    
    # Проверяю блоки на повреждения
    print("\n🔨 Блоки:")
    for block in drone.iter_blocks():
        state = block.state or {}
        integrity = state.get("integrity", 0)
        max_int = state.get("maxIntegrity", 1)
        if integrity < max_int:
            bt = str(getattr(block, 'block_type', ''))
            print(f"  ⚠️ {bt}: {integrity:.0f}/{max_int:.0f} ({integrity/max_int*100:.0f}%)")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
