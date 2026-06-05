"""Показать что может произвести грид — все чертежи всех конструкторов.

Использование:
    python examples/organized/assembler/basic/grid_production.py --grid farpost0
    python examples/organized/assembler/basic/grid_production.py --grid farpost0 --full
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


CATEGORIES = {
    "Компоненты": [
        "SteelPlate", "InteriorPlate", "SmallTube", "LargeTube",
        "MotorComponent", "ConstructionComponent", "MetalGrid", "PowerCell",
        "RadioCommunicationComponent", "DetectorComponent", "MedicalComponent", "Display",
        "BulletproofGlass", "ComputerComponent", "ReactorComponent", "ThrustComponent",
        "GravityGeneratorComponent", "SolarCell", "Superconductor", "GirderComponent",
        "ExplosivesComponent", "Canvas",
    ],
    "Инструменты": [
        "AngleGrinder", "AngleGrinder2", "AngleGrinder3", "AngleGrinder4",
        "HandDrill", "HandDrill2", "HandDrill3", "HandDrill4",
        "Welder", "Welder2", "Welder3", "Welder4",
    ],
    "Оружие": [
        "SemiAutoPistol", "FullAutoPistol", "EliteAutoPistol",
        "AutomaticRifle", "RapidFireAutomaticRifle",
        "PreciseAutomaticRifle", "UltimateAutomaticRifle",
        "BasicHandHeldLauncher", "AdvancedHandHeldLauncher",
        "FlareGun",
    ],
    "Боеприпасы": [
        "NATO_25x184mm", "AutocannonClip", "Missile200mm",
        "MediumCalibreAmmo", "LargeCalibreAmmo",
        "SmallRailgunAmmo", "LargeRailgunAmmo",
        "SemiAutoPistolMagazine", "FullAutoPistolMagazine",
        "ElitePistolMagazine", "AutomaticRifleGun_Mag_20rd",
        "RapidFireAutomaticRifleGun_Mag_50rd",
        "PreciseAutomaticRifleGun_Mag_5rd",
        "UltimateAutomaticRifleGun_Mag_30rd",
        "FlareClip",
    ],
    "Предметы": [
        "OxygenBottle", "HydrogenBottle", "Medkit", "Powerkit",
        "Datapad",
    ],
    "Фейерверки": [
        "FireworksBoxBlue", "FireworksBoxGreen", "FireworksBoxRed",
        "FireworksBoxYellow", "FireworksBoxPink", "FireworksBoxRainbow",
    ],
}


def _bp_subtype(bp: dict) -> str:
    bp_id = bp.get("blueprintId", "")
    return bp_id.rsplit("/", 1)[-1] if "/" in bp_id else bp_id


def _bp_name(bp: dict) -> str:
    return bp.get("displayName") or _bp_subtype(bp)


def _bp_prereqs(bp: dict) -> list[str]:
    lines = []
    for p in bp.get("prerequisites", []):
        name = p.get("subtype", "?")
        amt = p.get("amount", 1)
        lines.append(f"{name} x{int(amt) if amt == int(amt) else amt}")
    return lines


def _classify(bp: dict) -> str:
    bp_id = bp.get("blueprintId", "")
    subtype = _bp_subtype(bp)

    # Точное совпадение
    for cat, subtypes in CATEGORIES.items():
        if subtype in subtypes:
            return cat

    # Поиск по суффиксу ID (для Position-префиксов)
    bp_lower = bp_id.lower()
    if any(k in bp_lower for k in ["grinder", "handdrill", "welder"]):
        return "Инструменты"
    if any(k in bp_lower for k in ["pistol", "rifle", "launcher", "flaregun"]):
        if any(k in bp_lower for k in ["magazine", "ammo", "clip"]):
            return "Боеприпасы"
        return "Оружие"
    if any(k in bp_lower for k in ["magazine", "ammo", "clip", "missile", "rocket", "sabot", "shell"]):
        return "Боеприпасы"
    if "firework" in bp_lower:
        return "Фейерверки"
    if any(k in bp_lower for k in ["bottle", "medkit", "powerkit", "canvas", "datapad"]):
        return "Предметы"

    return "Прочее"


def show_production(grid, *, full: bool = False) -> None:
    assemblers = [
        d for d in grid.devices.values()
        if isinstance(d, AssemblerDevice)
    ]

    if not assemblers:
        print("Конструкторы не найдены на гриде")
        return

    print(f"Грид: {grid.name}")
    print(f"Конструкторов: {len(assemblers)}")

    for a in assemblers:
        a.set_enabled(True)

    time.sleep(0.5)

    # Запросить чертежи
    for a in assemblers:
        if a.blueprints is None:
            a.request_blueprints()
    time.sleep(1)

    # Собрать все чертежи
    all_blueprints: dict[str, dict] = {}
    for a in assemblers:
        if a.blueprints is None:
            continue
        for bp in a.blueprints:
            key = _bp_subtype(bp)
            if key not in all_blueprints:
                all_blueprints[key] = bp

    if not all_blueprints:
        print("Чертежи не загружены")
        return

    # Группировка по категориям
    grouped: dict[str, list[dict]] = defaultdict(list)
    for bp in all_blueprints.values():
        grouped[_classify(bp)].append(bp)

    cat_order = ["Компоненты", "Инструменты", "Оружие", "Боеприпасы", "Предметы", "Фейерверки", "Прочее"]

    print(f"\n{'=' * 60}")
    print(f"Доступно чертежей: {len(all_blueprints)}")
    print(f"{'=' * 60}")

    for cat in cat_order:
        bps = grouped.get(cat, [])
        if not bps:
            continue
        bps.sort(key=lambda b: _bp_name(b))
        print(f"\n[{cat}] ({len(bps)})")
        print("-" * 40)
        for bp in bps:
            name = _bp_name(bp)
            prereqs = _bp_prereqs(bp)
            if full and prereqs:
                print(f"  {name}")
                print(f"    <- {', '.join(prereqs)}")
            else:
                print(f"  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Показать возможности производства грида")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--full", action="store_true", help="Показать материалы для каждого чертежа")
    args = parser.parse_args()

    grid = prepare_grid(args.grid)
    try:
        show_production(grid, full=args.full)
    finally:
        close(grid)


if __name__ == "__main__":
    main()
