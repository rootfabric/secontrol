"""Быстрый просмотр гридов с помощью класса :class:`Grids`.

Пример показывает, как подписаться на обновления списка гридов и
использовать новый метод ``search`` для поиска по имени или идентификатору.
"""

from __future__ import annotations

import argparse
import json

from secontrol import Grids, RedisEventClient
from secontrol.common import resolve_owner_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Показать гриды владельца")
    parser.add_argument(
        "-q",
        "--query",
        help="строка для поиска по имени или идентификатору грида",
    )
    args = parser.parse_args()

    owner_id = resolve_owner_id()
    client = RedisEventClient()
    grids = Grids(client, owner_id)

    try:
        matches = grids.search(args.query) if args.query else grids.list()
        if not matches:
            print("Гриды не найдены. Проверьте соединение с Redis и идентификатор владельца.")
            return

        print(f"Найдено {len(matches)} грид(ов) для владельца {owner_id}:")
        for state in matches:
            print(f"- {state.grid_id}: {state.name or '(без имени)'}")

        print("\nПодробные данные:")
        payload = {
            "ownerId": owner_id,
            "query": args.query,
            "grids": [state.info or state.descriptor for state in matches],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    finally:
        grids.close()
        client.close()


if __name__ == "__main__":
    main()
