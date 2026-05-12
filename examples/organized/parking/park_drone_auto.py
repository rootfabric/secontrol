"""Парковка дрона на DroneBase 2.

Использует модуль parking для автоматической стыковки.
"""

from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from parking import (
    DockingConfig,
    dock_procedure,
    prepare_for_parking,
    finalize_parking,
    undock_ship,
)


def main() -> None:
    client = RedisEventClient()
    
    # === Подключаемся к базе и дрону ===
    print("🏗️ База (DroneBase 2)...")
    base = Grid.from_name("DroneBase 2", redis_client=client)
    print(f"  Найдена: {base.name}")
    
    print("\n📡 Дрон (taburet3)...")
    drone = Grid.from_name("taburet3", redis_client=client)
    print(f"  Найден: {drone.name}")
    
    # === Готовим к парковке ===
    if not prepare_for_parking(drone):
        print("❌ Подготовка не удалась!")
        drone.close()
        base.close()
        client.close()
        return
    
    # === Запускаем стыковку ===
    print("\n🚀 Запуск процедуры стыковки...")
    
    config = DockingConfig(
        base_grid=base,
        ship_grid=drone,
        approach_distance=5.0,    # Дистанция подхода
        fine_distance=1.5,        # Дистанция точной стыковки
        dock_speed=1.0,           # Скорость стыковки
        approach_speed=10.0,      # Скорость подхода
        max_steps=10,             # Макс шагов подползания
        success_tolerance=0.6,    # Допуск успешной стыковки
    )
    
    result = dock_procedure(base, drone, config)
    
    if result.success:
        print(f"\n✅ Стыковка успешна: {result.message}")
        
        # Финализация
        finalize_result = finalize_parking(drone, base, auto_park=True)
        print(f"  Финализация: {finalize_result.message}")
    else:
        print(f"\n❌ Стыковка не удалась: {result.error or result.message}")
        print(f"  Финальная позиция: {result.final_position}")
        print(f"  Шагов: {result.steps_taken}")
    
    # Закрываем
    drone.close()
    base.close()
    client.close()


if __name__ == "__main__":
    main()
