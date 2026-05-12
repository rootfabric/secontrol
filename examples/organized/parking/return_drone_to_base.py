"""Проверка дрона и возврат на базу."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.devices.remote_control_device import RemoteControlDevice


def main() -> None:
    client = RedisEventClient()
    
    # === Проверяем дрон ===
    print("📡 Дрон (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        pos = remotes[0].telemetry.get("position", {})
        speed = remotes[0].telemetry.get("speed", 0)
        print(f"  Позиция: x={pos.get('x', 0):.0f}, y={pos.get('y', 0):.0f}, z={pos.get('z', 0):.0f}")
        print(f"  Скорость: {speed:.1f} m/s")
        drone_y = pos.get("y", 0)
    else:
        print("  ❌ RemoteControl не найден")
        drone.close()
        return
    
    # Проверяю повреждения
    damaged = []
    for block in drone.iter_blocks():
        state = block.state or {}
        integrity = state.get("integrity", 0)
        max_int = state.get("maxIntegrity", 1)
        if integrity < max_int:
            damaged.append((str(getattr(block, 'block_type', '')), integrity, max_int))
    
    if damaged:
        print(f"\n⚠️ Повреждения ({len(damaged)} блоков):")
        for bt, integ, max_i in damaged[:5]:
            print(f"  {bt}: {integ:.0f}/{max_i:.0f} ({integ/max_i*100:.0f}%)")
    
    # === Проверяем базу ===
    print("\n🏗️ База (DroneBase 2)...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    # Позиция коннектора базы
    base_connectors = base.find_devices_by_type("connector")
    if base_connectors:
        base_pos = base_connectors[0].telemetry.get("position", {})
        print(f"  Коннектор базы: x={base_pos.get('x', 0):.0f}, y={base_pos.get('y', 0):.0f}, z={base_pos.get('z', 0):.0f}")
        base_x = base_pos.get("x", 0)
        base_y = base_pos.get("y", 0)
        base_z = base_pos.get("z", 0)
    else:
        print("  ❌ Коннектор базы не найден")
        base_x, base_y, base_z = 0, 0, 0
    
    base.close()
    
    # === Возвращаем дрон ===
    print("\n🔄 Возврат дрона на базу...")
    remote: RemoteControlDevice = remotes[0]
    
    # Включаем
    print("  Включаю системы...")
    remote.enable()
    remote.gyro_control_on()
    remote.thrusters_on()
    remote.dampeners_on()
    time.sleep(1)
    
    # Летим к коннектору базы (чуть выше для стыковки)
    target_x = base_x
    target_y = base_y + 3  # Чуть выше коннектора
    target_z = base_z
    
    print(f"  Цель: x={target_x:.0f}, y={target_y:.0f}, z={target_z:.0f}")
    
    gps_target = f"GPS:ReturnToBase:{target_x:.6f}:{target_y:.6f}:{target_z:.6f}:"
    remote.goto(gps_target, speed=10.0)
    
    # Мониторим
    print("\n⏳ Дрон летит домой...")
    for i in range(180):
        time.sleep(1)
        drone.refresh_devices()
        
        remotes = drone.find_devices_by_type("remote_control")
        if remotes:
            new_pos = remotes[0].telemetry.get("position", {})
            new_y = new_pos.get("y", drone_y)
            speed = remotes[0].telemetry.get("speed", 0)
            
            dist_to_base = ((new_pos.get("x", 0) - base_x)**2 + 
                          (new_pos.get("y", 0) - base_y)**2 + 
                          (new_pos.get("z", 0) - base_z)**2)**0.5
            
            if dist_to_base < 10:
                print(f"\n✅ Дрон вернулся на базу! Расстояние: {dist_to_base:.1f}m")
                break
            
            if i % 5 == 0:
                print(f"  Y={new_y:.0f}, speed={speed:.1f} m/s, dist_to_base={dist_to_base:.0f}m")
    else:
        print("\n⏰ Время вышло!")
    
    # Остановка и стыковка
    print("\n🛑 Остановка...")
    remote.dampeners_on()
    remote.handbrake_on()
    time.sleep(1)
    
    # Проверяем коннектор
    drone.refresh_devices()
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        status = connectors[0].telemetry.get("connectorStatus", "Unknown")
        print(f"  Коннектор: {status}")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
