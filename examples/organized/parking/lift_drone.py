"""Подъём дрона на 1 км над базой."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.devices.remote_control_device import RemoteControlDevice


def main() -> None:
    client = RedisEventClient()
    
    # === Дрон (taburet3) ===
    print("📡 Подключение к дрону (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    # Находим RemoteControl
    remotes = drone.find_devices_by_type("remote_control")
    if not remotes:
        print("❌ RemoteControl не найден!")
        drone.close()
        return
    
    remote: RemoteControlDevice = remotes[0]
    print(f"  RemoteControl: {remote.telemetry.get('customName', 'unnamed')}")
    
    # Текущая позиция
    pos = remote.telemetry.get("position", {})
    current_x = pos.get("x", 0)
    current_y = pos.get("y", 0)
    current_z = pos.get("z", 0)
    print(f"  Позиция: x={current_x:.0f}, y={current_y:.0f}, z={current_z:.0f}")
    
    # === Отключаем коннектор ===
    print("\n🔌 Отключаю коннектор...")
    connectors = drone.find_devices_by_type("connector")
    if connectors:
        conn = connectors[0]
        result = conn.send_command({"cmd": "disconnect"})
        print(f"  Результат disconnect: {result}")
        time.sleep(2)
    
    # === Включаем RemoteControl и гироскоп ===
    print("\n🎮 Включаю RemoteControl...")
    remote.enable()
    remote.gyro_control_on()
    remote.thrusters_on()
    remote.dampeners_on()
    time.sleep(1)
    
    # === Подъём вверх ===
    target_y = current_y + 1000
    print(f"  Текущая Y: {current_y:.0f}")
    print(f"  Целевая Y: {target_y:.0f}")
    print(f"\n🚀 Поднимаю дрон...")
    
    # Отправляем команду goto на координату выше
    gps_target = f"GPS:TargetUp:{current_x:.6f}:{target_y:.6f}:{current_z:.6f}:"
    print(f"  GPS цель: {gps_target}")
    
    remote.goto(gps_target, speed=15.0)
    
    # Мониторим позицию
    print("\n⏳ Мониторю подъём...")
    for i in range(180):
        time.sleep(1)
        drone.refresh_devices()
        
        remotes = drone.find_devices_by_type("remote_control")
        if remotes:
            new_pos = remotes[0].telemetry.get("position", {})
            new_y = new_pos.get("y", current_y)
            speed = remotes[0].telemetry.get("speed", 0)
            dist = new_y - current_y
            
            pct = min(dist / 1000 * 100, 100)
            bar_len = int(pct / 5)
            bar = "█" * min(bar_len, 20) + "░" * max(0, 20 - bar_len)
            print(f"  [{bar}] Y={new_y:.0f} (+{dist:.0f}m / 1000m)  speed={speed:.1f} m/s")
            
            if new_y >= target_y - 5:
                print(f"\n✅ Дрон на целевой высоте!")
                break
    
    # Остановка
    print("\n🛑 Остановка...")
    remote.disable()
    remote.dampeners_on()
    remote.handbrake_on()
    
    time.sleep(2)
    drone.refresh_devices()
    remotes = drone.find_devices_by_type("remote_control")
    if remotes:
        final_pos = remotes[0].telemetry.get("position", {})
        print(f"  Финальная Y: {final_pos.get('y', 0):.0f}")
    
    drone.close()
    client.close()


if __name__ == "__main__":
    main()
