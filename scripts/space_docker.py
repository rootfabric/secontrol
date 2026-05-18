#!/usr/bin/env python3
"""
Space Docker v3 — автономная стыковка корабля к базе в космосе.

Алгоритм:
  1. Найти коннекторы, рассчитать позиции и ориентации
  2. Разворот корабля: coarse yaw (фиксированная скорость) + fine P-controller
  3. Подлёт к approach точке (50м перед коннектором базы) через RC goto
  4. Финальное сближение: RC goto с dock=True (SE сам выровняет коннекторы)
  5. Lock коннекторов

Usage:
    python3 space_docker.py --base skynet-farpost0 --ship skynet-baza2
    python3 space_docker.py --base skynet-farpost0 --ship skynet-baza2 --dry-run
"""

from __future__ import annotations

import argparse
import math
import os
import time
from typing import Optional, Tuple

WORKSPACE = "/workspace"
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import close, prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.tools.navigation_tools import (
    fly_to_point,
    get_world_position,
    get_orientation,
    _dist,
    _dot,
    _normalize,
    _cross,
    _length,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def find_connector_on_grid(grid, conn_id=None):
    connectors = grid.find_devices_by_type(ConnectorDevice)
    if not connectors:
        raise RuntimeError(f"Коннекторы не найдены на {grid.name}")
    if conn_id:
        for c in connectors:
            if str(c.device_id) == str(conn_id):
                return c
        raise RuntimeError(f"Коннектор {conn_id} не найден на {grid.name}")
    return connectors[0]


def get_conn_state(conn):
    conn.update()
    tel = conn.telemetry or {}
    pos_raw = tel.get("worldPosition") or tel.get("position")
    if not pos_raw:
        raise RuntimeError(f"Нет позиции коннектора {conn.device_id}")
    pos = (float(pos_raw["x"]), float(pos_raw["y"]), float(pos_raw["z"]))
    ori = tel.get("orientation") or {}
    fwd_r = ori.get("forward", {})
    up_r = ori.get("up", {})
    fwd = (float(fwd_r.get("x", 0)), float(fwd_r.get("y", 0)), float(fwd_r.get("z", 0)))
    up = (float(up_r.get("x", 0)), float(up_r.get("y", 0)), float(up_r.get("z", 0)))
    return pos, fwd, up, tel.get("connectorIsConnected", False)


def get_rc_pos(rc):
    rc.update()
    return get_world_position(rc)


def get_speed(rc):
    vel = (rc.telemetry or {}).get("linearVelocity") or {}
    return math.sqrt(
        float(vel.get("x", 0)) ** 2 + float(vel.get("y", 0)) ** 2 + float(vel.get("z", 0)) ** 2
    )


# ── Orientation ──────────────────────────────────────────────────────────

def coarse_turn(grid, desired_fwd, timeout=30.0):
    """
    Грубый разворот: фиксированная скорость вращения по yaw.
    Работает для больших углов (>45°), где P-controller oscillирует.
    """
    rc = grid.get_first_device(RemoteControlDevice)
    gyros = grid.find_devices_by_type(GyroDevice)
    if not rc or not gyros:
        return False

    desired_fwd = _normalize(desired_fwd)
    for g in gyros:
        g.enable()

    start = time.time()
    aligned = False

    try:
        while time.time() - start < timeout:
            rc.update()
            try:
                basis = get_orientation(rc)
            except RuntimeError:
                time.sleep(0.1)
                continue

            dot_fwd = max(-1.0, min(1.0, _dot(basis.forward, desired_fwd)))
            angle = math.acos(dot_fwd)

            if angle < math.radians(15):
                aligned = True
                print(f"  [COARSE] ✅ {math.degrees(angle):.1f}°")
                break

            # Определяем направление вращения
            cross = _cross(basis.forward, desired_fwd)
            # Проекция на up корабля — определяет yaw direction
            yaw_dir = _dot(cross, basis.up)
            yaw_sign = 1.0 if yaw_dir > 0 else -1.0

            # Фиксированная скорость вращения (быстрее при большом угле)
            rate = min(1.0, 0.3 + angle / math.pi * 0.7)

            pitch_cmd = 0.0
            # Если угол > 90°, нужен pitch тоже
            if angle > math.radians(90):
                local_y = _dot(desired_fwd, basis.up)
                pitch_cmd = max(-0.5, min(0.5, -local_y * 0.5))

            for g in gyros:
                g.set_override(pitch=pitch_cmd, yaw=yaw_sign * rate, roll=0.0)

            if int(time.time() - start) % 3 == 0:
                print(f"  [COARSE] {math.degrees(angle):.1f}° yaw={yaw_sign * rate:.2f}")

            time.sleep(0.1)
    finally:
        for g in gyros:
            g.clear_override()

    return aligned


def fine_align(grid, desired_fwd, desired_up, timeout=20.0, tolerance_deg=5.0):
    """Тонкая подстройка ориентации P-controller."""
    rc = grid.get_first_device(RemoteControlDevice)
    gyros = grid.find_devices_by_type(GyroDevice)
    if not rc or not gyros:
        return False

    desired_fwd = _normalize(desired_fwd)
    desired_up = _normalize(desired_up)
    tolerance = math.radians(tolerance_deg)
    gain = 2.0
    max_rate = 0.8

    for g in gyros:
        g.enable()

    start = time.time()
    aligned = False

    try:
        while time.time() - start < timeout:
            rc.update()
            try:
                basis = get_orientation(rc)
            except RuntimeError:
                time.sleep(0.1)
                continue

            dot_fwd = max(-1.0, min(1.0, _dot(basis.forward, desired_fwd)))
            angle_fwd = math.acos(dot_fwd)
            dot_up = max(-1.0, min(1.0, _dot(basis.up, desired_up)))
            angle_up = math.acos(dot_up)

            if angle_fwd < tolerance and angle_up < tolerance:
                aligned = True
                print(f"  [FINE] ✅ fwd={math.degrees(angle_fwd):.1f}° up={math.degrees(angle_up):.1f}°")
                break

            local_y = _dot(desired_fwd, basis.up)
            local_x = _dot(desired_fwd, basis.right)
            local_up_x = _dot(desired_up, basis.right)

            pitch_cmd = max(-max_rate, min(max_rate, -local_y * gain))
            yaw_cmd = max(-max_rate, min(max_rate, -local_x * gain))
            roll_cmd = max(-max_rate * 0.3, min(max_rate * 0.3, local_up_x * gain * 0.3))

            for g in gyros:
                g.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)

            if int(time.time() - start) % 2 == 0:
                print(f"  [FINE] fwd={math.degrees(angle_fwd):.1f}° up={math.degrees(angle_up):.1f}°")

            time.sleep(0.1)
    finally:
        for g in gyros:
            g.clear_override()

    return aligned


