"""Пример отслеживания всех гридов игрока."""

from __future__ import annotations

import time

from secontrol.common import resolve_owner_id, resolve_player_id
from secontrol.grids import GridState, Grids
from secontrol.redis_client import RedisEventClient


def describe(state: GridState) -> str:
    name = state.name or "(без имени)"
    return f"{name} [{state.grid_id}]"


def main() -> None:
    client = RedisEventClient()
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)
    grids = Grids(client, owner_id, player_id)

    print("Текущие гриды:")
    current = grids.list()
    if not current:
        print("  (нет гридов)")
    for state in current:
        print("  *", describe(state))

    grids.on_added(lambda state: print("[+] Появился грид:", describe(state)))
    grids.on_updated(lambda state: print("[*] Обновился грид:", describe(state)))
    grids.on_removed(lambda state: print("[-] Исчез грид:", describe(state)))

    print("Ожидаем изменения... Нажмите Ctrl+C для выхода.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Завершение...")
    finally:
        grids.close()
        client.close()


if __name__ == "__main__":
    main()

