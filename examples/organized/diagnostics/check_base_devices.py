"""Список устройств на DroneBase 2."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    print(f"🏗️ {base.name}\n")
    
    print("📦 Устройства:")
    for dev_id, dev in base.devices.items():
        t = dev.telemetry or {}
        print(f"  [{dev_id}] {type(dev).__name__}: {t.get('customName', t.get('name', 'unnamed'))}")
    
    print("\n🔨 Блоки:")
    for block in base.iter_blocks():
        bt = str(getattr(block, 'block_type', ''))
        if 'Welder' in bt or 'Nanobot' in bt or 'Repair' in bt:
            state = block.state or {}
            print(f"  {bt}")
            print(f"    enabled: {state.get('enabled')}, working: {state.get('working')}")
    
    base.close()
    client.close()


if __name__ == "__main__":
    main()