def orientation_correction_during_flight(grid, desired_fwd, desired_up, gain=1.5, max_rate=0.5):
    """Одиночный шаг коррекции ориентации (вызывать в цикле полёта)."""
    rc = grid.get_first_device(RemoteControlDevice)
    gyros = grid.find_devices_by_type(GyroDevice)
    if not rc or not gyros:
        return

    try:
        basis = get_orientation(rc)
        local_y = _dot(desired_fwd, basis.up)
        local_x = _dot(desired_fwd, basis.right)
        local_up_x = _dot(desired_up, basis.right)

        pitch_cmd = max(-max_rate, min(max_rate, -local_y * gain))
        yaw_cmd = max(-max_rate, min(max_rate, -local_x * gain))
        roll_cmd = max(-max_rate * 0.3, min(max_rate * 0.3, local_up_x * gain * 0.3))

        for g in gyros:
            g.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=roll_cmd)
    except RuntimeError:
        pass


def clear_gyros(grid):
    for g in grid.find_devices_by_type(GyroDevice):
        g.clear_override()


# ── Flight ───────────────────────────────────────────────────────────────

def fly_to_approach(rc, grid, target, desired_fwd, desired_up, speed, arrival_dist, timeout):
    """Подлёт к точке с коррекцией ориентации."""
    gps = f"GPS:Approach:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    rc.enable()
    rc.gyro_control_on()
    rc.thrusters_on()
    rc.dampeners_on()
    time.sleep(1)

    rc.set_mode("oneway")
    rc.set_collision_avoidance(False)
    rc.goto(gps, speed=speed, gps_name="Approach")

    for _ in range(20):
        time.sleep(0.2)
        rc.update()
        if (rc.telemetry or {}).get("autopilotEnabled"):
            break

    start = time.time()
    arrived = False

    try:
        while time.time() - start < timeout:
            orientation_correction_during_flight(grid, desired_fwd, desired_up)

            pos = get_rc_pos(rc)
            if not pos:
                time.sleep(0.3)
                continue

            dist = _dist(pos, target)
            if dist < arrival_dist:
                arrived = True
                print(f"  [APPROACH] ✅ dist={dist:.1f}m")
                break

            if int((time.time() - start) * 2) % 10 == 0:
                spd = get_speed(rc)
                print(f"  [APPROACH] dist={dist:.1f}m speed={spd:.1f}m/s")

            # Проверяем не остановился ли автопилот
            if not (rc.telemetry or {}).get("autopilotEnabled"):
                if dist < arrival_dist * 2:
                    break
                # Перезапуск
                rc.goto(gps, speed=speed, gps_name="Approach")
                time.sleep(1)

            time.sleep(0.3)
    finally:
        clear_gyros(grid)

    return arrived


