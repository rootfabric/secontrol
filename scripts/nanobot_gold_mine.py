#!/usr/bin/env python3
"""
Nanobot Drill — автономная добыча золота (skynet-baza0).

Автоматически:
  1. Подключается к гриду
  2. Находит Nanobot Drill и RC
  3. Вычисляет area offset от позиции бура до руды
     (с учётом ориентации бура на корабле!)
  4. Устанавливает зону, фильтр, включает бурение

Использование:
  python scripts/nanobot_gold_mine.py              # полный запуск
  python scripts/nanobot_gold_mine.py --dry-run     # только расчёт
  python scripts/nanobot_gold_mine.py --status      # текущее состояние

Ключевой момент: area offset идёт ОТНОСИТЕЛЬНО осей бура на корабле,
а не мировых координат. Скрипт автоматически трансформирует вектор
"бур→руда" через матрицу ориентации грида.
"""

import sys
import argparse
import time
import numpy as np

sys.path.insert(0, "/workspace/src")

from secontrol.common import prepare_grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

GRID_NAME = "skynet-baza0"

# Координаты руды (мировые, из ore scanner)
# Скрипт автоматически вычисляет area offset от бура до этой точки
ORE_TARGET = {
    "name": "Gold_01",
    "pos": [98932.15, 81370.99, -131207.03],
}

# Фильтр руды (SE ore subtypes)
ORE_FILTER = ["Gold"]

# WorkMode: "drill" (2), "collect" (1), "fill" (0)
WORK_MODE = "drill"

# ============================================================
# ОСИ БУРА НА КОРАБЛЕ (определены эмпирически)
# ============================================================
# Nanobot Drill (SELtdLargeNanobotDrillSystem) на large grid:
#   Bounding box: 0.75 x 0.77 x 4.20м — длинная ось = world Z
#   Grid X → Ship Left   → Drill LeftRight
#   Grid Y → Ship Up     → Drill UpDown
#   Grid Z → Ship Forward → Drill FrontBack
#
# Если бур установлен иначе — поменяйте mapping:
DRILL_AXIS_MAP = {
    "FrontBack":  2,   # grid axis index: 0=X, 1=Y, 2=Z
    "LeftRight":  0,
    "UpDown":     1,
}


# ============================================================
# ЛОГИКА
# ============================================================

def get_ship_rotation_matrix(rc):
    """
    Матрица поворота grid-local → world из RC телеметрии.
    Grid X→Ship Left, Grid Y→Ship Up, Grid Z→Ship Forward.
    """
    orient = rc.telemetry['orientation']
    fwd  = np.array([orient['forward']['x'], orient['forward']['y'], orient['forward']['z']])
    up   = np.array([orient['up']['x'],      orient['up']['y'],      orient['up']['z']])
    left = np.array([orient['left']['x'],    orient['left']['y'],    orient['left']['z']])
    return np.column_stack([left, up, fwd])  # R: grid→world


def compute_drill_offsets(drill_pos_world, ore_pos_world, R):
    """
    Вычисляет area offsets для Nanobot Drill.

    Args:
        drill_pos_world: [x,y,z] позиция бура (мировые)
        ore_pos_world:   [x,y,z] позиция руды (мировые)
        R: матрица поворота grid-local → world

    Returns:
        dict: {"FrontBack": float, "LeftRight": float, "UpDown": float}
    """
    vec_world = np.array(ore_pos_world) - np.array(drill_pos_world)
    vec_local = R.T @ vec_world  # world → grid-local

    return {
        axis: float(vec_local[grid_idx])
        for axis, grid_idx in DRILL_AXIS_MAP.items()
    }


def get_drill_world_position(drill, grid):
    """Позиция бура в мировых координатах (grid pos + relative_to_grid_center)."""
    grid_pos = np.array(grid.metadata['pos'])
    rtc = drill.metadata.extra.get('relative_to_grid_center', [0, 0, 0])
    return grid_pos + np.array(rtc)


def set_drill_config(drill, offsets):
    """Отправляет все команды настройки бура."""

    # Area offsets
    drill.send_command({"cmd": "set", "property": "Drill.AreaOffsetLeftRight",  "value": offsets['LeftRight']})
    drill.send_command({"cmd": "set", "property": "Drill.AreaOffsetUpDown",     "value": offsets['UpDown']})
    drill.send_command({"cmd": "set", "property": "Drill.AreaOffsetFrontBack",  "value": offsets['FrontBack']})

    # Show area on HUD
    drill.send_command({"cmd": "set", "property": "Drill.ShowArea", "value": True})

    # ScriptControlled = False (ОБЯЗАТЕЛЬНО для автономной работы)
    drill.send_command({"cmd": "set", "property": "Drill.ScriptControlled", "value": False})

    # Ore filter
    drill.set_ore_filters(ORE_FILTER)

    # Work mode
    drill.set_work_mode(WORK_MODE)

    # Включить бур
    drill.send_command({"cmd": "set", "property": "OnOff", "value": True})


