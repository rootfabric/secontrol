"""Диагностика сварщика."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()

    print("Подключение к DroneBase...")
    
    try:
        grid = Grid.from_name("DroneBase", redis_client=client)
        print(f"Грид: {grid.name}\n")

        welders = grid.find_devices_by_type("ship_welder")
        if not welders:
            print("Сварщик не найден!")
            grid.close()
            return

        welder = welders[0]
        print(f"🔧 Сварщик: {type(welder).__name__}")
        print(f"  block_id: {welder.block_id}")
        print(f"  telemetry: {welder.telemetry}")
        print(f"\n  welding_multiplier: {welder.welding_multiplier()}")
        print(f"  weld_speed_multiplier: {welder.weld_speed_multiplier()}")
        print(f"  help_others: {welder.help_others()}")
        print(f"  show_area: {welder.show_area()}")

        # Проверяем инвентарь сварщика
        print(f"\n📦 Инвентарь сварщика:")
        if hasattr(welder, 'get_inventory'):
            inv = welder.get_inventory()
            if inv:
                for item in inv:
                    print(f"  - {item}")
            else:
                print("  (пусто)")
        
        # Проверяем есть ли металлические пластины в контейнерах
        print(f"\n📦 Контейнеры на гриде:")
        containers = grid.find_devices_containers()
        for c in containers:
            print(f"  - {type(c).__name__}")
            if hasattr(c, 'get_inventory'):
                inv = c.get_inventory()
                if inv:
                    for item in inv:
                        print(f"    {item}")
                else:
                    print(f"    (пусто)")

        grid.close()
        
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    main()
