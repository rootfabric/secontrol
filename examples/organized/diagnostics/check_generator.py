"""Проверка состояния газового генератора на DroneBase."""
from __future__ import annotations

from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.devices.gas_generator_device import GasGeneratorDevice


def main() -> None:
    client = RedisEventClient()

    print("Подключение к DroneBase...")
    
    try:
        grid = Grid.from_name("DroneBase", redis_client=client)
        print(f"Грид: {grid.name}\n")

        # Ищем генераторы
        generators = grid.find_devices_by_type("gas_generator")
        
        if not generators:
            print("Газовые генераторы не найдены!")
            grid.close()
            return

        for i, gen in enumerate(generators, 1):
            gen: GasGeneratorDevice
            print(f"{'='*60}")
            print(f"Генератор #{i}")
            print(f"{'='*60}")
            
            print(f"\n📊 Состояние:")
            func = gen.functional_status()
            print(f"  Включён:         {'✅ Да' if func['enabled'] else '❌ Нет'}")
            print(f"  Функционален:    {'✅ Да' if func['isFunctional'] else '❌ Нет'}")
            print(f"  Работает:        {'✅ Да' if func['isWorking'] else '❌ Нет'}")
            
            print(f"\n⛽ Производительность:")
            print(f"  Текущая выработка: {gen.current_output():.1f}")
            print(f"  Макс. выработка:   {gen.max_output():.1f}")
            print(f"  Ёмкость:           {gen.production_capacity():.1f}")
            print(f"  Заполненность:     {gen.fill_ratio()*100:.1f}%")
            
            print(f"\n⚙️ Настройки:")
            print(f"  Конвейер:   {'✅ Да' if gen.use_conveyor() else '❌ Нет'}")
            print(f"  Авто-дозаправ: {'✅ Да' if gen.auto_refill() else '❌ Нет'}")
            
            print(f"\n📦 Инвентарь:")
            inventory = gen.get_inventory()
            if inventory:
                for item in inventory:
                    print(f"  - {item.get('name', 'unknown')}: {item.get('amount', 0):.1f}")
            else:
                print("  (пусто)")
            
            # Сырьё в генераторе
            print(f"\n🔧 Сырьё:")
            materials = gen.get_materials()
            if materials:
                for mat, amount in materials.items():
                    print(f"  - {mat}: {amount:.1f}")
            else:
                print("  (нет данных)")

        grid.close()
        
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    main()
