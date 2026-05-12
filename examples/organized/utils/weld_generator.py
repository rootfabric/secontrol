"""Включение сварщика и достройка генератора на DroneBase."""
from __future__ import annotations

import time
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()

    print("Подключение к DroneBase...")
    
    try:
        grid = Grid.from_name("DroneBase", redis_client=client)
        print(f"Грид: {grid.name}\n")

        # Ищем сварщик
        welders = grid.find_devices_by_type("ship_welder")
        if not welders:
            print("Сварщик не найден!")
            grid.close()
            return

        welder = welders[0]
        print(f"🔧 Сварчик найден: {type(welder).__name__}")
        
        # Проверяем текущее состояние
        telemetry = welder.telemetry or {}
        state = telemetry.get("state", {})
        enabled = state.get("enabled", telemetry.get("enabled", False))
        working = state.get("working", telemetry.get("working", False))
        
        print(f"  Включён: {'✅' if enabled else '❌'}")
        print(f"  Работает: {'✅' if working else '❌'}")

        if not enabled:
            print("\n⚡ Включаю сварщик...")
            welder.set_enabled(True)
            time.sleep(1)
            
            # Обновляем телеметрию
            grid.refresh_devices()
            # Перенаходим сварщик и генератор после обновления
            welders = grid.find_devices_by_type("ship_welder")
            welder = welders[0]
            state = welder.telemetry.get("state", welder.telemetry) if welder.telemetry else {}
            print(f"  Включён: {'✅' if state.get('enabled') else '❌'}")
            print(f"  Работает: {'✅' if state.get('working') else '❌'}")

        # Ждём пока генератор достроится
        print("\n⏳ Ждём достройку генератора (до 30 сек)...")
        generators = grid.find_devices_by_type("gas_generator")
        if not generators:
            print("Генератор не найден!")
            grid.close()
            return

        gen = generators[0]
        
        for i in range(30):
            time.sleep(1)
            grid.refresh_devices()
            generators = grid.find_devices_by_type("gas_generator")
            gen = generators[0]
            
            state = gen.telemetry or {}
            build_ratio = state.get("buildRatio", state.get("state", {}).get("buildRatio", 0))
            
            print(f"  Построено: {float(build_ratio)*100:.1f}%")
            
            if float(build_ratio) >= 1.0:
                print("\n✅ Генератор полностью построен!")
                break
        else:
            print("\n⏰ Время вышло, проверяю финальный статус...")
            grid.refresh_devices()
            generators = grid.find_devices_by_type("gas_generator")
            gen = generators[0]
            build_ratio = (gen.telemetry or {}).get("buildRatio", 0)
            print(f"  Построено: {float(build_ratio)*100:.1f}%")

        grid.close()
        
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    main()
