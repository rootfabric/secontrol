#!/usr/bin/env python3
"""
Пример использования команд park и power для грида.

Этот скрипт демонстрирует, как активировать режим парковки и изменять режим питания грида.
"""

import time
from secontrol import prepare_grid

def main():
    # Получаем первый доступный грид
    grid = prepare_grid()

    print(f"Работаем с гридом: {grid.name} (ID: {grid.grid_id})")



    # Пример 1: Активация режима парковки
    # print("\n=== Активация режима парковки ===")
    result = grid.park(
        enabled=True,
        brake_wheels=True,
        shutdown_thrusters=True,
        lock_connectors=True
    )
    # print(f"Команда park отправлена: {result} сообщений")
    #
    # # Ждем немного
    # time.sleep(2)
    result = grid.power("on")

    time.sleep(4)

    # Пример 2: Изменение режима питания на "soft_off"
    print("\n=== Изменение режима питания на soft_off ===")
    result = grid.power("soft_off")
    # result = grid.power("hard_off")
    print(f"Команда power отправлена: {result} сообщений")

    time.sleep(10)

    # Ждем немного
    time.sleep(2)
    #
    # # Пример 4: Включение питания
    # print("\n=== Включение питания ===")
    result = grid.power("on")
    # print(f"Команда power отправлена: {result} сообщений")
    #

    time.sleep(2)

    # # Пример 3: Деактивация режима парковки
    # print("\n=== Деактивация режима парковки ===")
    # result = grid.park(
    #     enabled=False,
    #     brake_wheels=False,
    #     shutdown_thrusters=False,
    #     lock_connectors=False
    # )
    # print(f"Команда park отправлена: {result} сообщений")

    print("\nПример завершен.")



if __name__ == "__main__":
    main()
