"""Диагностика позиции коннектора и векторов."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from parking.helpers import _parse_vector, _normalize, _sub, _add, _scale


def main() -> None:
    client = RedisEventClient()
    
    # === База ===
    print("🏗️ DroneBase 2...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    base_conn = base.find_devices_by_type("connector")[0]
    base_pos = base_conn.telemetry.get("position", {})
    base_orient = base_conn.telemetry.get("orientation", {})
    base_fwd_raw = base_orient.get("forward", {})
    base_up_raw = base_orient.get("up", {})
    
    base_x = base_pos.get("x", 0)
    base_y = base_pos.get("y", 0)
    base_z = base_pos.get("z", 0)
    base_fwd = _parse_vector(base_fwd_raw)
    base_up = _parse_vector(base_up_raw)
    
    print(f"  Позиция коннектора: ({base_x:.2f}, {base_y:.2f}, {base_z:.2f})")
    print(f"  Forward (raw): ({base_fwd_raw.get('x', 0):.3f}, {base_fwd_raw.get('y', 0):.3f}, {base_fwd_raw.get('z', 0):.3f})")
    print(f"  Up (raw):      ({base_up_raw.get('x', 0):.3f}, {base_up_raw.get('y', 0):.3f}, {base_up_raw.get('z', 0):.3f})")
    
    if base_fwd:
        print(f"  Forward (norm): ({base_fwd[0]:.3f}, {base_fwd[1]:.3f}, {base_fwd[2]:.3f})")
        print(f"  -Forward (UP):  ({-base_fwd[0]:.3f}, {-base_fwd[1]:.3f}, {-base_fwd[2]:.3f})")
    
    base.close()
    
    # === Дрон ===
    print("\n📡 taburet3...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    drone_conn = drone.find_devices_by_type("connector")[0]
    drone_pos = drone_conn.telemetry.get("position", {})
    drone_orient = drone_conn.telemetry.get("orientation", {})
    drone_fwd_raw = drone_orient.get("forward", {})
    
    drone_x = drone_pos.get("x", 0)
    drone_y = drone_pos.get("y", 0)
    drone_z = drone_pos.get("z", 0)
    
    print(f"  Позиция коннектора: ({drone_x:.2f}, {drone_y:.2f}, {drone_z:.2f})")
    print(f"  Forward (raw): ({drone_fwd_raw.get('x', 0):.3f}, {drone_fwd_raw.get('y', 0):.3f}, {drone_fwd_raw.get('z', 0):.3f})")
    
    drone.close()
    
    # === Расчёты ===
    if base_fwd:
        print("\n📐 Расчёт точек:")
        
        # Точка 5м "вверх" по -forward
        up5_x = base_x - base_fwd[0] * 5
        up5_y = base_y - base_fwd[1] * 5
        up5_z = base_z - base_fwd[2] * 5
        print(f"\n  5м ВВЕРХ (-forward): ({up5_x:.2f}, {up5_y:.2f}, {up5_z:.2f})")
        print(f"  ΔY от базы: {-base_fwd[1] * 5:.2f}м")
        
        # Точка 5м СТРОГО по вертикали (Y)
        print(f"\n  5м СТРОГО ВВЕРХ (Y+5): ({base_x:.2f}, {base_y + 5:.2f}, {base_z:.2f})")
        
        # Расстояние между коннекторами
        if drone_fwd_raw:
            dx = drone_x - base_x
            dy = drone_y - base_y
            dz = drone_z - base_z
            import math
            dist = math.sqrt(dx**2 + dy**2 + dz**2)
            print(f"\n  Расстояние коннектор-к-коннектору: {dist:.2f}м")
            print(f"  Δx={dx:.2f}, Δy={dy:.2f}, Δz={dz:.2f}")
    
    # === Показываю блоки на базе вокруг коннектора ===
    print("\n🔍 Блоки на базе рядом с коннектором:")
    for block in base.iter_blocks():
        bt = str(getattr(block, 'block_type', ''))
        if 'SolarPanel' in bt or 'Landing' in bt or 'Armor' in bt:
            state = block.state or {}
            print(f"  {bt}")
            print(f"    relative: {block.relative_to_grid_center}")
    
    client.close()


if __name__ == "__main__":
    main()
