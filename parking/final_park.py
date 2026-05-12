"""Финальная векторная парковка: 10м по forward → плавное снижение → стыковка."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from parking import (
    DockingConfig,
    DockingResult,
    calculate_connector_forward_point_by_name,
    prepare_for_parking,
    finalize_parking,
    final_approach_and_dock,
    try_dock,
    get_connector_status,
    STATUS_CONNECTED,
)
from parking.helpers import (
    _dist, _dot, _sub,
)


def main() -> None:
    client = RedisEventClient()
    
    # === Подключаемся к базе и дрону ===
    print("🏗️ База (DroneBase 2)...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    
    print("\n📡 Дрон (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    
    # === Готовим дрон ===
    prepare_for_parking(drone)
    
    # Получаем устройства
    rc_list = drone.find_devices_by_type("remote_control")
    ship_conn_list = drone.find_devices_by_type("connector")
    base_conn_list = base.find_devices_by_type("connector")
    
    if not rc_list or not ship_conn_list or not base_conn_list:
        print("❌ Не найдены необходимые устройства!")
        drone.close()
        base.close()
        client.close()
        return
    
    rc = rc_list[0]
    ship_conn = ship_conn_list[0]
    base_conn = base_conn_list[0]
    
    config = DockingConfig(base_grid=base, ship_grid=drone)
    
    # === ШАГ 1: Летим на 10м по forward от коннектора базы ===
    print("\n" + "="*60)
    print("📍 ШАГ 1: Полёт на 10м по forward коннектора базы")
    print("="*60)
    
    target_point = calculate_connector_forward_point_by_name(
        "DroneBase 2", distance=10.0, redis_client=client
    )
    
    print(f"🎯 Цель: ({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})")
    
    # Включаем RC
    rc.enable()
    rc.gyro_control_on()
    rc.thrusters_on()
    rc.dampeners_on()
    time.sleep(1)
    
    # Летим к точке
    gps = f"GPS:Approach10m:{target_point[0]:.2f}:{target_point[1]:.2f}:{target_point[2]:.2f}:"
    print(f"✈️ Лечу... GPS: {gps}")
    rc.set_mode("oneway")
    rc.goto(gps, speed=10.0, gps_name="Approach10m")
    
    # Ждём прилёта
    for i in range(120):
        time.sleep(1)
        drone.refresh_devices()
        rc_list = drone.find_devices_by_type("remote_control")
        if rc_list:
            pos = rc_list[0].telemetry.get("position", {})
            dist = _dist(
                (pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)),
                target_point
            )
            if dist < 2:
                print(f"✅ На точке! Расстояние: {dist:.1f}м")
                break
            if i % 5 == 0:
                print(f"  Dist to target: {dist:.1f}m")
    
    time.sleep(2)
    
    # === ШАГ 2: Плавное снижение по forward к коннектору ===
    print("\n" + "="*60)
    print("📍 ШАГ 2: Плавное снижение к коннектору (vector dock)")
    print("="*60)
    
    result = final_approach_and_dock(rc, ship_conn, base_conn, config)

    if result.success:
        print(f"\n✅ Позиционирование успешно: {result.message}")
    else:
        print(f"\n⚠️ Позиционирование: {result.message}")
        print("  Проверяю коннектор...")

    # === ШАГ 3: Проверка статуса коннектора и стыковка ===
    print("\n" + "="*60)
    print("📍 ШАГ 3: Проверка коннектора и стыковка")
    print("="*60)

    # Ждём когда коннектор станет готов к стыковке
    ship_conn.update()
    status = get_connector_status(ship_conn)
    print(f"  Текущий статус: {status}")

    if status == "Connectable":
        print("🔗 Connectable detected! Вызываю connect()...")
        ship_conn.connect()
        time.sleep(1)
        ship_conn.update()
        status = get_connector_status(ship_conn)

    if status == STATUS_CONNECTED:
        print(f"✅ Стыковка успешна! Паркую...")
        
        # Включаем режим парковки ТОЛЬКО для коннекторов (не трогаем трастеры!)
        drone.park(
            enabled=True,
            brake_wheels=True,        # Тормозим колёса
            shutdown_thrusters=False, # НЕ выключаем трастеры!
            lock_connectors=True      # Блокируем коннекторы
        )
        time.sleep(1)
        
        # НЕ выключаем RemoteControl — ручное управление должно работать
        print("  Парковка включена (трастеры работают)")
        print("✅ Парковка завершена!")
    else:
        print(f"⚠️ Коннектор: {status}")
        # Мониторим ещё немного
        print("\n🔍 Мониторю коннектор (до 60 сек)...")
        for i in range(60):
            time.sleep(1)
            ship_conn.update()
            status = get_connector_status(ship_conn)
            
            if status == "Connectable":
                print(f"  🔗 Connectable! Вызываю connect()...")
                ship_conn.connect()
                time.sleep(1)
                ship_conn.update()
                status = get_connector_status(ship_conn)
            
            if status == STATUS_CONNECTED:
                print(f"  ✅ Стыковка! Паркую...")
                drone.park(
                    enabled=True,
                    brake_wheels=True,
                    shutdown_thrusters=False,
                    lock_connectors=True
                )
                time.sleep(1)
                print("    Парковка включена (трастеры работают)")
                print("✅ Парковка завершена!")
                break
            
            if i % 10 == 0:
                print(f"  Статус: {status}")
        else:
            print("\n❌ Не удалось припарковаться")
    
    drone.close()
    base.close()
    client.close()


if __name__ == "__main__":
    main()
