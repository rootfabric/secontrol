"""Временный скрипт для проверки доступных гридов."""
from __future__ import annotations

from secontrol.redis_client import RedisEventClient
from secontrol.grids import Grids


def main() -> None:
    client = RedisEventClient()
    
    # Пробуем получить owner_id из REDIS_USERNAME
    import os
    owner_id = os.getenv("REDIS_USERNAME")
    if not owner_id:
        print("Ошибка: REDIS_USERNAME не установлен!")
        print("Установите переменную окружения: set REDIS_USERNAME=ваш_id")
        return

    print(f"Подключение к Redis... (owner_id: {owner_id})")
    
    try:
        # Получаем список гридов
        grids = client.list_grids(owner_id, exclude_subgrids=False)
        
        if not grids:
            print("\nГриды не найдены!")
            print("Убедитесь что:")
            print("  - Игра запущена")
            print("  - Redis-мост работает")
            print("  - REDIS_USERNAME правильный")
            return

        print(f"\nНайдено гридов: {len(grids)}")
        print("-" * 60)
        
        for i, g in enumerate(grids, 1):
            grid_id = g.get("id", "unknown")
            grid_name = g.get("name", "unnamed")
            print(f"{i}. {grid_name} (ID: {grid_id})")
        
        print("-" * 60)
        print("\nДля фильтрации суб-гридов используйте exclude_subgrids=True")
        
    except Exception as e:
        print(f"\nОшибка: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
