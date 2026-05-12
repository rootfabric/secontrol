"""Поиск taburet2 на DroneBase 2."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    grid = Grid.from_name("DroneBase 2", redis_client=client)
    
    print(f"Грид: {grid.name} (ID: {grid.grid_id})\n")
    
    # Смотрю коннекторы — они показывают connected grid
    connectors = grid.find_devices_by_type("connector")
    for conn in connectors:
        print(f"🔌 Коннектор: {type(conn).__name__}")
        telemetry = conn.telemetry or {}
        print(f"  connected: {telemetry.get('connectorIsConnected')}")
        print(f"  status: {telemetry.get('connectorStatus')}")
        print(f"  other_grid_id: {telemetry.get('otherConnectorGridId')}")
        print(f"  other_name: {telemetry.get('otherConnectorName')}")
    
    # Смотрю подключенные субгриды
    print(f"\n📋 Субгриды:")
    for block in grid.iter_blocks():
        block_type = str(getattr(block, 'block_type', ''))
        if 'OxygenGenerator' in block_type:
            state = block.state or {}
            print(f"  {block.block_type}: buildRatio={state.get('buildRatio')}")
    
    grid.close()
    client.close()


if __name__ == "__main__":
    main()
