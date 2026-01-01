#!/usr/bin/env python3
"""
Тест времени создания грида: замер prepare_grid на примере taburet2.
"""

import time
from secontrol.common import prepare_grid, close

def main():
    print("=== Grid Creation Time Test ===")

    # Замер полного времени prepare_grid
    start_time = time.perf_counter()
    try:
        grid = prepare_grid("taburet2")
        total_time = time.perf_counter() - start_time
        print(f"Общее время создания грида: {total_time:.4f} сек")
        print(f"Грид: {grid.name}, устройств: {len(grid.devices)}, блоков: {len(grid.blocks)}")

        # Закрываем грид
        close(grid)
    except Exception as e:
        total_time = time.perf_counter() - start_time
        print(f"Ошибка создания грида за {total_time:.4f} сек: {e}")

if __name__ == "__main__":
    main()
