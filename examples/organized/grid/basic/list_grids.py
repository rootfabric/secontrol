"""Краткий список гридов владельца.

Выводит по одной строке на грид: имя, id, тип (static/mobile),
количество блоков и позицию.
"""

from __future__ import annotations

from secontrol import Grids, RedisEventClient
from secontrol.common import resolve_owner_id


def _grid_type(info: dict) -> str:
    for key in ("isStatic", "gridIsStatic"):
        val = info.get(key)
        if isinstance(val, bool):
            return "static" if val else "mobile"
        if isinstance(val, (int, float)):
            return "static" if val else "mobile"
    return "unknown"


def _block_count(info: dict) -> int:
    blocks = info.get("blocks")
    if isinstance(blocks, list):
        return len(blocks)
    return 0


def _position(info: dict) -> str:
    for key in ("pos", "worldPosition", "position", "Position"):
        pos = info.get(key)
        if isinstance(pos, (list, tuple)) and len(pos) >= 3:
            try:
                return f"{float(pos[0]):.1f}, {float(pos[1]):.1f}, {float(pos[2]):.1f}"
            except (TypeError, ValueError):
                continue
        if isinstance(pos, dict) and all(k in pos for k in ("x", "y", "z")):
            try:
                return f"{float(pos['x']):.1f}, {float(pos['y']):.1f}, {float(pos['z']):.1f}"
            except (TypeError, ValueError):
                continue
    return "-"


def main() -> None:
    owner_id = resolve_owner_id()
    client = RedisEventClient()
    grids = Grids(client, owner_id)

    try:
        states = grids.list()
        if not states:
            print("Гриды не найдены. Проверьте соединение с Redis и owner_id.")
            return

        print(f"Найдено {len(states)} грид(ов) для владельца {owner_id}:")
        for state in states:
            info = state.info or state.descriptor or {}
            name = state.name or f"Grid_{state.grid_id}"
            grid_type = _grid_type(info)
            blocks = _block_count(info)
            pos = _position(info)
            print(f"- {name} (id={state.grid_id}) [{grid_type}, {blocks} blocks] @ {pos}")
    finally:
        grids.close()
        client.close()


if __name__ == "__main__":
    main()
