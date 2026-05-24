#!/usr/bin/env python3
"""
drill_diag.py — диагностика почему Nanobot Drill не добывает.

Пошагово проверяет состояние бура и пробует разные способы запуска.

Usage:
    python drill_diag.py --grid skynet-baza0
    python drill_diag.py --grid skynet-baza0 --target X Y Z
"""

from __future__ import annotations

import argparse
import os
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(THIS_DIR))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice


def show_tel(drill):
    drill.update()
    tel = drill.telemetry or {}
    props = tel.get("properties", {})
    targets = tel.get("drill_possibledrilltargets", [])
    print(f"  OnOff:              {props.get('OnOff')}")
    print(f"  WorkMode:           {props.get('Drill.WorkMode')} ({drill.get_work_mode()})")
    print(f"  ScriptControlled:   {props.get('Drill.ScriptControlled')}")
    print(f"  ShowArea:           {props.get('Drill.ShowArea')}")
    print(f"  CurrentDrillTarget: {props.get('Drill.CurrentDrillTarget')}")
    print(f"  PossibleTargets:    {len(targets)}")
    print(f"  DrillEnabled:       {props.get('Drill.DrillEnabled')}")
    return tel, props, targets


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Nanobot Drill startup")
    parser.add_argument("--grid", required=True, help="Grid name")
    parser.add_argument("--target", nargs=3, type=float, metavar=("X", "Y", "Z"), help="Target world coords")
    args = parser.parse_args()

    grid = Grid.from_name(args.grid)
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("ERROR: No Nanobot Drill found")
        return 1
    drill = drills[0]

    rc_devices = grid.find_devices_by_type(RemoteControlDevice)
    rc = rc_devices[0] if rc_devices else None

    print(f"Drill: {drill.name} (id={drill.device_id})")
    print(f"RC:    {rc.name if rc else 'N/A'} (id={rc.device_id if rc else 'N/A'})")
    print()

    # === Шаг 1: Текущее состояние ===
    print("=== Шаг 1: Текущее состояние ===")
    show_tel(drill)
    print()

    # === Шаг 2: Полный сброс ===
    print("=== Шаг 2: Полный сброс ===")
    drill.set_raw_property("OnOff", False)
    drill.set_raw_property("Drill.ShowArea", False)
    drill.set_raw_property("Drill.AreaOffsetFrontBack", 0)
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetUpDown", 0)
    time.sleep(0.1)
    drill.set_raw_property("Drill.AreaOffsetLeftRight", 0)
    time.sleep(1)
    show_tel(drill)
    print()

    # === Шаг 3: Установка AreaOffset ===
    if args.target:
        target = tuple(args.target)
        print(f"=== Шаг 3: Установка AreaOffset на {target} ===")
        if rc:
            rc.update()
            time.sleep(0.3)
            rc.update()
            tel_rc = rc.telemetry or {}
            rc_pos = tel_rc.get("position", {})
            orient = tel_rc.get("orientation", {})
            if rc_pos and orient:
                fwd = orient["forward"]
                up = orient["up"]
                l = orient.get("left") or {}
                r = orient.get("right") or {}
                if l:
                    lx, ly, lz = l["x"], l["y"], l["z"]
                elif r:
                    lx, ly, lz = -r["x"], -r["y"], -r["z"]
                else:
                    lx = -(fwd["y"] * up["z"] - fwd["z"] * up["y"])
                    ly = -(fwd["z"] * up["x"] - fwd["x"] * up["z"])
                    lz = -(fwd["x"] * up["y"] - fwd["y"] * up["x"])
                dl = (-2.5, 2.5, 5.0)
                dwx = rc_pos["x"] + dl[0]*lx + dl[1]*up["x"] + dl[2]*fwd["x"]
                dwy = rc_pos["y"] + dl[0]*ly + dl[1]*up["y"] + dl[2]*fwd["y"]
                dwz = rc_pos["z"] + dl[0]*lz + dl[1]*up["z"] + dl[2]*fwd["z"]
                import math
                ddx, ddy, ddz = target[0]-dwx, target[1]-dwy, target[2]-dwz
                lf = ddx*fwd["x"] + ddy*fwd["y"] + ddz*fwd["z"]
                lu = ddx*up["x"] + ddy*up["y"] + ddz*up["z"]
                ll = ddx*lx + ddy*ly + ddz*lz
                gv = [ll, lu, lf]
                ofb, oud, olr = gv[1], gv[2], gv[0]
                print(f"  Distance: {math.sqrt(ddx**2+ddy**2+ddz**2):.1f}m")
                drill.set_raw_property("Drill.AreaOffsetFrontBack", round(ofb, 1))
                time.sleep(0.1)
                drill.set_raw_property("Drill.AreaOffsetUpDown", round(oud, 1))
                time.sleep(0.1)
                drill.set_raw_property("Drill.AreaOffsetLeftRight", round(olr, 1))
                time.sleep(0.1)
            else:
                print("  WARNING: No RC telemetry")
        else:
            print("  WARNING: No RC")
    else:
        print("=== Шаг 3: Пропущен (нет --target) ===")
    print()

    # === Шаг 4: Настройка фильтров ===
    print("=== Шаг 4: Настройка фильтров ===")
    drill.set_raw_property("Drill.ScriptControlled", True)
    time.sleep(0.2)
    drill.set_raw_property("Drill.CollectFilter", "Ore")
    time.sleep(0.1)
    drill.set_collect_filter(["Ore"])
    time.sleep(0.2)
    drill.set_ore_filters(["Nickel"], work_mode="Collect")
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", 1)
    time.sleep(0.2)
    drill.set_raw_property("Drill.ScriptControlled", False)
    time.sleep(0.2)
    drill.set_raw_property("Drill.WorkMode", 1)
    time.sleep(0.2)
    print("  Filters set: Nickel, Collect")
    print()

    # === Шаг 5: Включение ===
    print("=== Шаг 5: Включение ===")
    drill.set_raw_property("Drill.ShowArea", True)
    drill.set_raw_property("OnOff", True)
    print("  OnOff=True, ждём 10s для авто-запуска...")
    time.sleep(10)
    tel, props, targets = show_tel(drill)
    print()

    # === Шаг 6: Пробуем Drill_On action ===
    print("=== Шаг 6: Drill_On action ===")
    if props.get("Drill.CurrentDrillTarget") is None:
        print("  CurrentTarget=None — отправляем Drill_On...")
        drill.run_action("Drill_On")
        time.sleep(3)
        tel, props, targets = show_tel(drill)
        if props.get("Drill.CurrentDrillTarget") is not None:
            print("  [OK] Drill_On сработал!")
        else:
            print("  [FAIL] Drill_On не сработал")
    else:
        print("  [OK] Уже работает, CurrentTarget задан")
    print()

    # === Шаг 7: Пробуем Collect_On (если режим Collect) ===
    print("=== Шаг 7: Collect_On action ===")
    if props.get("Drill.CurrentDrillTarget") is None:
        print("  Пробуем Collect_On...")
        drill.run_action("Collect_On")
        time.sleep(3)
        tel, props, targets = show_tel(drill)
        if props.get("Drill.CurrentDrillTarget") is not None:
            print("  ✅ Collect_On сработал!")
        else:
            print("  ❌ Collect_On не сработал")
    else:
        print("  ✅ Уже работает")
    print()

    # === Шаг 8: Проверка контейнеров ===
    print("=== Шаг 8: Содержимое контейнеров ===")
    for item in grid.get_all_grid_items():
        st = item.get("item_subtype", "")
        amt = item.get("amount", 0)
        if amt > 0:
            print(f"  {item.get('display_name', st)}: {amt:.1f}")
    print()

    # === Шаг 9: Мониторинг 60 секунд ===
    if props.get("Drill.CurrentDrillTarget") is not None:
        print("=== Шаг 9: Мониторинг 60s ===")
        baseline = sum(item.get("amount", 0) for item in grid.get_all_grid_items()
                       if "Nickel" in str(item.get("item_subtype", "")))
        for i in range(12):
            time.sleep(5)
            amt = sum(item.get("amount", 0) for item in grid.get_all_grid_items()
                      if "Nickel" in str(item.get("item_subtype", "")))
            delta = amt - baseline
            print(f"  [{i*5+5}s] Nickel: {amt:.1f} (+{delta:.1f})")
            if delta > 0:
                print(f"\n  ✅ Добыча идёт! +{delta:.1f} за {(i+1)*5}s")
                break
        else:
            print("\n  ❌ Добыча не началась за 60s")
    else:
        print("=== Шаг 9: Пропущен (нет активной добычи) ===")

    print()
    print("Done. Если бур не заработал — проверь:")
    print("  1. Корабль на астероиде (surface=0)")
    print("  2. Руда в радиусе ≤1000м")
    print("  3. Мод Nanobot Drill & Fill установлен на сервере")
    print("  4. Другие моды не мешают (например, SpeedMod, PowerMod)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
