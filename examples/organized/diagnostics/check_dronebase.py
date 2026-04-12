"""Проверка состава DroneBase."""
from __future__ import annotations

import os
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def main() -> None:
    client = RedisEventClient()

    print("Подключение к DroneBase...")
    
    try:
        grid = Grid.from_name("DroneBase", redis_client=client)
        print(f"Грид: {grid.name} (ID: {grid.grid_id})")
        print()

        # Получаем список всех устройств через атрибут devices
        devices = list(grid.devices.values())
        
        if not devices:
            print("Устройства не найдены!")
            return

        # Группируем по типам
        by_type: dict[str, list] = {}
        for device in devices:
            device_type = type(device).__name__
            if device_type not in by_type:
                by_type[device_type] = []
            by_type[device_type].append(device)

        print(f"Всего устройств: {len(devices)}")
        print("=" * 70)
        
        for device_type, items in sorted(by_type.items()):
            print(f"\n{device_type}: {len(items)} шт.")
            for item in items:
                name = getattr(item, 'name', None) or getattr(item, 'custom_name', 'unnamed')
                block_id = getattr(item, 'block_id', 'unknown')
                print(f"  - {name} (ID: {block_id})")

        print("\n" + "=" * 70)
        
        # Информация о ресурсах грида
        print("\nРесурсы грида:")
        try:
            resources = grid.get_resources()
            if resources:
                for res_type, amount in sorted(resources.items(), key=lambda x: -x[1]):
                    print(f"  {res_type}: {amount:.1f}")
            else:
                print("  (нет данных о ресурсах)")
        except Exception as e:
            print(f"  (не удалось получить: {e})")

        grid.close()
        
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    main()
