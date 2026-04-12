"""Проверка статуса постройки генератора."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()

    print("Подключение к DroneBase...")
    
    try:
        grid = Grid.from_name("DroneBase", redis_client=client)
        print(f"Грид: {grid.name}\n")

        generators = grid.find_devices_by_type("gas_generator")
        
        if not generators:
            print("Газовые генераторы не найдены!")
            grid.close()
            return

        for i, gen in enumerate(generators, 1):
            print(f"{'='*60}")
            print(f"Генератор #{i}")
            print(f"{'='*60}")
            
            # Вся сырая телеметрия
            telemetry = gen.telemetry or {}
            print(f"\n📋 Полная телеметрия:")
            for key, value in sorted(telemetry.items()):
                print(f"  {key}: {value}")
            
            # Проверяем build level / integrity
            print(f"\n🔨 Статус постройки:")
            build_level = telemetry.get("buildLevelRatio", telemetry.get("buildRatio", telemetry.get("integrity")))
            if build_level is not None:
                print(f"  Построен на: {float(build_level)*100:.1f}%")
            else:
                print("  (данных о постройке нет)")

            # Проверяем subgrid_id / parent (может быть частью проектора)
            subgrid = telemetry.get("subGridId", telemetry.get("isProjected"))
            if subgrid:
                print(f"  Проекция/субгрид: {subgrid}")

        grid.close()
        
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    main()