def show_drill_status(drill):
    """Выводит текущее состояние бура."""
    t = drill.telemetry

    target = t.get('drill_currentdrilltarget', 'None')
    targets = t.get('drill_possibledrilltargets', [])
    gold_targets = [x for x in targets if 'Gold' in str(x)]
    stone_targets = [x for x in targets if 'Stone' in str(x)]

    print(f"  isWorking:          {t.get('isWorking')}")
    print(f"  OnOff:              {t.get('onoff')}")
    print(f"  ScriptControlled:   {t.get('drill_scriptcontrolled')}")
    print(f"  WorkMode:           {t.get('drill_workmode')}")
    print(f"  oreFilterIndices:   {t.get('oreFilterIndices')}")
    print(f"  Area:               {t.get('drill_areawidth')}x{t.get('drill_areaheight')}x{t.get('drill_areadepth')}м")
    print(f"  Offset LR/UD/FB:   {t.get('drill_areaoffsetleftright')} / {t.get('drill_areaoffsetupdown')} / {t.get('drill_areaoffsetfrontback')}")
    print(f"  CurrentDrillTarget: {target}")
    print(f"  Possible targets:   {len(targets)} всего ({len(gold_targets)} Gold, {len(stone_targets)} Stone)")
    print(f"  Volume:             {t.get('currentVolume')}")
    print(f"  Items:              {t.get('items')}")
    return target


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Nanobot Drill — автономная добыча золота")
    parser.add_argument("--dry-run", action="store_true", help="Только расчёт, без команд")
    parser.add_argument("--status", action="store_true", help="Показать текущее состояние")
    args = parser.parse_args()

    print(f"{'='*50}")
    print(f"  Nanobot Gold Mine — {GRID_NAME}")
    print(f"{'='*50}\n")

    # Подключение
    print("[1/4] Подключение к гриду...")
    grid = prepare_grid(GRID_NAME)
    grid.refresh_devices()
    print(f"  ✓ '{grid.metadata['name']}' (ID: {grid.metadata['id']})")

    # Бур
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)
    if not drills:
        print("  ✗ Nanobot Drill не найден!"); sys.exit(1)
    drill = drills[0]
    print(f"  ✓ Бур: {drill.name} (ID: {drill.device_id})")

    # Только статус
    if args.status:
        print(f"\n{'─'*50}")
        print("  Текущее состояние бура:")
        print(f"{'─'*50}")
        show_drill_status(drill)
        return

    # RC
    rcs = grid.find_devices_by_type(RemoteControlDevice)
    if not rcs:
        print("  ✗ Remote Control не найден!"); sys.exit(1)
    rc = rcs[0]

    # Ориентация
    print("[2/4] Ориентация корабля...")
    R = get_ship_rotation_matrix(rc)
    orient = rc.telemetry['orientation']
    fwd = orient['forward']
    print(f"  Forward: [{fwd['x']:.3f}, {fwd['y']:.3f}, {fwd['z']:.3f}]")

    # Позиция бура и руды
    drill_pos = get_drill_world_position(drill, grid)
    ore_pos = ORE_TARGET['pos']
    dist = np.linalg.norm(np.array(ore_pos) - drill_pos)

    print(f"[3/4] Координаты:")
    print(f"  Бур:   [{drill_pos[0]:.1f}, {drill_pos[1]:.1f}, {drill_pos[2]:.1f}]")
    print(f"  Руда:  [{ore_pos[0]:.1f}, {ore_pos[1]:.1f}, {ore_pos[2]:.1f}]")
    print(f"  Расстояние: {dist:.1f}м")

    # Вычисляем offsets
    offsets = compute_drill_offsets(drill_pos, ore_pos, R)
    print(f"\n  Area offsets (drill-local):")
    print(f"    FrontBack:  {offsets['FrontBack']:.1f}м")
    print(f"    LeftRight:  {offsets['LeftRight']:.1f}м")
    print(f"    UpDown:     {offsets['UpDown']:.1f}м")

    offset_vec = np.array([offsets[k] for k in ['LeftRight', 'UpDown', 'FrontBack']])
    print(f"    Сдвиг центра зоны: {np.linalg.norm(offset_vec):.1f}м")

    if args.dry_run:
        print(f"\n{'─'*50}")
        print("[dry-run] Команды не отправлены.")
        return

    # Отправка команд
    print(f"\n[4/4] Настройка и запуск бура...")
    set_drill_config(drill, offsets)
    print(f"  ✓ Offsets, фильтр, режим установлены")

    # Запуск
    time.sleep(0.5)
    drill.start_drilling()
    print(f"  ✓ start_drilling()")

    # Проверка через 3 сек
    time.sleep(3)
    grid.refresh_devices()
    drill2 = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]

    print(f"\n{'─'*50}")
    print("  Результат:")
    print(f"{'─'*50}")
    target = show_drill_status(drill2)

    if target and 'Gold' in str(target):
        print(f"\n  ✅ БУР ДОБЫВАЕТ ЗОЛОТО!")
    elif target and 'Stone' in str(target):
        print(f"\n  ⚠ Бур берёт Stone (Nanobot Drill не блокирует drill-цели фильтром)")
        print(f"    oreFilterIndices=[8] установлен, но плагин берёт ближайшую руду.")
        print(f"    Золото будет добыто когда Stone в зоне закончится.")
    else:
        print(f"\n  ⏳ Бур сканирует зону...")


if __name__ == "__main__":
    main()
