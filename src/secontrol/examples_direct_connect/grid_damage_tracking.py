#!/usr/bin/env python3
"""
Короткий пример отслеживания повреждений в Space Engineers через secontrol.
"""

import time
from secontrol import DamageEvent, close, prepare_grid


def on_damage(event: DamageEvent) -> None:
    """Обработчик событий повреждений."""
    if event.block:
        block_name = event.block.name or f"Блок #{event.block.block_id}"
        attacker_name = event.attacker.name or "Неизвестный"
        deformation = " (деформация)" if event.damage.is_deformation else ""

        print(f"💥 {block_name}: -{event.damage.amount:.1f} HP от {event.damage.damage_type}")
        print(f"   Атакующий: {attacker_name}{deformation}")
        print()


def main():
    """Основная функция."""
    # Получаем грид (автоматически выбирает первый доступный)
    grid = prepare_grid()

    print(f"🎯 Отслеживаем повреждения грида: {grid.name} (ID: {grid.grid_id})")
    print("Нажмите Ctrl+C для выхода...\n")

    # Подписываемся на события повреждений
    subscription = grid.subscribe_to_damage(on_damage)

    try:
        # Бесконечный цикл ожидания
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n🛑 Остановка отслеживания...")
    finally:
        # Корректно закрываем соединения
        subscription.close()
        close(grid)


if __name__ == "__main__":
    main()
