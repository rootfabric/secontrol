"""Отправить дрон на 10м по вектору forward от коннектора базы."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()
    
    # === База ===
    print("🏗️ DroneBase 2...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    base_conn = base.find_devices_by_type("connector")[0]
    base_pos = base_conn.telemetry.get("position", {})
    base_orient = base_conn.telemetry.get("orientation", {})
    base_fwd = base_orient.get("forward", {})
    
    base_x = base_pos.get("x", 0)
    base_y = base_pos.get("y", 0)
    base_z = base_pos.get("z", 0)
    
    fwd_x = base_fwd.get("x", 0)
    fwd_y = base_fwd.get("y", 0)
    fwd_z = base_fwd.get("z", 0)
    
    print(f"  Коннектор базы: ({base_x:.2f}, {base_y:.2f}, {base_z:.2f})")
    print(f"  Forward: ({fwd_x:.3f}, {fwd_y:.3f}, {fwd_z:.3f})")
    
    # Точка 10м по forward от коннектора базы
    dist = 10.0
    target_x = base_x + fwd_x * dist
    target_y = base_y + fwd_y * dist
    target_z = base_z + fwd_z * dist
    
    print(f"\n🎯 Точка 10м по forward: ({target_x:.2f}, {target_y:.2f}, {target_z:.2f})")
    
    base.close()
    
    # === Дрон ===
    print("\n📡 taburet3...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    remotes = drone.find_devices_by_type("remote_control")
    if not remotes:
        print("  ❌ RemoteControl не найден!")
        drone.close()
        client.close()
        return
    
    rc = remotes[0]
    rc_pos = rc.telemetry.get("position", {})
    print(f"  RC текущая: ({rc_pos.get('x', 0):.1f}, {rc_pos.get('y', 0):.1f}, {rc_pos.get('z', 0):.1f})")
    
    # Включаем
    print("\n🚀 Включаю системы...")
    rc.enable()
    rc.gyro_control_on()
    rc.thrusters_on()
    rc.dampeners_on()
    time.sleep(1)
    
    # Отправляем по forward вектору
    print(f"\n✈️ Лечу к точке: ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")
    
    gps = f"GPS:Forward10m:{target_x:.2f}:{target_y:.2f}:{target_z:.2f}:"
    print(f"  GPS: {gps}")
    
    rc.set_mode("oneway")
    rc.goto(gps, speed=5.0, gps_name="Forward10m")
    
    # Мониторю
    print("\n⏳ Дрон летит...")
    start_y = rc_pos.get("y", 0)
    
    for i in range(120):
        time.sleep(1)
        drone.refresh_devices()
        
        remotes = drone.find_devices_by_type("remote_control")
        if remotes:
            pos = remotes[0].telemetry.get("position", {})
            cx = pos.get("x", 0)
            cy = pos.get("y", 0)
            cz = pos.get("z", 0)
            speed = remotes[0].telemetry.get("speed", 0)
            
            import math
            dist_to_target = math.sqrt((cx-target_x)**2 + (cy-target_y)**2 + (cz-target_z)**2)
            
            if dist_to_target < 2:
                print(f"\n✅ Дрон на точке! Расстояние: {dist_to_target:.1f}м")
                break
            
            if i % 3 == 0:
                print(f"  ({cx:.0f}, {cy:.0f}, {cz:.0f}) speed={speed:.1f} dist={dist_to_target:.1f}m")
    
    # Остановка
    print("\n🛑 Торможу...")
    rc.dampeners_on()
    rc.handbrake_on()
    
    time.sleep(2)
    drone.refresh_devices()
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        final = remotes[0].telemetry.get("position", {})
        print(f"  Финальная: ({final.get('x', 0):.1f}, {final.get('y', 0):.1f}, {final.get('z', 0):.1f})")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
