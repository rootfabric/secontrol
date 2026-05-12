import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

from secontrol.redis_client import RedisEventClient

def main():
    # Создаем клиент Redis
    client = RedisEventClient()

    # Ключ для хранения данных
    key = "se:144115188075855919:memory1"

    # Пример данных для записи (словарь с различными типами данных)
    data_to_store = {
        "user_id": 144115188075855919,
        "session_data": {
            "last_login": "2025-01-01T20:00:00Z",
            "preferences": {
                "theme": "dark",
                "language": "ru"
            }
        },
        "counters": {
            "actions_performed": 42,
            "errors_encountered": 3
        },
        "notes": ["Первая заметка", "Вторая заметка"]
    }

    print("Записываем данные в ключ:", key)
    print("Данные:", data_to_store)

    # Записываем данные в Redis
    client.set_json(key, data_to_store)

    print("\nДанные успешно записаны!")

    # Читаем данные из Redis
    print("\nЧитаем данные из ключа:", key)
    retrieved_data = client.get_json(key)

    if retrieved_data is not None:
        print("Прочитанные данные:")
        print(retrieved_data)

        # Проверяем, что данные совпадают
        if retrieved_data == data_to_store:
            print("\nДанные совпадают!")
        else:
            print("\nДанные не совпадают!")
    else:
        print("Не удалось прочитать данные из ключа.")

if __name__ == "__main__":
    main()
