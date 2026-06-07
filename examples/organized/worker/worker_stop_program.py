#!/usr/bin/env python3
"""
Пример остановки программы на воркере через WorkerApiClient.

Сценарий:
    - читает SE_WORKER_INSTANCE_UUID из окружения (или принимает --instance);
    - показывает, что запущено на воркере;
    - останавливает либо все запущенные программы, либо одну (по имени/UUID);
    - проверяет, что после остановки воркер пуст.

Перед запуском:
    export SE_WORKER_INSTANCE_UUID=28f8784e-dbe4-5f5e-b294-c1c87df4b712
    export SE_WORKER_BASE_URL=https://www.outenemy.ru/se/worker-controller   # опционально

Примеры:
    # остановить всё, что запущено
    python worker_stop_program.py --all

    # остановить конкретную программу по имени
    python worker_stop_program.py --program lamp_blink_rover

    # остановить программу по UUID
    python worker_stop_program.py --program baab494e32964742b8fd6d78c700aab9

    # остановить на конкретном инстансе
    python worker_stop_program.py --instance 26ba5aaa-4391-52e0-ae40-1e0a5a77541a --all
"""

from __future__ import annotations

import argparse
import time
from typing import Any, Dict, List, Optional

from dotenv import find_dotenv, load_dotenv

from WorkerApi import WorkerApiClient


load_dotenv(find_dotenv(usecwd=True), override=False)


def find_program_uuid(programs: Dict[str, Any], identifier: str) -> Optional[str]:
    """Найти UUID программы по UUID или по имени (точное совпадение)."""
    items = programs.get("items", []) if isinstance(programs, dict) else []
    for item in items:
        if item.get("uuid") == identifier or item.get("worker_id") == identifier:
            return item.get("uuid") or item.get("worker_id")
    for item in items:
        if item.get("name") == identifier:
            return item.get("uuid") or item.get("worker_id")
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Остановить программу на воркере")
    parser.add_argument(
        "--instance",
        default=None,
        help="UUID инстанса воркера. По умолчанию — SE_WORKER_INSTANCE_UUID из env.",
    )
    parser.add_argument(
        "--program",
        default=None,
        help="Имя или UUID программы, которую нужно остановить. "
        "Если не указан и не задан --all, ничего не делаем.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Остановить все запущенные программы на воркере.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="Сколько секунд подождать после остановки для проверки.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.program and not args.all:
        print("Укажи --program <имя|UUID> или --all.")
        return

    client = WorkerApiClient(instance_uuid=args.instance)
    print(f"Контроллер: {client.root_url}")

    print()
    print("=== Запущенные программы ДО остановки ===")
    running = client.get_running_programs() or {}
    items: List[Dict[str, Any]] = running.get("items", []) or []
    if not items:
        print("  (ничего не запущено — нечего останавливать)")
        return
    for it in items:
        print(
            f"  - {it.get('name')} uuid={it.get('uuid', '?')[:8]}.. "
            f"run_id={it.get('run_id', '?')[:8]} grid={it.get('grid_label')}"
        )

    targets: List[str] = []
    if args.all:
        targets = [it.get("uuid") for it in items if it.get("uuid")]
    else:
        uuid = find_program_uuid(
            {"items": [{"uuid": it.get("uuid"), "name": it.get("name")} for it in items]},
            args.program,
        )
        if not uuid:
            available = [it.get("name") for it in items]
            print(f"Запущенная программа '{args.program}' не найдена. Запущены: {available}")
            return
        targets = [uuid]

    print()
    print(f"=== Остановка ({len(targets)} шт.) ===")
    for uuid in targets:
        ok = client.stop_program(uuid)
        print(f"  stop_program({uuid[:8]}..) -> {ok}")

    time.sleep(args.wait)

    print()
    print("=== Запущенные программы ПОСЛЕ остановки ===")
    running = client.get_running_programs() or {}
    items = running.get("items", []) or []
    if not items:
        print("  (ничего не запущено — OK)")
        return
    for it in items:
        print(
            f"  - {it.get('name')} uuid={it.get('uuid', '?')[:8]}.. "
            f"status={it.get('status')} grid={it.get('grid_label')}"
        )


if __name__ == "__main__":
    main()
