#!/usr/bin/env python3
"""
Пример запуска программы на воркере через WorkerApiClient.

Сценарий:
    - читает SE_WORKER_INSTANCE_UUID из окружения (или принимает --instance);
    - показывает, что уже запущено на воркере;
    - находит программу по имени (или принимает --program-uuid);
    - запускает её с указанным grid_id и читает хвост логов.

Перед запуском:
    export SE_WORKER_INSTANCE_UUID=28f8784e-dbe4-5f5e-b294-c1c87df4b712
    export SE_WORKER_BASE_URL=https://www.outenemy.ru/se/worker-controller   # опционально

Примеры:
    # запуск по имени программы и ID грида
    python worker_run_program.py --program lamp_blink_rover --grid-id 127551744966766463

    # запуск по UUID программы
    python worker_run_program.py --program baab494e32964742b8fd6d78c700aab9

    # запуск с JSON-параметрами
    python worker_run_program.py --program Drone_test --filename example_app_params.py \
        --grid-id 127551744966766463 --params '{"speed": 25, "mode": "patrol"}'

    # запуск с параметрами из файла
    python worker_run_program.py --program Drone_test --filename example_app_params.py \
        --grid-id 127551744966766463 --params-file params.json

    # запуск на конкретном инстансе
    python worker_run_program.py --instance 26ba5aaa-4391-52e0-ae40-1e0a5a77541a \
        --program lamp_blink_rover --grid-id 127551744966766463
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from dotenv import find_dotenv, load_dotenv

from WorkerApi import WorkerApiClient


load_dotenv(find_dotenv(usecwd=True), override=False)


def find_program_uuid(programs: Dict[str, Any], identifier: str) -> Optional[str]:
    """Найти UUID программы по UUID или по имени (точное совпадение)."""
    items = programs.get("items", []) if isinstance(programs, dict) else []
    # Сначала пробуем как UUID
    for item in items:
        if item.get("uuid") == identifier or item.get("worker_id") == identifier:
            return item.get("uuid") or item.get("worker_id")
    # Затем как имя
    for item in items:
        if item.get("name") == identifier:
            return item.get("uuid") or item.get("worker_id")
    return None


def load_params(params_text: Optional[str], params_file: Optional[str]) -> Optional[Dict[str, Any]]:
    """Read launch parameters from --params or --params-file."""
    if params_text and params_file:
        raise ValueError("Use either --params or --params-file, not both")
    raw: Optional[str] = None
    if params_file:
        raw = Path(params_file).read_text(encoding="utf-8")
    elif params_text:
        raw = params_text
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"params must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"params must be a JSON object, got {type(data).__name__}")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Запустить программу на воркере")
    parser.add_argument(
        "--instance",
        default=None,
        help="UUID инстанса воркера. По умолчанию — SE_WORKER_INSTANCE_UUID из env.",
    )
    parser.add_argument(
        "--program",
        required=True,
        help="Имя или UUID программы для запуска.",
    )
    parser.add_argument(
        "--grid-id",
        default=None,
        help="grid_id грида, на котором запускается программа. "
        "Если не указан, контроллер возьмёт grid_id из своего binding.",
    )
    parser.add_argument(
        "--filename",
        default="01_lamp_blink.py",
        help="Имя файла внутри программы. По умолчанию 01_lamp_blink.py.",
    )
    parser.add_argument(
        "--params",
        default=None,
        help="JSON-объект параметров для запуска, например: '{\"speed\": 25, \"mode\": \"patrol\"}'.",
    )
    parser.add_argument(
        "--params-file",
        default=None,
        help="Путь к JSON-файлу с параметрами. Нельзя использовать одновременно с --params.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=4.0,
        help="Сколько секунд подождать после запуска, чтобы прочитать логи.",
    )
    parser.add_argument(
        "--log-tail",
        type=int,
        default=3000,
        help="Сколько последних байт лога прочитать после запуска.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    client = WorkerApiClient(instance_uuid=args.instance)
    print(f"Контроллер: {client.root_url}")
    print(f"Программа:   {args.program}")
    print(f"Grid ID:     {args.grid_id or '(из binding контроллера)'}")
    print(f"Файл:        {args.filename}")
    try:
        run_params = load_params(args.params, args.params_file)
    except ValueError as exc:
        print(f"Ошибка параметров: {exc}")
        return
    print(f"Параметры:   {json.dumps(run_params, ensure_ascii=False) if run_params is not None else '(нет)'}")

    programs = client.get_programs()
    if not programs or "items" not in programs:
        print("Не удалось получить список программ. Прерываю.")
        return
    program_uuid = find_program_uuid(programs, args.program)
    if not program_uuid:
        available = [it.get("name", "?") for it in programs.get("items", [])]
        print(f"Программа '{args.program}' не найдена. Доступные: {available}")
        return
    print(f"Найден UUID программы: {program_uuid}")

    print()
    print("=== Запущенные программы ДО старта ===")
    running = client.get_running_programs() or {}
    items: List[Dict[str, Any]] = running.get("items", []) or []
    if not items:
        print("  (ничего не запущено)")
    for it in items:
        print(f"  - {it.get('name')} run_id={it.get('run_id', '?')[:8]} grid={it.get('grid_label')}")

    print()
    print("=== Запуск ===")
    run = client.run_program(
        program_uuid,
        args.filename,
        grid_id=args.grid_id,
        params=run_params,
    )
    if not run:
        print("Запуск не удался. Подробности см. в логах контроллера.")
        return

    worker = run.get("worker", {}) or {}
    run_info = run.get("run", {}) or {}
    print(f"  worker.name:    {worker.get('name')}")
    print(f"  worker.status:  {worker.get('status')}")
    print(f"  current_grid:   {worker.get('current_grid_label')} ({worker.get('current_grid_id')})")
    print(f"  run_id:         {worker.get('current_run_id') or run_info.get('run_id')}")
    print(f"  started_at:     {run_info.get('started_at')}")
    print(f"  pid:            {run_info.get('pid')}")

    time.sleep(args.wait)

    print()
    print(f"=== Логи (хвост {args.log_tail} байт) ===")
    logs = client.get_program_logs(program_uuid, tail_bytes=args.log_tail)
    if not logs:
        print("  (пусто)")
    else:
        print(logs)

    print()
    print("=== Запущенные программы ПОСЛЕ старта ===")
    running = client.get_running_programs() or {}
    items = running.get("items", []) or []
    if not items:
        print("  (ничего не запущено)")
    for it in items:
        print(f"  - {it.get('name')} run_id={it.get('run_id', '?')[:8]} grid={it.get('grid_label')}")


if __name__ == "__main__":
    main()
