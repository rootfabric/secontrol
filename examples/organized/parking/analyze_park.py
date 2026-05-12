"""Анализ точки парковки."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    
    # === Дрон (припаркован) ===
    print("📡 Дрон (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    drone_remotes = drone.find_devices_by_type("remote_control")
    drone_pos = None
    if drone_remotes:
        drone_pos = drone_remotes[0].telemetry.get("position", {})
        print(f"  Позиция: x={drone_pos.get('x', 0):.2f}, y={drone_pos.get('y', 0):.2f}, z={drone_pos.get('z', 0):.2f}")
    
    drone_connectors = drone.find_devices_by_type("connector")
    drone_conn_pos = None
    drone_conn_fwd = None
    if drone_connectors:
        dt = drone_connectors[0].telemetry or {}
        drone_conn_pos = dt.get("position", {})
        orientation = dt.get("orientation", {})
        drone_conn_fwd = orientation.get("forward", {})
        print(f"  Коннектор дрона: x={drone_conn_pos.get('x', 0):.2f}, y={drone_conn_pos.get('y', 0):.2f}, z={drone_conn_pos.get('z', 0):.2f}")
        print(f"  Forward дрона: ({drone_conn_fwd.get('x', 0):.3f}, {drone_conn_fwd.get('y', 0):.3f}, {drone_conn_fwd.get('z', 0):.3f})")
    
    drone.close()
    
    # === База ===
    print("\n🏗️ База (DroneBase 2)...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    base_connectors = base.find_devices_by_type("connector")
    base_conn_pos = None
    base_conn_fwd = None
    if base_connectors:
        bt = base_connectors[0].telemetry or {}
        base_conn_pos = bt.get("position", {})
        orientation = bt.get("orientation", {})
        base_conn_fwd = orientation.get("forward", {})
        print(f"  Коннектор базы: x={base_conn_pos.get('x', 0):.2f}, y={base_conn_pos.get('y', 0):.2f}, z={base_conn_pos.get('z', 0):.2f}")
        print(f"  Forward базы: ({base_conn_fwd.get('x', 0):.3f}, {base_conn_fwd.get('y', 0):.3f}, {base_conn_fwd.get('z', 0):.3f})")
    
    base.close()
    
    # === Анализ ===
    if drone_pos and base_conn_pos:
        print("\n📐 Расчёты:")
        
        # Расстояние между центрами
        dx = drone_pos.get('x', 0) - base_conn_pos.get('x', 0)
        dy = drone_pos.get('y', 0) - base_conn_pos.get('y', 0)
        dz = drone_pos.get('z', 0) - base_conn_pos.get('z', 0)
        dist = (dx**2 + dy**2 + dz**2)**0.5
        print(f"  Расстояние центр-к-центру: {dist:.2f}m")
        print(f"  Δx={dx:.2f}, Δy={dy:.2f}, Δz={dz:.2f}")
        
        # Если есть позиции коннекторов — расстояние между ними
        if drone_conn_pos and base_conn_pos:
            cdx = drone_conn_pos.get('x', 0) - base_conn_pos.get('x', 0)
            cdy = drone_conn_pos.get('y', 0) - base_conn_pos.get('y', 0)
            cdz = drone_conn_pos.get('z', 0) - base_conn_pos.get('z', 0)
            conn_dist = (cdx**2 + cdy**2 + cdz**2)**0.5
            print(f"\n  Расстояние коннектор-к-коннектору: {conn_dist:.2f}m")
            print(f"  Δx={cdx:.2f}, Δy={cdy:.2f}, Δz={cdz:.2f}")
            
            # Смещение для парковки (где должен быть дрон относительно коннектора базы)
            if drone_conn_fwd:
                print(f"\n  📍 Формула точки парковки:")
                print(f"  park_x = base_conn_x - base_conn_fwd_x * {conn_dist:.1f}")
                print(f"  park_y = base_conn_y - base_conn_fwd_y * {conn_dist:.1f}")
                print(f"  park_z = base_conn_z - base_conn_fwd_z * {conn_dist:.1f}")
    
    client.close()


if __name__ == "__main__":
    main()
