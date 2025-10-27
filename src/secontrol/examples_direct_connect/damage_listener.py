"""Пример подписки на события урона для выбранного грида."""

from __future__ import annotations

import json
import time
from typing import Any

from secontrol import DamageEvent, close, prepare_grid


def _format_block(event: DamageEvent) -> str:
    if event.block is None:
        return "неизвестный блок"
    name = event.block.name or event.block.block_type
    if name:
        return f"{name} ({event.block.block_id})"
    return str(event.block.block_id)


def _format_attacker(event: DamageEvent) -> str:
    attacker = event.attacker
    parts = [
        part
        for part in (
            attacker.name,
            attacker.type,
            f"entity {attacker.entity_id}" if attacker.entity_id is not None else None,
        )
        if part
    ]
    return parts[0] if parts else "неизвестный источник"


def handle_event(payload: DamageEvent | dict[str, Any] | str) -> None:
    if isinstance(payload, DamageEvent):
        block = _format_block(payload)
        attacker = _format_attacker(payload)
        deformation = " (деформация)" if payload.damage.is_deformation else ""
        print(
            f"[{payload.timestamp}] {block}: -{payload.damage.amount:.2f} HP от {payload.damage.damage_type}"
            f" (атакующий: {attacker}){deformation}"
        )
    elif isinstance(payload, dict):
        print("[damage] необработанный словарь:", json.dumps(payload, ensure_ascii=False))
    else:
        print("[damage] необработанные данные:", payload)


def main() -> None:
    grid = prepare_grid()
    subscription = grid.subscribe_to_damage(handle_event)
    print(
        "Ожидаем события урона для грида",
        f"{grid.grid_id} ({grid.name})",
        "— нажмите Ctrl+C для выхода.",
    )
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Остановка по запросу пользователя…")
    finally:
        try:
            subscription.close()
        except Exception:
            pass
        close(grid)
if __name__ == "__main__":
    main()
