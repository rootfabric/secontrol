#!/usr/bin/env python3
"""
Пример использования WorkerApiClient:

- Получает список запущенных программ.
- Печатает информацию по программам.
- Для первой программы выводит хвост логов.
"""

from typing import Any, Dict, List

from WorkerApi import WorkerApiClient  # импорт класса из предыдущего файла

from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv(usecwd=True), override=False)



def print_running_programs_info(running_programs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Печатает информацию о запущенных программах в удобочитаемом виде
    и возвращает список программ (items).
    """
    items = running_programs.get("items", []) or []
    count = running_programs.get("count")
    if count is None:
        # если backend не вернул count, берём длину списка
        count = len(items)

    print(f"Найдено запущенных программ: {count}")

    if not items:
        print("В данный момент нет запущенных программ.")
        return []

    print("\nДетали запущенных программ:")
    print("-" * 80)

    for idx, program in enumerate(items, 1):
        name = program.get("name", "N/A")
        uuid = program.get("uuid", program.get("id", "N/A"))
        status = program.get("status", "N/A")
        run_id = program.get("run_id", "N/A")
        grid_id = program.get("grid_id", "N/A")
        grid_label = program.get("grid_label", "N/A")

        print(f"{idx}. Программа: {name}")
        print(f"   UUID: {uuid}")
        print(f"   Статус: {status}")
        print(f"   Run ID: {run_id}")
        print(f"   Grid ID: {grid_id}")
        print(f"   Grid Label: {grid_label}")
        print("-" * 80)

    return items


def main() -> None:
    # UUID инстанса и base_url берутся из окружения:
    #   SE_WORKER_BASE_URL, SE_WORKER_INSTANCE_UUID
    client = WorkerApiClient()

    print(f"Проверяем запущенные программы на воркере: {client.root_url}")

    running = client.get_running_programs()
    if running is None:
        print("Не удалось получить информацию о запущенных программах.")
        return

    items = print_running_programs_info(running)
    if not items:
        return

    # Для примера выводим логи только первой программы
    first_program = items[0]
    program_uuid = first_program.get("uuid") or first_program.get("id")

    if not program_uuid:
        print("Не удалось определить UUID программы для получения логов.")
        return

    print(f"\nПолучаем логи для программы UUID={program_uuid} (хвост 20000 байт)...")
    logs = client.get_program_logs(program_uuid, tail_bytes=20000)
    if logs is None:
        print("Не удалось получить логи программы.")
        return

    print("\n=== Логи программы (хвост) ===")
    print(logs)


if __name__ == "__main__":
    main()
