"""Поиск управления дроном на taburet3."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("taburet3", redis_client=client)
    
    print(f"Грид: {grid.name}\n")
    
    print("📦 Блоки:")
    for block in grid.iter_blocks():
        bt = str(getattr(block, 'block_type', ''))
        state = block.state or {}
        print(f"  {bt}")
        print(f"    state: enabled={state.get('enabled')}, working={state.get('working')}, build={state.get('buildRatio')}")
    
    print("\n🎮 Устройства:")
    for dev_id, dev in grid.devices.items():
        dev_type = type(dev).__name__
        print(f"  [{dev_id}] {dev_type}")
        if dev.telemetry:
            for k, v in dev.telemetry.items():
                if k not in ('items', 'load'):
                    print(f"    {k}: {v}")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
