"""Тест: 1 км вперёд и 1 км назад с телеметрией.

Usage:
    python scripts/test_1km_back.py --grid skynet-baza0
    python scripts/test_1km_back.py --grid skynet-baza0 --speed 30
"""
from __future__ import annotations

import argparse
import math
import time

from dotenv import load_dotenv
load_dotenv()

from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.tools.navigation_tools import get_orientation, get_world_position


def dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def fmt_pos(p):
    if p is None:
        return "N/A"
    return f"({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f})"


def fly_and_monitor(rc, grid, target, speed, label, timeout=300):
    """Отправить корабль в точку и выводить телеметрию."""
    gps = f"GPS:{label}:{target[0]:.1f}:{target[1]:.1f}:{target[2]:.1f}:"

    rc.enable()
    rc.gyro_control_on()
    rc.thrusters_on()
    rc.dampeners_on()
    time.sleep(0.5)

    rc.set_mode("oneway")
    rc.set_collision_avoidance(False)
    rc.goto(gps, speed=speed, gps_name=label)

    print(f"\n{'='*60}")
    print(f"  {label}: лечу к {fmt_pos(target)}")
    print(f"  Скорость: {speed} m/s")
    print(f"{'='*60}")

    start_time = time.time()
    start_pos = get_world_position(rc)
    last_print = 0

    while time.time() - start_time < timeout:
        time.sleep(2)
        rc.update()
        time.sleep(0.5)

        pos = get_world_position(rc)
        speed_val = float((rc.telemetry or {}).get("speed", 0))
        ap = (rc.telemetry or {}).get("autopilotEnabled", False)
        d = dist3(pos, target) if pos else -1

        elapsed = time.time() - start_time

        if time.time() - last_print >= 3:
            traveled = dist3(pos, start_pos) if pos and start_pos else 0
            print(
                f"  [{elapsed:6.1f}s] pos={fmt_pos(pos)}  "
                f"speed={speed_val:5.1f} m/s  "
                f"dist_to_target={d:7.1f} m  "
                f"traveled={traveled:7.1f} m"
            )
            last_print = time.time()

        if d >= 0 and d < 5.0:
            print(f"\n  Прибыл! dist={d:.1f}m за {elapsed:.1f}s")
            break

        if not ap and d >= 0 and d < 20.0:
            print(f"\n  Автопилот выключился, dist={d:.1f}m")
            break

    rc.disable()
    rc.dampeners_on()
    time.sleep(1)

    final = get_world_position(rc)
    print(f"  Финальная позиция: {fmt_pos(final)}")
    return final


def main():
    parser = argparse.ArgumentParser(description="Тест: 1км вперёд и 1км назад")
    parser.add_argument("--grid", default="skynet-baza0", help="Имя грида")
    parser.add_argument("--speed", type=float, default=20.0, help="Скорость m/s")
    parser.add_argument("--distance", type=float, default=1000.0, help="Дистанция м")
    args = parser.parse_args()

    client = RedisEventClient()
    grid = Grid.from_name(args.grid, redis_client=client)

    rc = grid.get_first_device("remote_control")
    if rc is None:
        print("RemoteControl не найден!")
        grid.close()
        client.close()
        return

    rc.update()
    time.sleep(1)

    start_pos = get_world_position(rc)
    if start_pos is None:
        print("Не могу прочитать позицию корабля!")
        grid.close()
        client.close()
        return

    basis = get_orientation(rc)
    fwd = basis.forward

    target_fwd = (
        start_pos[0] + fwd[0] * args.distance,
        start_pos[1] + fwd[1] * args.distance,
        start_pos[2] + fwd[2] * args.distance,
    )

    print(f"Grid: {args.grid}")
    print(f"Старт: {fmt_pos(start_pos)}")
    print(f"Forward: ({fwd[0]:.3f}, {fwd[1]:.3f}, {fwd[2]:.3f})")
    print(f"Цель вперёд: {fmt_pos(target_fwd)}")
    print(f"Дистанция: {args.distance:.0f}m")

    # --- Вперёд ---
    fly_and_monitor(rc, grid, target_fwd, args.speed, "Forward1km")

    # --- Назад ---
    fly_and_monitor(rc, grid, start_pos, args.speed, "Back1km")

    pos_final = get_world_position(rc)
    drift = dist3(pos_final, start_pos) if pos_final else -1
    print(f"\n{'='*60}")
    print(f"  Тест завершён!")
    print(f"  Старт:  {fmt_pos(start_pos)}")
    print(f"  Финиш:  {fmt_pos(pos_final)}")
    print(f"  Дрифт:  {drift:.1f} m")
    print(f"{'='*60}")

    grid.close()
    client.close()


if __name__ == "__main__":
    main()
