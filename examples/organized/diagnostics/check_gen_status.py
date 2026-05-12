"""Проверка состояния газогенератора через фреймворк."""
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

        generators = grid.find_devices_by_type("gas_generator")
        
        if not generators:
            print("Газовые генераторы не найдены!")
            grid.close()
            return

        gen = generators[0]
        
        print(f"{'='*60}")
        print(f"Газогенератор")
        print(f"{'='*60}")
        
        # Целостность и постройка
        print(f"\n🔨 Целостность:")
        build_ratio = (gen.telemetry or {}).get("buildRatio", 0)
        state = gen.telemetry or {}
        integrity = state.get("integrity", state.get("state", {}).get("integrity", "N/A"))
        max_integrity = state.get("maxIntegrity", state.get("state", {}).get("maxIntegrity", "N/A"))
        
        print(f"  Построен:     {float(build_ratio)*100:.1f}%")
        print(f"  Целостность:  {integrity} / {max_integrity}")
        
        func = gen.functional_status()
        print(f"\n📊 Состояние:")
        print(f"  Включён:      {'✅ Да' if func['enabled'] else '❌ Нет'}")
        print(f"  Функционален: {'✅ Да' if func['isFunctional'] else '❌ Нет'}")
        print(f"  Работает:     {'✅ Да' if func['isWorking'] else '❌ Нет'}")
        
        print(f"\n⛽ Производительность:")
        print(f"  Текущая выработка: {gen.current_output():.1f}")
        print(f"  Макс. выработка:   {gen.max_output():.1f}")
        print(f"  Заполненность:     {gen.fill_ratio()*100:.1f}%")

        grid.close()
        
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    main()
