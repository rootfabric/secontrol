"""Поиск дрона и его компонентов на DroneBase 2."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("DroneBase 2", redis_client=client)
    
    print(f"Грид: {grid.name}\n")
    
    # Ищем устройства управления
    print("🎮 Устройства управления:")
    for dev_id, dev in grid.devices.items():
        dev_type = type(dev).__name__
        if any(x in dev_type.lower() for x in ['remote', 'cockpit', 'gyro', 'thrust', 'sensor']):
            print(f"  [{dev_id}] {dev_type}")
            if dev.telemetry:
                for k, v in dev.telemetry.items():
                    if k not in ('items', 'load'):
                        print(f"    {k}: {v}")
    
    # Ищем блоки
    print("\n📦 Блоки:")
    for block in grid.iter_blocks():
        bt = str(getattr(block, 'block_type', ''))
        if any(x in bt for x in ['Remote', 'Gyro', 'Thrust', 'Sensor', 'Reactor', 'Battery', 'Connector']):
            state = block.state or {}
            print(f"  {bt}")
            print(f"    state: {state}")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