def fly_to_dock(rc, grid, target, desired_fwd, desired_up, ship_conn, speed, timeout):
    """Финальное сближение с dock=True. RC goto + connector monitoring."""
    gps = f"GPS:Dock:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    rc.enable()
    rc.gyro_control_on()
    rc.thrusters_on()
    rc.dampeners_on()
    time.sleep(1)

    rc.set_mode("oneway")
    rc.set_collision_avoidance(False)
    # dock=True — SE autopilot будет выравнивать коннектор
    rc.goto(gps, speed=speed, gps_name="Dock", dock=True)

    for _ in range(20):
        time.sleep(0.2)
        rc.update()
        if (rc.telemetry or {}).get("autopilotEnabled"):
            break

    start = time.time()
    connected = False
    arrived = False

    try:
        while time.time() - start < timeout:
            # Check connector
            ship_conn.update()
            c_tel = ship_conn.telemetry or {}
            if c_tel.get("connectorIsConnected"):
                connected = True
                print("  [DOCK] ✅ Коннектор подключился!")
                break

            # Orientation correction (мягче)
            orientation_correction_during_flight(grid, desired_fwd, desired_up, gain=1.0, max_rate=0.3)

            pos = get_rc_pos(rc)
            conn_raw = (c_tel.get("worldPosition") or c_tel.get("position"))
            conn_pos = (float(conn_raw["x"]), float(conn_raw["y"]), float(conn_raw["z"])) if conn_raw else None

            if pos:
                dist = _dist(pos, target)
                if dist < 3.0:
                    arrived = True

            if conn_pos:
                conn_dist = _dist(conn_pos, target)
                if int((time.time() - start) * 2) % 10 == 0:
                    print(f"  [DOCK] conn_dist={conn_dist:.1f}m")

            if not (rc.telemetry or {}).get("autopilotEnabled"):
                if arrived:
                    break
                rc.goto(gps, speed=speed, gps_name="Dock", dock=True)
                time.sleep(1)

            time.sleep(0.3)
    finally:
        clear_gyros(grid)

    return connected, arrived


