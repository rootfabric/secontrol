"""Проверка генератора через блоки."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()

    grid = Grid.from_name("DroneBase", redis_client=client)
    print(f"Грид: {grid.name}\n")

    # Ищем OxygenGenerator среди блоков
    for block in grid.iter_blocks():
        block_type = getattr(block, 'block_type', '') or ''
        if 'OxygenGenerator' in str(block_type) or 'oxygen' in str(block_type).lower():
            print(f"🔧 OxygenGenerator найден!")
            print(f"  block_id: {block.block_id}")
            print(f"  block_type: {block.block_type}")
            print(f"  state: {block.state}")
            integrity = block.state.get("integrity") if block.state else None
            max_integrity = block.state.get("maxIntegrity") if block.state else None
            build_ratio = block.state.get("buildRatio") if block.state else None
            
            if integrity and max_integrity:
                print(f"  Целостность: {integrity} / {max_integrity} ({integrity/max_integrity*100:.1f}%)")
            if build_ratio is not None:
                print(f"  Построен: {float(build_ratio)*100:.1f}%")

    # Также покажу устройства
    print(f"\n📋 Все устройства:")
    for dev_id, dev in grid.devices.items():
        print(f"  [{dev_id}] {type(dev).__name__} -> telemetry: {dev.telemetry}")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
