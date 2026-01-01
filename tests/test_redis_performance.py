#!/usr/bin/env python3
"""
Тест производительности Redis: замер времени подключения и чтения ключей.
"""

import time
import os
from secontrol.redis_client import RedisEventClient
from secontrol.common import resolve_owner_id

def test_redis_performance():
    print("=== Redis Performance Test ===")

    # 1. Замер времени подключения
    start_time = time.perf_counter()
    try:
        client = RedisEventClient()
        # Проверка соединения через ping
        client._client.ping()
        connection_time = time.perf_counter() - start_time
        print(f"Время подключения: {connection_time:.4f} сек")
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        return

    # 2. Получение owner_id
    try:
        owner_id = resolve_owner_id()
        print(f"Owner ID: {owner_id}")
    except Exception as e:
        print(f"Ошибка получения owner_id: {e}")
        owner_id = "unknown"

    # 3. Ключи для тестирования
    test_keys = [
        f"se:{owner_id}:grids",
        f"se:{owner_id}:grid:taburet2:gridinfo",  # Замени на актуальный grid_id если нужно
        f"se:{owner_id}:memory",  # Ключ карты, если есть
    ]

    # 4. Замер времени чтения ключей
    total_read_time = 0.0
    results = []

    for key in test_keys:
        start_read = time.perf_counter()
        try:
            value = client.get_json(key)
            read_time = time.perf_counter() - start_read
            total_read_time += read_time
            size = len(str(value)) if value else 0
            print(f"Ключ '{key}': {read_time:.4f} сек, размер ~{size} символов")
            results.append((key, read_time, size))
        except Exception as e:
            read_time = time.perf_counter() - start_read
            print(f"Ключ '{key}': ошибка за {read_time:.4f} сек")
            results.append((key, read_time, 0))

    # 5. Итоги
    print("\n=== Итоги ===")
    print(f"Общее время чтения ключей: {total_read_time:.4f} сек")
    print(f"Среднее время на ключ: {total_read_time / len(results):.4f} сек")
    print(f"Всего ключей протестировано: {len(results)}")

    # Закрытие клиента
    client.close()

if __name__ == "__main__":
    test_redis_performance()
