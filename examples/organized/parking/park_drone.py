"""Парковка дрона над коннектором базы."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.devices.remote_control_device import RemoteControlDevice


def main() -> None:
    client = RedisEventClient()
    
    # === Находим позицию коннектора базы ===
    print("🏗️ База (DroneBase 2)...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    base_connectors = base.find_devices_by_type("connector")
    if not base_connectors:
        print("  ❌ Коннектор не найден!")
        base.close()
        return
    
    conn = base_connectors[0]
    conn_pos = conn.telemetry.get("position", {})
    orientation = conn.telemetry.get("orientation", {})
    
    base_x = conn_pos.get("x", 0)
    base_y = conn_pos.get("y", 0)
    base_z = conn_pos.get("z", 0)
    
    print(f"  Коннектор: x={base_x:.1f}, y={base_y:.1f}, z={base_z:.1f}")
    
    # Вектор направления коннектора (куда он смотрит)
    forward = orientation.get("forward", {})
    up = orientation.get("up", {})
    
    fx = forward.get("x", 0)
    fy = forward.get("y", 0)
    fz = forward.get("z", 0)
    
    print(f"  Forward: ({fx:.2f}, {fy:.2f}, {fz:.2f})")
    
    # Позиция для парковки: над коннектором, в направлении куда он смотрит
    # Смещаемся на 3 метра вперёд от коннектора (в сторону куда он смотрит)
    offset = 3.0
    park_x = base_x - fx * offset
    park_y = base_y - fy * offset  
    park_z = base_z - fz * offset
    
    print(f"\n🅿️ Парковка: x={park_x:.1f}, y={park_y:.1f}, z={park_z:.1f}")
    
    base.close()
    
    # === Отправляем дрон ===
    print("\n📡 Дрон (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    remotes = drone.find_devices_by_type("remote_control")
    if not remotes:
        print("  ❌ RemoteControl не найден!")
        drone.close()
        return
    
    remote: RemoteControlDevice = remotes[0]
    cur_pos = remote.telemetry.get("position", {})
    print(f"  Текущая: x={cur_pos.get('x', 0):.0f}, y={cur_pos.get('y', 0):.0f}, z={cur_pos.get('z', 0):.0f}")
    
    # Включаем
    print("\n🚀 Отправляю на парковку...")
    remote.enable()
    remote.gyro_control_on()
    remote.thrusters_on()
    remote.dampeners_on()
    time.sleep(1)
    
    gps_target = f"GPS:ParkOverConnector:{park_x:.6f}:{park_y:.6f}:{park_z:.6f}:"
    remote.goto(gps_target, speed=5.0)
    
    # Мониторим
    drone_start_y = cur_pos.get("y", 0)
    print("\n⏳ Дрон летит на парковку...")
    
    for i in range(120):
        time.sleep(1)
        drone.refresh_devices()
        
        remotes = drone.find_devices_by_type("remote_control")
        if remotes:
            new_pos = remotes[0].telemetry.get("position", {})
            nx = new_pos.get("x", 0)
            ny = new_pos.get("y", 0)
            nz = new_pos.get("z", 0)
            speed = remotes[0].telemetry.get("speed", 0)
            
            dist = ((nx - park_x)**2 + (ny - park_y)**2 + (nz - park_z)**2)**0.5
            
            if dist < 2:
                print(f"\n✅ Дрон на позиции! Расстояние: {dist:.1f}m")
                break
            
            if i % 3 == 0:
                print(f"  ({nx:.0f}, {ny:.0f}, {nz:.0f}) speed={speed:.1f} dist={dist:.1f}m")
    
    # Остановка
    print("\n🛑 Торможу...")
    remote.dampeners_on()
    remote.handbrake_on()
    time.sleep(2)
    
    drone.refresh_devices()
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        final = remotes[0].telemetry.get("position", {})
        print(f"  Финальная: x={final.get('x', 0):.1f}, y={final.get('y', 0):.1f}, z={final.get('z', 0):.1f}")
        dist_final = ((final.get('x', 0) - park_x)**2 + (final.get('y', 0) - park_y)**2 + (final.get('z', 0) - park_z)**2)**0.5
        print(f"  До цели: {dist_final:.1f}m")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