def lock_connectors(ship_conn, base_conn):
    print("  [LOCK] Попытка фиксации...")
    ship_conn.update()
    tel = ship_conn.telemetry or {}
    print(f"  [LOCK] Status: {tel.get('connectorStatus')}")
    print(f"  [LOCK] Nearby: {tel.get('nearbyConnectors')}")

    if tel.get("connectorIsConnected"):
        print("  [LOCK] ✅ Уже подключены!")
        return True

    try:
        ship_conn.set_state(locked=True)
        time.sleep(1)
        ship_conn.update()
        if (ship_conn.telemetry or {}).get("connectorIsConnected"):
            print("  [LOCK] ✅ Подключены после lock!")
            return True
    except Exception as e:
        print(f"  [LOCK] lock error: {e}")

    try:
        ship_conn.connect()
        time.sleep(1)
        ship_conn.update()
        if (ship_conn.telemetry or {}).get("connectorIsConnected"):
            print("  [LOCK] ✅ Подключены после connect!")
            return True
    except Exception as e:
        print(f"  [LOCK] connect error: {e}")

    return False


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Space Docker v3")
    parser.add_argument("--base", required=True)
    parser.add_argument("--ship", required=True)
    parser.add_argument("--base-conn", default=None)
    parser.add_argument("--ship-conn", default=None)
    parser.add_argument("--approach-dist", type=float, default=50.0)
    parser.add_argument("--approach-speed", type=float, default=10.0)
    parser.add_argument("--final-speed", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  SPACE DOCKER v3")
    print("=" * 60)

    base_grid = ship_grid = None

    try:
        # 1. Connect
        print("\n[1/6] Подключение...")
        base_grid = prepare_grid(args.base)
        ship_grid = prepare_grid(args.ship)
        print(f"  База: {base_grid.name}")
        print(f"  Корабль: {ship_grid.name}")

        # 2. Find connectors
        print("\n[2/6] Коннекторы...")
        base_conn = find_connector_on_grid(base_grid, args.base_conn)
        ship_conn = find_connector_on_grid(ship_grid, args.ship_conn)

        # 3. Positions
        print("\n[3/6] Позиции...")
        base_pos, base_fwd, base_up, _ = get_conn_state(base_conn)
        ship_pos, ship_fwd, ship_up, _ = get_conn_state(ship_conn)
        current_dist = _dist(base_pos, ship_pos)

        rc = ship_grid.get_first_device(RemoteControlDevice)
        if not rc:
            raise RuntimeError("RC не найден!")
        rc_pos = get_rc_pos(rc)
        rc_offset = tuple(r - s for r, s in zip(rc_pos, ship_pos))

        print(f"  База:   ({base_pos[0]:.0f}, {base_pos[1]:.0f}, {base_pos[2]:.0f})")
        print(f"  Ship:   ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
        print(f"  Dist:   {current_dist:.0f}m")
        print(f"  RC offset: ({rc_offset[0]:.1f}, {rc_offset[1]:.1f}, {rc_offset[2]:.1f})")

        # 4. Calculate
        print("\n[4/6] Расчёт...")
        desired_fwd = _normalize((-base_fwd[0], -base_fwd[1], -base_fwd[2]))
        desired_up = _normalize(base_up)

        approach_point = tuple(b + d * args.approach_dist for b, d in zip(base_pos, desired_fwd))
        final_point = tuple(b + d * 2.5 for b, d in zip(base_pos, desired_fwd))
        approach_rc = tuple(a + o for a, o in zip(approach_point, rc_offset))
        final_rc = tuple(f + o for f, o in zip(final_point, rc_offset))

        angle_between = math.acos(max(-1, min(1, _dot(ship_fwd, desired_fwd))))
        print(f"  Угол поворота: {math.degrees(angle_between):.0f}°")
        print(f"  Approach: ({approach_point[0]:.0f}, {approach_point[1]:.0f}, {approach_point[2]:.0f})")
        print(f"  Final:    ({final_point[0]:.0f}, {final_point[1]:.0f}, {final_point[2]:.0f})")
        print(f"  RC→approach: {_dist(rc_pos, approach_rc):.0f}m")
        print(f"  RC→final:    {_dist(rc_pos, final_rc):.0f}m")

        if args.dry_run:
            print("\n[DRY RUN] Готово.")
            return

        # 5. Coarse turn
        print(f"\n[5/6] Разворот ({math.degrees(angle_between):.0f}°)...")
        if angle_between > math.radians(20):
            coarse_turn(ship_grid, desired_fwd, timeout=30.0)
        fine_align(ship_grid, desired_fwd, desired_up, timeout=15.0, tolerance_deg=10.0)

        # 6. Fly to approach
        print(f"\n[6/6] Полёт к базе...")
        rc.update()
        rc_pos = get_rc_pos(rc)
        dist_to_approach = _dist(rc_pos, approach_rc)

        if dist_to_approach > 10:
            print(f"  Phase 1: Approach ({args.approach_speed}m/s, {dist_to_approach:.0f}m)...")
            fly_to_approach(
                rc, ship_grid, approach_rc,
                desired_fwd, desired_up,
                speed=args.approach_speed,
                arrival_dist=5.0,
                timeout=120.0,
            )

            rc.disable()
            rc.dampeners_on()
            time.sleep(2)

        # Check position
        ship_conn.update()
        conn_pos_now = (lambda t: (float(t["x"]), float(t["y"]), float(t["z"])) if t else None)(
            (ship_conn.telemetry or {}).get("worldPosition") or (ship_conn.telemetry or {}).get("position")
        )
        if conn_pos_now:
            print(f"  Коннектор: ({conn_pos_now[0]:.0f}, {conn_pos_now[1]:.0f}, {conn_pos_now[2]:.0f})")
            print(f"  До базы: {_dist(conn_pos_now, base_pos):.0f}m")

        # Phase 2: Final with dock=True
        print(f"  Phase 2: Dock ({args.final_speed}m/s)...")
        connected, arrived = fly_to_dock(
            rc, ship_grid, final_rc,
            desired_fwd, desired_up,
            ship_conn,
            speed=args.final_speed,
            timeout=90.0,
        )

        # Stop
        rc.disable()
        rc.dampeners_on()
        time.sleep(1)

        # Lock
        if not connected:
            connected = lock_connectors(ship_conn, base_conn)

        # Final status
        ship_conn.update()
        final_tel = ship_conn.telemetry or {}
        final_raw = final_tel.get("worldPosition") or final_tel.get("position")
        if final_raw:
            fp = (float(final_raw["x"]), float(final_raw["y"]), float(final_raw["z"]))
            print(f"\n  Финальная позиция коннектора: ({fp[0]:.0f}, {fp[1]:.0f}, {fp[2]:.0f})")
            print(f"  Расстояние до базы: {_dist(fp, base_pos):.1f}m")

        if connected:
            print("\n" + "=" * 60)
            print("  ✅ СТЫКОВКА УСПЕШНА!")
            print("=" * 60)
        else:
            print("\n  ⚠️ Стыковка не удалась. Попробуйте вручную.")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if base_grid:
            close(base_grid)
        if ship_grid:
            close(ship_grid)


if __name__ == "__main__":
    main()
