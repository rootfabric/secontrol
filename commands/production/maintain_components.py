"""Поддержание запаса компонентов на гриде.

Читает целевые количества из production_targets.json, проверяет инвентарь
и текущую очередь конструктора. Если с учётом уже поставленных заданий
компонентов всё ещё не хватает — добавляет только недостающую разницу.

Использование:
    python examples/organized/assembler/basic/maintain_components.py --grid farpost0
    python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --dry-run
    python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --config my_targets.json
    python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --no-verify
    python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --ignore-queue
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.item_types import COMPONENT_ITEMS, INGOT_ITEMS, item_matches

CONFIG_PATH = Path(__file__).parent / "production_targets.json"
EPSILON = 1e-6

# Маппинг: blueprint subtype -> inventory subtype.
# Большинство совпадают, но некоторые компоненты в инвентаре имеют другое имя.
BLUEPRINT_TO_INVENTORY = {
    "SteelPlate": "SteelPlate",
    "InteriorPlate": "InteriorPlate",
    "SmallTube": "SmallTube",
    "LargeTube": "LargeTube",
    "MotorComponent": "Motor",
    "ConstructionComponent": "Construction",
    "MetalGrid": "MetalGrid",
    "PowerCell": "PowerCell",
    "RadioCommunicationComponent": "RadioCommunication",
    "DetectorComponent": "Detector",
    "MedicalComponent": "Medical",
    "Display": "Display",
    "BulletproofGlass": "BulletproofGlass",
    "ComputerComponent": "Computer",
    "ReactorComponent": "Reactor",
    "ThrustComponent": "Thrust",
    "GravityGeneratorComponent": "GravityGenerator",
    "SolarCell": "SolarCell",
    "Superconductor": "Superconductor",
    "GirderComponent": "Girder",
    "ExplosivesComponent": "Explosives",
}


def load_targets(config_path: Path) -> dict[str, int]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config must contain an object: {config_path}")

    targets: dict[str, int] = {}
    for key, value in data.items():
        amount = int(value)
        if amount < 0:
            raise ValueError(f"Target amount must be >= 0 for {key}: {amount}")
        targets[str(key)] = amount
    return targets


def find_item_type(inventory_subtype: str):
    """Найти ItemType по inventory subtype."""
    for item in COMPONENT_ITEMS:
        if item.subtype == inventory_subtype:
            return item
    for item in INGOT_ITEMS:
        if item.subtype == inventory_subtype:
            return item
    return None


def count_in_inventory(grid, item_type) -> float:
    """Подсчитать количество предмета во всех контейнерах грида."""
    total = 0.0
    for device in grid.devices.values():
        if not isinstance(device, ContainerDevice):
            continue
        for item in device.items():
            if item_matches(item, item_type):
                total += float(item.amount)
    return total


def find_assembler(grid) -> AssemblerDevice | None:
    assemblers = [device for device in grid.devices.values() if isinstance(device, AssemblerDevice)]
    if not assemblers:
        return None

    # Предпочитаем включённый/рабочий конструктор, если телеметрия это показывает.
    for assembler in assemblers:
        telemetry = assembler.telemetry or {}
        enabled = bool(telemetry.get("enabled", telemetry.get("isWorking", True)))
        functional = bool(telemetry.get("isFunctional", True))
        if enabled and functional:
            return assembler
    return assemblers[0]


def refresh_assembler_telemetry(assembler: AssemblerDevice, *, timeout: float = 1.0) -> None:
    """Запросить свежую телеметрию, но не падать, если ответ не пришёл."""
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        pass


def print_assembler_state(assembler: AssemblerDevice) -> None:
    telemetry = assembler.telemetry or {}
    mode = assembler.mode() or "unknown"
    print(f"Конструктор: {assembler.name} ({assembler.device_id})")
    print(
        f"  enabled={telemetry.get('enabled', 'N/A')} "
        f"functional={telemetry.get('isFunctional', 'N/A')} "
        f"working={telemetry.get('isWorking', 'N/A')} "
        f"mode={mode} "
        f"disassemble={telemetry.get('disassembleEnabled', 'N/A')}"
    )
    print(f"  queue_items={len(assembler.queue())} producing={assembler.is_producing()} progress={assembler.current_progress():.3f}")


def prepare_blueprints(assembler: AssemblerDevice) -> None:
    if assembler.wait_for_blueprints(timeout=2.0):
        print(f"  blueprints={len(assembler.blueprints or [])}")
    else:
        print("  blueprints не получены, буду использовать canonical id вида MyObjectBuilder_BlueprintDefinition/<Subtype>")


def blueprint_subtype(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def queue_entry_subtype(entry: dict[str, Any]) -> str:
    """Достать subtype blueprint-а из позиции очереди конструктора."""
    for key in ("blueprintSubtype", "subtype"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    for key in ("blueprintId", "blueprint", "id", "itemId"):
        value = str(entry.get(key) or "").strip()
        if value:
            return blueprint_subtype(value)

    return ""


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_amount(value: float) -> str:
    value = float(value)
    if math.isclose(value, round(value), abs_tol=EPSILON):
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def planned_queue_amounts(
    assembler: AssemblerDevice,
    *,
    ignore_queue: bool = False,
    count_queue_in_disassemble_mode: bool = False,
) -> dict[str, float]:
    """Сумма уже запланированных blueprint-ов в очереди конструктора.

    В текущей телеметрии плагина у позиции очереди нет отдельного признака
    сборки/разбора. Поэтому, если конструктор сейчас в режиме разбора,
    очередь по умолчанию не считаем как производство, чтобы не принять разбор
    компонентов за будущую сборку.
    """
    if ignore_queue:
        return {}

    telemetry = assembler.telemetry or {}
    disassemble_enabled = bool(telemetry.get("disassembleEnabled", False))
    queue = assembler.queue()

    if disassemble_enabled and not count_queue_in_disassemble_mode:
        if queue:
            print(
                "[!] Конструктор сейчас в режиме разбора; существующую очередь "
                "не считаю как запланированное производство."
            )
            print("    Если точно знаешь, что в очереди сборка, запусти с --count-queue-in-disassemble-mode.")
        return {}

    totals: defaultdict[str, float] = defaultdict(float)
    for entry in queue:
        subtype = queue_entry_subtype(entry)
        if not subtype:
            continue
        amount = safe_float(entry.get("amount"), 0.0)
        if amount > EPSILON:
            totals[subtype.lower()] += amount
    return dict(totals)


def maintain_components(
    grid,
    targets: dict[str, int],
    *,
    dry_run: bool = False,
    verify: bool = True,
    verify_timeout: float = 3.0,
    delay: float = 0.2,
    ignore_queue: bool = False,
    count_queue_in_disassemble_mode: bool = False,
) -> int:
    assembler = find_assembler(grid)
    if not assembler:
        print("Конструктор не найден на гриде")
        return 1

    refresh_assembler_telemetry(assembler, timeout=1.0)

    print(f"Грид: {grid.name}")
    print_assembler_state(assembler)
    prepare_blueprints(assembler)

    queue_amounts = planned_queue_amounts(
        assembler,
        ignore_queue=ignore_queue,
        count_queue_in_disassemble_mode=count_queue_in_disassemble_mode,
    )

    if ignore_queue:
        print("  очередь конструктора не учитывается (--ignore-queue)")
    else:
        total_queued = sum(queue_amounts.values())
        print(f"  учитываю очередь сборки: {format_amount(total_queued)} шт. по известным blueprint-ам")

    print(f"Целей: {len(targets)}")
    print("=" * 60)

    actions: list[tuple[str, int]] = []

    for bp_subtype, target_amount in targets.items():
        inv_subtype = BLUEPRINT_TO_INVENTORY.get(bp_subtype, bp_subtype)
        item_type = find_item_type(inv_subtype)

        if not item_type:
            print(f"[!] {bp_subtype}: неизвестный тип компонента, пропускаю")
            continue

        current = count_in_inventory(grid, item_type)
        queued = queue_amounts.get(bp_subtype.lower(), 0.0)
        planned_total = current + queued
        deficit = float(target_amount) - planned_total

        if deficit <= EPSILON:
            status = "OK"
        else:
            status = f"добавить {format_amount(math.ceil(deficit - EPSILON))}"

        print(
            f"  {item_type.display_name}: "
            f"склад {format_amount(current)} + очередь {format_amount(queued)} "
            f"= {format_amount(planned_total)}/{target_amount} — {status}"
        )

        if deficit > EPSILON:
            actions.append((bp_subtype, int(math.ceil(deficit - EPSILON))))

    if not actions:
        print("\nС учётом текущей очереди всего хватает, производство не требуется.")
        return 0

    print(f"\n{'=' * 60}")
    print(f"Требуется добавить в очередь: {len(actions)} позиций")

    if not dry_run:
        print("\nПереключаю конструктор в режим сборки (DisassembleEnabled=False)...")
        if verify:
            if assembler.set_disassemble_verified(False, timeout=verify_timeout):
                print("  режим сборки подтверждён")
            else:
                print("  [!] не удалось подтвердить режим сборки; задачи могут попасть в режим разбора")
        else:
            assembler.set_disassemble(False)

    failed: list[tuple[str, int]] = []
    for bp_subtype, amount in actions:
        blueprint_id = assembler.resolve_blueprint_id(bp_subtype, request=False)
        if dry_run:
            print(f"  [dry-run] {bp_subtype} -> {blueprint_id} x{amount}")
            continue

        print(f"  [>] {bp_subtype} -> {blueprint_id} x{amount}")
        if verify:
            ok = assembler.add_queue_item_verified(blueprint_id, amount, timeout=verify_timeout)
            if ok:
                print("      подтверждено телеметрией очереди")
            else:
                print("      НЕ подтверждено: команда ушла, но очередь в телеметрии не изменилась")
                failed.append((bp_subtype, amount))
        else:
            sent = assembler.add_queue_item(blueprint_id, amount)
            if sent <= 0:
                failed.append((bp_subtype, amount))
        if delay > 0:
            time.sleep(delay)

    if dry_run:
        print("\n[dry-run] Команды не отправлены. Уберите --dry-run для запуска.")
        return 0

    print("\nИтоговая очередь конструктора:")
    refresh_assembler_telemetry(assembler, timeout=1.0)
    assembler.print_queue()

    if failed:
        print("\nНе удалось подтвердить добавление задач:")
        for bp_subtype, amount in failed:
            print(f"  - {bp_subtype} x{amount}")
        print("\nПроверь логи плагина: если там command 'queue_add' was not handled или ошибка blueprint, проблема на стороне обработчика AssemblerDevice.")
        return 2

    print("\nЗадачи подтверждённо добавлены в очередь конструктора.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Поддержание запаса компонентов")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Путь к файлу целей")
    parser.add_argument("--dry-run", action="store_true", help="Показать что будет сделано, но не отправлять")
    parser.add_argument("--no-verify", action="store_true", help="Не ждать подтверждения очереди из телеметрии")
    parser.add_argument("--verify-timeout", type=float, default=3.0, help="Сколько секунд ждать изменение очереди после каждой команды")
    parser.add_argument("--delay", type=float, default=0.2, help="Пауза между командами")
    parser.add_argument("--ignore-queue", action="store_true", help="Не учитывать существующую очередь конструктора")
    parser.add_argument(
        "--count-queue-in-disassemble-mode",
        action="store_true",
        help="Учитывать существующую очередь даже если сейчас включён режим разбора",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Файл конфигурации не найден: {config_path}")
        sys.exit(1)

    try:
        targets = load_targets(config_path)
    except Exception as exc:
        print(f"Ошибка чтения конфигурации: {exc}")
        sys.exit(1)

    grid = prepare_grid(args.grid)
    try:
        code = maintain_components(
            grid,
            targets,
            dry_run=args.dry_run,
            verify=not args.no_verify,
            verify_timeout=args.verify_timeout,
            delay=args.delay,
            ignore_queue=args.ignore_queue,
            count_queue_in_disassemble_mode=args.count_queue_in_disassemble_mode,
        )
    finally:
        close(grid)

    sys.exit(code)


if __name__ == "__main__":
    main()
