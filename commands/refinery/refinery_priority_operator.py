"""Операторский скрипт приоритета очистителей.

Задачи:
- читать порядок руд из JSON-конфига;
- смотреть все очистители на гриде;
- в режиме оценки показывать, что будет изменено;
- в режиме применения переставлять очередь и входную руду очистителей;
- опционально поднимать приоритет руд по очереди сборки ассемблеров.

Примеры:
  python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --evaluate
  python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --apply
  python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --apply --from-assembler-queue
  python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --apply --loop --interval 30
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.refinery_device import RefineryDevice

CONFIG_PATH = Path(__file__).with_name("refinery_priority_config.json")
SCRIPT_VERSION = "refinery-priority-v5-keep-lower-priority-after-first-2026-05-31"
EPSILON = 1e-6
ORE_TYPE_ID = "MyObjectBuilder_Ore"

DEFAULT_ORE_ORDER = [
    "Uranium",
    "Platinum",
    "Gold",
    "Silver",
    "Cobalt",
    "Magnesium",
    "Nickel",
    "Silicon",
    "Iron",
    "Stone",
]

ORE_TO_BLUEPRINT = {
    "Stone": "StoneOreToIngot",
    "Iron": "IronOreToIngot",
    "Nickel": "NickelOreToIngot",
    "Cobalt": "CobaltOreToIngot",
    "Magnesium": "MagnesiumOreToIngot",
    "Silicon": "SiliconOreToIngot",
    "Silver": "SilverOreToIngot",
    "Gold": "GoldOreToIngot",
    "Platinum": "PlatinumOreToIngot",
    "Uranium": "UraniumOreToIngot",
}

INGOT_TO_ORE = {
    "Stone": "Stone",
    "Iron": "Iron",
    "Nickel": "Nickel",
    "Cobalt": "Cobalt",
    "Magnesium": "Magnesium",
    "Silicon": "Silicon",
    "Silver": "Silver",
    "Gold": "Gold",
    "Platinum": "Platinum",
    "Uranium": "Uranium",
}

DEFAULT_CONFIG = {
    "ore_order": DEFAULT_ORE_ORDER,
    "ore_to_blueprint": ORE_TO_BLUEPRINT,
    "max_ore_types_per_refinery": 3,
    "queue_amount_per_ore": 1000,
    "move_amount_per_ore": 1000,
    "min_ore_amount": 1,
    "source_container_tags": ["source", "input", "ore"],
    "use_all_containers_if_no_tagged_sources": True,
    "allow_move_from_other_refineries": False,
    "clear_wrong_ore_from_refinery_input": True,
    "force_priority_ore_to_first_input_slot": True,
    "restore_displaced_lower_priority_ore": False,
    "temporary_storage_tags": ["ore", "cargo", "storage", "buffer", "input"],
    "verify_transfer_timeout": 2.0,
    "assembler_queue_boost": {
        "ingot_safety_stock": {
            "Uranium": 10,
            "Platinum": 10,
            "Gold": 50,
            "Silver": 50,
            "Cobalt": 100,
            "Magnesium": 100,
            "Nickel": 100,
            "Silicon": 100,
            "Iron": 500,
            "Stone": 0,
        }
    },
}


@dataclass
class OreInventory:
    totals: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_container: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class AssemblerDemand:
    required_ingots: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    available_ingots: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    shortages: dict[str, float] = field(default_factory=dict)
    boosted_ores: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RefineryPlan:
    refinery: RefineryDevice
    desired_ores: list[str]
    desired_queue: list[dict[str, Any]]
    current_queue: list[dict[str, Any]]
    current_input_ores: list[str]
    queue_ok: bool
    input_ok: bool
    actions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def write_default_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        write_default_config(path)
        print(f"Создан конфиг по умолчанию: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config must be JSON object: {path}")

    merged = json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
    deep_update(merged, data)
    validate_config(merged)
    return merged


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value


def validate_config(config: dict[str, Any]) -> None:
    ore_order = config.get("ore_order")
    if not isinstance(ore_order, list) or not ore_order:
        raise ValueError("config.ore_order must be a non-empty list")

    ore_to_blueprint = config.get("ore_to_blueprint")
    if not isinstance(ore_to_blueprint, dict):
        raise ValueError("config.ore_to_blueprint must be an object")

    for ore in ore_order:
        if not isinstance(ore, str) or not ore.strip():
            raise ValueError(f"Invalid ore in ore_order: {ore!r}")
        if ore not in ore_to_blueprint:
            raise ValueError(f"Ore {ore!r} has no blueprint in ore_to_blueprint")

    for int_key in ("max_ore_types_per_refinery", "queue_amount_per_ore", "move_amount_per_ore"):
        if float(config.get(int_key, 0)) <= 0:
            raise ValueError(f"config.{int_key} must be > 0")


# ---------------------------------------------------------------------------
# Discovery and telemetry
# ---------------------------------------------------------------------------


def refresh_device(device, *, timeout: float = 1.0) -> None:
    try:
        device.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        pass


def find_refineries(grid) -> list[RefineryDevice]:
    return [device for device in grid.devices.values() if isinstance(device, RefineryDevice)]


def find_assemblers(grid) -> list[AssemblerDevice]:
    return [device for device in grid.devices.values() if isinstance(device, AssemblerDevice)]


def find_containers(grid) -> list[ContainerDevice]:
    return [device for device in grid.devices.values() if isinstance(device, ContainerDevice)]


def normalize_tag(text: str) -> str:
    return str(text or "").strip().lower()


def container_has_any_tag(container: ContainerDevice, tags: Iterable[str]) -> bool:
    wanted = {normalize_tag(tag) for tag in tags if normalize_tag(tag)}
    if not wanted:
        return False

    name = normalize_tag(container.name)
    custom_data = normalize_tag(container.custom_data() or "")
    runtime_tags = {normalize_tag(tag) for tag in getattr(container, "tags", set())}

    for tag in wanted:
        if tag in runtime_tags:
            return True
        if f"[{tag}]" in name or tag in custom_data:
            return True
    return False


def source_containers(grid, config: dict[str, Any]) -> list[ContainerDevice]:
    containers = find_containers(grid)
    refineries = set(id(refinery) for refinery in find_refineries(grid))
    non_refinery = [container for container in containers if id(container) not in refineries]

    tags = config.get("source_container_tags") or []
    tagged = [container for container in non_refinery if container_has_any_tag(container, tags)]
    if tagged:
        return tagged

    if config.get("use_all_containers_if_no_tagged_sources", True):
        return non_refinery
    return []


# ---------------------------------------------------------------------------
# Item helpers
# ---------------------------------------------------------------------------


def normalize_subtype(value: Any) -> str:
    text = str(value or "").strip()
    return text.rsplit("/", 1)[-1] if "/" in text else text


def normalize_ore_name(value: Any) -> str:
    subtype = normalize_subtype(value)
    if subtype.endswith(" Ore"):
        subtype = subtype[:-4]
    if subtype.endswith("Ore"):
        subtype = subtype[:-3]
    return subtype


def is_ore_item(item: Any, ore_order: Iterable[str]) -> bool:
    item_type = str(getattr(item, "type", "") or "")
    subtype = normalize_ore_name(getattr(item, "subtype", ""))
    display_name = str(getattr(item, "display_name", "") or "").lower()
    known_ores = set(ore_order) | set(ORE_TO_BLUEPRINT.keys())

    if item_type == "MyObjectBuilder_Ore" and subtype in known_ores:
        return True
    if subtype in known_ores and ("ore" in display_name or "руда" in display_name or subtype == "Stone"):
        return True
    return False


def is_ingot_item(item: Any) -> bool:
    item_type = str(getattr(item, "type", "") or "")
    subtype = normalize_subtype(getattr(item, "subtype", ""))
    return item_type == "MyObjectBuilder_Ingot" and subtype in INGOT_TO_ORE


def queue_blueprint_subtype(entry: dict[str, Any]) -> str:
    for key in ("blueprintSubtype", "blueprintId", "blueprint", "id", "subtype"):
        value = entry.get(key)
        if value:
            return normalize_subtype(value)
    return ""


def amount_of(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def format_amount(value: float) -> str:
    value = float(value)
    if math.isclose(value, round(value), abs_tol=EPSILON):
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Inventories and assembler demand
# ---------------------------------------------------------------------------


def collect_ore_inventory(grid, config: dict[str, Any]) -> OreInventory:
    ore_order = config["ore_order"]
    result = OreInventory()

    for container in find_containers(grid):
        per_container: defaultdict[str, float] = defaultdict(float)
        try:
            items = container.items()
        except Exception:
            continue
        for item in items:
            if not is_ore_item(item, ore_order):
                continue
            ore = normalize_ore_name(item.subtype)
            amount = amount_of(item.amount)
            if amount <= EPSILON:
                continue
            result.totals[ore] += amount
            per_container[ore] += amount
        if per_container:
            result.by_container[container.name or str(container.device_id)] = dict(per_container)

    result.totals = dict(result.totals)
    return result


def collect_ingots(grid) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for container in find_containers(grid):
        try:
            items = container.items()
        except Exception:
            continue
        for item in items:
            if not is_ingot_item(item):
                continue
            totals[normalize_subtype(item.subtype)] += amount_of(item.amount)
    return dict(totals)


def blueprint_result_amount(blueprint: dict[str, Any], queue_subtype: str) -> float:
    results = blueprint.get("results") if isinstance(blueprint, dict) else None
    if not isinstance(results, list):
        return 1.0
    for result in results:
        if not isinstance(result, dict):
            continue
        result_subtype = normalize_subtype(result.get("subtype"))
        if result_subtype == queue_subtype:
            amount = amount_of(result.get("amount"), 1.0)
            return amount if amount > EPSILON else 1.0
    return 1.0


def index_assembler_blueprints(assemblers: list[AssemblerDevice]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for assembler in assemblers:
        try:
            assembler.wait_for_blueprints(timeout=2.0)
        except Exception:
            try:
                assembler.request_blueprints()
                time.sleep(0.5)
            except Exception:
                pass
        for bp in assembler.blueprints or []:
            if not isinstance(bp, dict):
                continue
            bp_id = str(bp.get("blueprintId") or "")
            subtype = normalize_subtype(bp_id)
            if subtype:
                indexed[subtype] = bp
    return indexed


def analyze_assembler_queue(grid, config: dict[str, Any]) -> AssemblerDemand:
    demand = AssemblerDemand()
    assemblers = find_assemblers(grid)
    if not assemblers:
        demand.notes.append("Ассемблеры не найдены, boost по очереди сборки невозможен.")
        return demand

    for assembler in assemblers:
        refresh_device(assembler, timeout=1.0)
    blueprints = index_assembler_blueprints(assemblers)
    ingot_stock = collect_ingots(grid)
    demand.available_ingots.update(ingot_stock)

    for assembler in assemblers:
        queue = assembler.queue()
        if not queue:
            continue
        for entry in queue:
            queue_subtype = queue_blueprint_subtype(entry)
            if not queue_subtype:
                continue
            blueprint = blueprints.get(queue_subtype)
            if not blueprint:
                demand.notes.append(f"Нет blueprint-данных для очереди ассемблера: {queue_subtype}")
                continue

            queue_amount = amount_of(entry.get("amount"), 0.0)
            result_amount = blueprint_result_amount(blueprint, queue_subtype)
            batches = queue_amount / result_amount if result_amount > EPSILON else queue_amount

            prereqs = blueprint.get("prerequisites")
            if not isinstance(prereqs, list):
                continue
            for prereq in prereqs:
                if not isinstance(prereq, dict):
                    continue
                ingot = normalize_subtype(prereq.get("subtype"))
                prereq_type = str(prereq.get("type") or "")
                if ingot not in INGOT_TO_ORE:
                    continue
                if prereq_type and prereq_type != "MyObjectBuilder_Ingot":
                    continue
                demand.required_ingots[ingot] += amount_of(prereq.get("amount"), 0.0) * batches

    safety = (config.get("assembler_queue_boost") or {}).get("ingot_safety_stock") or {}
    shortages: dict[str, float] = {}
    for ingot, required in demand.required_ingots.items():
        reserve = amount_of(safety.get(ingot), 0.0)
        available = demand.available_ingots.get(ingot, 0.0)
        shortage = required + reserve - available
        if shortage > EPSILON:
            shortages[ingot] = shortage

    demand.shortages = shortages

    ore_order = config["ore_order"]
    ore_position = {ore: index for index, ore in enumerate(ore_order)}
    boosted = []
    for ingot, shortage in sorted(shortages.items(), key=lambda kv: (-kv[1], ore_position.get(INGOT_TO_ORE.get(kv[0], ""), 999))):
        ore = INGOT_TO_ORE.get(ingot)
        if ore and ore not in boosted:
            boosted.append(ore)
    demand.boosted_ores = boosted
    return demand


def build_effective_ore_order(config: dict[str, Any], assembler_demand: AssemblerDemand | None) -> list[str]:
    base_order = list(config["ore_order"])
    if not assembler_demand or not assembler_demand.boosted_ores:
        return base_order
    boosted = [ore for ore in assembler_demand.boosted_ores if ore in base_order]
    return boosted + [ore for ore in base_order if ore not in boosted]


# ---------------------------------------------------------------------------
# Refinery planning and apply
# ---------------------------------------------------------------------------


def current_input_ores(refinery: RefineryDevice, config: dict[str, Any]) -> list[str]:
    inv = refinery.input_inventory()
    items = inv.items if inv else []
    result: list[str] = []
    for item in items:
        if not is_ore_item(item, config["ore_order"]):
            continue
        ore = normalize_ore_name(item.subtype)
        if not result or result[-1] != ore:
            result.append(ore)
    return result


def current_input_ore_amounts(refinery: RefineryDevice, config: dict[str, Any]) -> dict[str, float]:
    inv = refinery.input_inventory()
    items = inv.items if inv else []
    totals: defaultdict[str, float] = defaultdict(float)
    for item in items:
        if not is_ore_item(item, config["ore_order"]):
            continue
        totals[normalize_ore_name(item.subtype)] += amount_of(item.amount)
    return dict(totals)


def build_desired_queue(config: dict[str, Any], available_ores: dict[str, float], effective_order: list[str]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    max_types = int(config["max_ore_types_per_refinery"])
    min_amount = amount_of(config.get("min_ore_amount"), 1.0)
    queue_amount = amount_of(config.get("queue_amount_per_ore"), 1000.0)
    ore_to_blueprint = config["ore_to_blueprint"]

    for ore in effective_order:
        available = available_ores.get(ore, 0.0)
        if available < min_amount:
            continue
        blueprint = ore_to_blueprint.get(ore)
        if not blueprint:
            continue
        queue.append({"ore": ore, "blueprint": blueprint, "amount": min(queue_amount, available)})
        if len(queue) >= max_types:
            break
    return queue


def queue_matches(current_queue: list[dict[str, Any]], desired_queue: list[dict[str, Any]]) -> bool:
    if len(current_queue) < len(desired_queue):
        return False
    for index, desired in enumerate(desired_queue):
        current = current_queue[index]
        current_bp = queue_blueprint_subtype(current)
        desired_bp = normalize_subtype(desired["blueprint"])
        if current_bp != desired_bp:
            return False
    return True


def input_matches(input_ores: list[str], desired_ores: list[str]) -> bool:
    if not desired_ores:
        return not input_ores
    if not input_ores:
        return False

    # Важно не только чтобы первая руда была правильной, но и чтобы уже доступные
    # нижние приоритеты тоже лежали после неё. Иначе v4 после выноса Cobalt/Silver
    # считал input_ok=True при входе [Uranium] и больше не возвращал Cobalt/Silver
    # во вход очистителя.
    if len(input_ores) < len(desired_ores):
        return False
    return input_ores[: len(desired_ores)] == desired_ores


def build_plan(refinery: RefineryDevice, config: dict[str, Any], desired_queue: list[dict[str, Any]]) -> RefineryPlan:
    refresh_device(refinery, timeout=1.0)
    current_queue = refinery.queue()
    input_ores = current_input_ores(refinery, config)
    desired_ores = [entry["ore"] for entry in desired_queue]
    plan = RefineryPlan(
        refinery=refinery,
        desired_ores=desired_ores,
        desired_queue=desired_queue,
        current_queue=current_queue,
        current_input_ores=input_ores,
        queue_ok=queue_matches(current_queue, desired_queue),
        input_ok=input_matches(input_ores, desired_ores),
    )

    if not plan.queue_ok:
        plan.actions.append("переписать очередь очистителя")
    if not plan.input_ok:
        plan.actions.append("переставить руду во входном инвентаре")
    return plan


def device_label(device: Any) -> str:
    name = str(getattr(device, "name", "") or "").strip()
    device_type = str(getattr(device, "device_type", "") or device.__class__.__name__).strip()
    device_id = str(getattr(device, "device_id", "") or "?").strip()
    if name:
        return name
    return f"{device_type or 'device'}({device_id})"


def inventory_fill_ratio(container: ContainerDevice) -> float:
    try:
        capacity = container.capacity()
    except Exception:
        return 1.0
    try:
        return float(capacity.get("fillRatio", 1.0) or 0.0)
    except Exception:
        return 1.0


def container_has_ore(container: ContainerDevice, ore: str, config: dict[str, Any]) -> bool:
    try:
        items = container.items()
    except Exception:
        return False
    for item in items:
        if not is_ore_item(item, config["ore_order"]):
            continue
        if normalize_ore_name(item.subtype) == ore and amount_of(item.amount) > EPSILON:
            return True
    return False


def storage_score(container: ContainerDevice, config: dict[str, Any], ore: str | None) -> tuple[float, str]:
    name = normalize_tag(getattr(container, "name", "") or "")
    device_type = normalize_tag(getattr(container, "device_type", "") or "")
    fill = inventory_fill_ratio(container)
    score = fill * 100.0

    # Временный буфер должен быть обычным контейнером, а не ассемблером/очистителем/генератором.
    if device_type != "container":
        score += 1000.0
    if not name:
        score += 100.0
    if "cargo" in name or "container" in name or "контейнер" in name:
        score -= 200.0
    if container_has_any_tag(container, config.get("temporary_storage_tags") or []):
        score -= 300.0
    if ore and container_has_ore(container, ore, config):
        score -= 100.0
    if fill >= 0.98:
        score += 10000.0
    return score, device_label(container)


def choose_temporary_storage(
    grid,
    config: dict[str, Any],
    refinery: RefineryDevice,
    *,
    ore: str | None = None,
) -> ContainerDevice | None:
    seen: set[int] = set()
    candidates: list[ContainerDevice] = []
    for container in list(source_containers(grid, config)) + list(find_containers(grid)):
        try:
            key = int(container.device_id)
        except Exception:
            key = id(container)
        if key in seen:
            continue
        seen.add(key)
        if container.device_id == refinery.device_id:
            continue
        if isinstance(container, RefineryDevice):
            continue
        if inventory_fill_ratio(container) >= 0.98:
            continue
        candidates.append(container)

    if not candidates:
        return None
    candidates.sort(key=lambda item: storage_score(item, config, ore))
    return candidates[0]


def inventory_index(snapshot: Any, default: int = 0) -> int:
    try:
        return int(snapshot.index)
    except Exception:
        return int(default)


def refinery_input_index(refinery: RefineryDevice) -> int:
    return inventory_index(refinery.input_inventory(), 0)


def send_transfer_via(
    command_device: ContainerDevice,
    source: ContainerDevice,
    destination: ContainerDevice,
    subtype: str,
    *,
    amount: float | None = None,
    type_id: str | None = None,
    source_inventory_index: int | None = None,
    destination_inventory_index: int | None = None,
    target_slot_id: int | None = None,
) -> int:
    item: dict[str, Any] = {"subtype": subtype}
    if type_id:
        item["type"] = type_id
    if amount is not None:
        item["amount"] = float(amount)
    if target_slot_id is not None:
        item["targetSlotId"] = int(target_slot_id)

    payload: dict[str, Any] = {
        "fromId": int(source.device_id),
        "toId": int(destination.device_id),
        "items": [item],
    }
    if source_inventory_index is not None:
        payload["fromInventoryIndex"] = int(source_inventory_index)
    if destination_inventory_index is not None:
        payload["toInventoryIndex"] = int(destination_inventory_index)

    # Важно: команду для операций с inputInventory очистителя отправляем самому
    # очистителю. Тогда C#-плагин уважает SourceInventoryIndex/DestinationInventoryIndex
    # для этого блока. Если отправить команду с cargo-контейнера, индекс remote refinery
    # в текущем плагине игнорируется и TryExtractInventory берёт GetInventory(0).
    return command_device.send_command({"cmd": "transfer_items", "state": json.dumps(payload, ensure_ascii=False)})


def wait_for_transfer_result(devices: Iterable[ContainerDevice], predicate, *, timeout: float) -> bool:
    deadline = time.time() + max(0.1, float(timeout))
    while time.time() <= deadline:
        for device in devices:
            refresh_device(device, timeout=0.35)
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    for device in devices:
        refresh_device(device, timeout=0.5)
    try:
        return bool(predicate())
    except Exception:
        return False


def move_from_refinery_input_verified(
    refinery: RefineryDevice,
    storage: ContainerDevice,
    ore: str,
    subtype: str,
    amount: float,
    config: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    if not apply:
        print(f"  [plan] {device_label(refinery)}: временно вынести {format_amount(amount)} {ore} в {device_label(storage)}")
        return True

    before_amount = current_input_ore_amounts(refinery, config).get(ore, 0.0)
    if before_amount <= EPSILON:
        return True

    timeout = amount_of(config.get("verify_transfer_timeout"), 2.0)
    input_index = refinery_input_index(refinery)
    tried: list[str] = []
    for source_index in [input_index, 0, 1, None]:
        label = "default" if source_index is None else str(source_index)
        if label in tried:
            continue
        tried.append(label)
        try:
            send_transfer_via(
                refinery,
                refinery,
                storage,
                subtype,
                amount=amount,
                type_id=ORE_TYPE_ID,
                source_inventory_index=source_index,
            )
        except Exception as exc:
            print(f"  [!] {device_label(refinery)}: transfer {ore} sourceInventoryIndex={label} не отправлен: {exc}")
            continue

        ok = wait_for_transfer_result(
            [refinery, storage],
            lambda: current_input_ore_amounts(refinery, config).get(ore, 0.0) < before_amount - EPSILON,
            timeout=timeout,
        )
        if ok:
            print(f"  {device_label(refinery)} -> {device_label(storage)}: временно вынес {format_amount(amount)} {ore} из inputInventory[{label}]")
            return True

    print(
        f"  [!] {device_label(refinery)}: не смог вынести {ore}; "
        f"скорее всего transfer_items не попал в inputInventory. Проверь лог плагина ContainerDevice validation."
    )
    return False


def move_to_refinery_input_verified(
    source: ContainerDevice,
    refinery: RefineryDevice,
    ore: str,
    subtype: str,
    amount: float,
    config: dict[str, Any],
    *,
    target_slot_id: int | None,
    apply: bool,
) -> bool:
    slot_text = "" if target_slot_id is None else f" в слот {target_slot_id}"
    if not apply:
        print(f"  [plan] {device_label(source)} -> {device_label(refinery)}: {format_amount(amount)} {ore}{slot_text}")
        return True

    before_amount = current_input_ore_amounts(refinery, config).get(ore, 0.0)
    timeout = amount_of(config.get("verify_transfer_timeout"), 2.0)
    input_index = refinery_input_index(refinery)
    tried: list[str] = []
    for dest_index in [input_index, 0, 1, None]:
        label = "default" if dest_index is None else str(dest_index)
        if label in tried:
            continue
        tried.append(label)
        try:
            send_transfer_via(
                refinery,
                source,
                refinery,
                subtype,
                amount=amount,
                type_id=ORE_TYPE_ID,
                destination_inventory_index=dest_index,
                target_slot_id=target_slot_id,
            )
        except Exception as exc:
            print(f"  [!] {device_label(source)}: transfer {ore} toInventoryIndex={label} не отправлен: {exc}")
            continue

        ok = wait_for_transfer_result(
            [source, refinery],
            lambda: current_input_ore_amounts(refinery, config).get(ore, 0.0) > before_amount + EPSILON,
            timeout=timeout,
        )
        if ok:
            print(f"  {device_label(source)} -> {device_label(refinery)}: {format_amount(amount)} {ore}{slot_text} inputInventory[{label}]")
            return True

    print(
        f"  [!] {device_label(source)}: не смог переложить {ore} в {device_label(refinery)}; "
        f"вход очистителя не изменился"
    )
    return False


# old first_storage_container kept for compatibility, but apply_plan uses choose_temporary_storage.
def first_storage_container(containers: list[ContainerDevice], refinery: RefineryDevice) -> ContainerDevice | None:
    for container in containers:
        if container.device_id != refinery.device_id and not isinstance(container, RefineryDevice):
            return container
    return None


def clear_wrong_input_ores(refinery: RefineryDevice, config: dict[str, Any], desired_ores: list[str], storage: ContainerDevice | None, *, apply: bool) -> int:
    if not config.get("clear_wrong_ore_from_refinery_input", True):
        return 0
    if storage is None:
        return 0

    inv = refinery.input_inventory()
    items = list(inv.items) if inv else []
    if not items:
        return 0

    actions = 0
    allowed = set(desired_ores)

    for item in items:
        if not is_ore_item(item, config["ore_order"]):
            continue
        ore = normalize_ore_name(item.subtype)

        # Важное исправление: не убираем Silver/Stone только потому, что Uranium выше.
        # Нижние приоритеты могут оставаться во входе; первый слот выставляем отдельной
        # операцией targetSlotId=0. Иначе скрипт сам выносил Silver, потом пытался
        # занести его обратно, а Space Engineers мог снова оставить Silver в первом слоте.
        if ore in allowed:
            continue

        actions += 1
        if apply:
            try:
                refinery.move_subtype(
                    storage,
                    item.subtype,
                    amount=item.amount,
                    type_id=ORE_TYPE_ID,
                    source_inventory="inputInventory",
                )
                print(f"  {device_label(refinery)}: убрал лишнюю руду {format_amount(item.amount)} {ore} -> {device_label(storage)}")
            except Exception as exc:
                print(f"  [!] {refinery.name}: не смог убрать лишнюю руду {ore}: {exc}")
        else:
            print(f"  [plan] {device_label(refinery)}: убрать лишнюю руду {format_amount(item.amount)} {ore} -> {device_label(storage)}")
    return actions


def move_ore_to_refinery(
    refinery: RefineryDevice,
    source_list: list[ContainerDevice],
    config: dict[str, Any],
    desired_queue: list[dict[str, Any]],
    *,
    apply: bool,
) -> int:
    actions = 0
    allow_from_refineries = bool(config.get("allow_move_from_other_refineries", False))
    max_move_amount = amount_of(config.get("move_amount_per_ore"), 1000.0)
    input_amounts = current_input_ore_amounts(refinery, config)

    for slot_index, desired in enumerate(desired_queue):
        ore = desired["ore"]
        target_amount = min(amount_of(desired["amount"]), max_move_amount)
        already_in_input = input_amounts.get(ore, 0.0)
        need = max(0.0, target_amount - already_in_input)
        if need <= EPSILON:
            continue

        for container in source_list:
            if container.device_id == refinery.device_id:
                continue
            if isinstance(container, RefineryDevice) and not allow_from_refineries:
                continue
            try:
                items = container.items()
            except Exception:
                continue
            for item in items:
                if need <= EPSILON:
                    break
                if not is_ore_item(item, config["ore_order"]):
                    continue
                if normalize_ore_name(item.subtype) != ore:
                    continue
                amount = min(amount_of(item.amount), need)
                if amount <= EPSILON:
                    continue
                actions += 1
                ok = move_to_refinery_input_verified(
                    container,
                    refinery,
                    ore,
                    item.subtype,
                    amount,
                    config,
                    target_slot_id=slot_index,
                    apply=apply,
                )
                if ok:
                    need -= amount
                    input_amounts[ore] = input_amounts.get(ore, 0.0) + amount
                elif apply:
                    # Не уменьшаем need: фактического переноса не было.
                    pass
        if need > EPSILON:
            print(f"  [!] {refinery.name}: не нашёл достаточно {ore}, осталось недоложить {format_amount(need)}")
    return actions


def ordered_input_ore_items(refinery: RefineryDevice, config: dict[str, Any]) -> list[tuple[str, str, float]]:
    """Ore items from refinery input in telemetry order: (ore, subtype, amount)."""
    inv = refinery.input_inventory()
    items = inv.items if inv else []
    result: list[tuple[str, str, float]] = []
    for item in items:
        if not is_ore_item(item, config["ore_order"]):
            continue
        ore = normalize_ore_name(item.subtype)
        amount = amount_of(item.amount)
        if amount > EPSILON:
            result.append((ore, item.subtype, amount))
    return result


def force_first_input_ore(
    refinery: RefineryDevice,
    config: dict[str, Any],
    desired_ores: list[str],
    storage: ContainerDevice | None,
    *,
    apply: bool,
) -> int:
    if not config.get("force_priority_ore_to_first_input_slot", True):
        return 0
    if not desired_ores:
        return 0

    first_ore = desired_ores[0]
    input_ores = current_input_ores(refinery, config)
    if input_ores and input_ores[0] == first_ore:
        return 0
    if first_ore not in input_ores:
        return 0

    ordered_items = ordered_input_ore_items(refinery, config)
    blockers: list[tuple[str, str, float]] = []
    for ore, subtype, amount in ordered_items:
        if ore == first_ore:
            break
        blockers.append((ore, subtype, amount))

    # В текущем C# ContainerDevice перестановка внутри того же инвентаря ненадёжна:
    # если целевой слот занят другим типом руды, TryTransferItem возвращает success для
    # source==destination, но фактического переноса не делает, а RearrangeContainerSlots
    # часто не может сдвинуть занятый слот. Поэтому делаем рабочий обход:
    # 1) временно выносим руду, которая стоит перед приоритетной;
    # 2) ждём, что приоритетная руда станет первым стеком;
    # 3) по желанию возвращаем вынесенную руду назад, уже после приоритетной.
    if blockers and storage is None:
        if apply:
            print(f"  [!] {device_label(refinery)}: нет контейнера для временного выноса {', '.join(ore for ore, _, _ in blockers)}")
        else:
            print(f"  [plan] {device_label(refinery)}: нужен временный контейнер, чтобы вынести {', '.join(ore for ore, _, _ in blockers)}")
        return 1

    actions = max(1, len(blockers))

    if not apply:
        if blockers:
            print(
                f"  [plan] {device_label(refinery)}: временно вынести "
                f"{', '.join(f'{format_amount(amount)} {ore}' for ore, _, amount in blockers)} "
                f"в {device_label(storage) if storage else '?'}; {first_ore} станет первым"
            )
            if config.get("restore_displaced_lower_priority_ore", True):
                print(f"  [plan] {device_label(refinery)}: вернуть вынесенную руду назад после {first_ore}")
        else:
            print(f"  [plan] {device_label(refinery)}: поставить {first_ore} в первый слот входного инвентаря")
        return actions

    moved_blockers: list[tuple[str, str, float]] = []
    for ore, subtype, amount in blockers:
        ok = move_from_refinery_input_verified(
            refinery,
            storage,
            ore,
            subtype,
            amount,
            config,
            apply=apply,
        )
        if ok:
            moved_blockers.append((ore, subtype, amount))
        else:
            # Если первый блокирующий стек не удалось реально вынести, дальше порядок
            # не изменится. Не пишем ложный успех и не возвращаем то, что не выносили.
            break

    refresh_device(refinery, timeout=1.0)
    input_ores_after_remove = current_input_ores(refinery, config)

    # Если после выноса блокирующих стеков уран всё ещё не первый, пробуем старую
    # команду перестановки как fallback. Теперь целевой слот обычно уже не занят
    # нижним приоритетом, поэтому шанс успеха выше.
    if not input_ores_after_remove or input_ores_after_remove[0] != first_ore:
        try:
            refinery.move_subtype(
                refinery,
                first_ore,
                type_id=ORE_TYPE_ID,
                target_slot_id=0,
                source_inventory="inputInventory",
                destination_inventory="inputInventory",
            )
            time.sleep(0.15)
            refresh_device(refinery, timeout=1.0)
        except Exception as exc:
            print(f"  [!] {device_label(refinery)}: fallback-перестановка {first_ore} в первый слот не удалась: {exc}")

    input_ores_after_force = current_input_ores(refinery, config)
    if input_ores_after_force and input_ores_after_force[0] == first_ore:
        print(f"  {device_label(refinery)}: {first_ore} теперь первый во входном инвентаре")
    else:
        print(
            f"  [!] {device_label(refinery)}: {first_ore} всё ещё не первый; "
            f"вход сейчас: {', '.join(input_ores_after_force) if input_ores_after_force else '-'}"
        )

    if moved_blockers and config.get("restore_displaced_lower_priority_ore", False):
        for ore, subtype, amount in moved_blockers:
            try:
                ok = move_to_refinery_input_verified(
                    storage,
                    refinery,
                    ore,
                    subtype,
                    amount,
                    config,
                    target_slot_id=None,
                    apply=True,
                )
                if ok:
                    print(f"  {device_label(storage)} -> {device_label(refinery)}: вернул {format_amount(amount)} {ore} после приоритетной руды")
                else:
                    print(f"  [!] {device_label(storage)}: не смог вернуть {ore} в {device_label(refinery)}")
            except Exception as exc:
                print(f"  [!] {device_label(storage)}: не смог вернуть {ore} в {device_label(refinery)}: {exc}")
        refresh_device(refinery, timeout=1.0)
    elif moved_blockers:
        print(
            f"  {device_label(refinery)}: вынесенную нижнеприоритетную руду оставил в {device_label(storage)}, "
            "чтобы она не вернулась перед приоритетной"
        )

    return actions


def rewrite_refinery_queue(refinery: RefineryDevice, desired_queue: list[dict[str, Any]], *, apply: bool) -> int:
    actions = 0
    if apply:
        if refinery.queue():
            refinery.clear_queue()
            actions += 1
            time.sleep(0.1)
        for item in desired_queue:
            blueprint_id = f"MyObjectBuilder_BlueprintDefinition/{normalize_subtype(item['blueprint'])}"
            refinery.add_queue_item(blueprint_id, item["amount"])
            actions += 1
            time.sleep(0.05)
    else:
        print(f"  [plan] {refinery.name}: очистить очередь и поставить:")
        for item in desired_queue:
            print(f"    - {item['blueprint']} x{format_amount(item['amount'])} ({item['ore']})")
            actions += 1
    return actions


def apply_plan(plan: RefineryPlan, grid, config: dict[str, Any], *, apply: bool) -> int:
    refinery = plan.refinery
    sources = source_containers(grid, config)
    all_containers = find_containers(grid)
    storage = choose_temporary_storage(
        grid,
        config,
        refinery,
        ore=plan.desired_ores[0] if plan.desired_ores else None,
    )

    actions = 0
    if not plan.actions:
        print(f"{refinery.name}: OK, приоритет уже соблюдён")
        return 0

    print(f"{refinery.name}: actions={', '.join(plan.actions)}")
    if not plan.input_ok:
        actions += clear_wrong_input_ores(refinery, config, plan.desired_ores, storage, apply=apply)
        if apply:
            refresh_device(refinery, timeout=0.5)

        # Сначала освобождаем первый слот и гарантируем, что приоритетная руда стала
        # первой. После этого добираем недостающие нижние приоритеты обратно во вход.
        # Так Cobalt/Silver не исчезают из очистителя, но уже стоят после Uranium.
        actions += force_first_input_ore(refinery, config, plan.desired_ores, storage, apply=apply)
        if apply:
            refresh_device(refinery, timeout=0.5)

        actions += move_ore_to_refinery(refinery, all_containers, config, plan.desired_queue, apply=apply)
        if apply:
            refresh_device(refinery, timeout=0.5)

        # Контрольный проход: если добавление нижнего приоритета снова испортило первый
        # слот, ещё раз фиксируем первый слот. Обычно действий уже не будет.
        actions += force_first_input_ore(refinery, config, plan.desired_ores, storage, apply=apply)

    if not plan.queue_ok:
        actions += rewrite_refinery_queue(refinery, plan.desired_queue, apply=apply)

    if apply:
        refresh_device(refinery, timeout=1.0)
    return actions


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_inventory_report(ore_inventory: OreInventory, ore_order: list[str]) -> None:
    print("\nРуда на гриде:")
    for ore in ore_order:
        amount = ore_inventory.totals.get(ore, 0.0)
        if amount > EPSILON:
            print(f"  {ore}: {format_amount(amount)}")
    missing = [ore for ore in ore_order if ore_inventory.totals.get(ore, 0.0) <= EPSILON]
    if missing:
        print(f"  нет руды: {', '.join(missing)}")


def print_assembler_demand_report(demand: AssemblerDemand, available_ores: dict[str, float]) -> None:
    print("\nОценка очереди сборки:")
    if demand.notes:
        for note in demand.notes:
            print(f"  [note] {note}")
    if not demand.required_ingots:
        print("  очередь сборки не требует известных слитков или очередь пуста")
        return

    for ingot, required in sorted(demand.required_ingots.items()):
        available = demand.available_ingots.get(ingot, 0.0)
        shortage = demand.shortages.get(ingot, 0.0)
        ore = INGOT_TO_ORE.get(ingot, "?")
        ore_available = available_ores.get(ore, 0.0)
        status = "OK" if shortage <= EPSILON else f"дефицит {format_amount(shortage)}, руда {ore}={format_amount(ore_available)}"
        print(f"  {ingot}: нужно {format_amount(required)}, есть {format_amount(available)} — {status}")

    if demand.boosted_ores:
        print(f"  boost руд: {', '.join(demand.boosted_ores)}")


def print_plan(plan: RefineryPlan) -> None:
    current_queue = [queue_blueprint_subtype(entry) for entry in plan.current_queue]
    desired_queue = [entry["blueprint"] for entry in plan.desired_queue]
    print(f"\nОчиститель: {plan.refinery.name} ({plan.refinery.device_id})")
    print(f"  вход сейчас: {', '.join(plan.current_input_ores) if plan.current_input_ores else '-'}")
    print(f"  вход нужно:  {', '.join(plan.desired_ores) if plan.desired_ores else '-'}")
    print(f"  очередь сейчас: {', '.join(current_queue) if current_queue else '-'}")
    print(f"  очередь нужно:  {', '.join(desired_queue) if desired_queue else '-'}")
    print(f"  queue_ok={plan.queue_ok} input_ok={plan.input_ok}")
    if plan.actions:
        print(f"  действия: {', '.join(plan.actions)}")
    else:
        print("  действия не нужны")


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------


def run_once(grid, config: dict[str, Any], *, apply: bool, from_assembler_queue: bool) -> int:
    refineries = find_refineries(grid)
    if not refineries:
        print("Очистители не найдены на гриде")
        return 1

    print(f"Скрипт: {SCRIPT_VERSION}")
    print(f"Файл: {Path(__file__).resolve()}")

    for refinery in refineries:
        refresh_device(refinery, timeout=1.0)

    ore_inventory = collect_ore_inventory(grid, config)
    assembler_demand = analyze_assembler_queue(grid, config) if from_assembler_queue else None
    effective_order = build_effective_ore_order(config, assembler_demand)
    desired_queue = build_desired_queue(config, ore_inventory.totals, effective_order)

    print(f"Грид: {grid.name}")
    print(f"Очистителей: {len(refineries)}")
    print(f"Режим: {'APPLY' if apply else 'EVALUATE'}")
    print(f"Базовый приоритет: {', '.join(config['ore_order'])}")
    if effective_order != config["ore_order"]:
        print(f"Фактический приоритет: {', '.join(effective_order)}")

    print_inventory_report(ore_inventory, effective_order)
    if assembler_demand is not None:
        print_assembler_demand_report(assembler_demand, ore_inventory.totals)

    if not desired_queue:
        print("\nНет доступной руды из списка приоритетов. Очереди очистителей не меняю.")
        return 0

    print("\nЖелаемая очередь для очистителей:")
    for item in desired_queue:
        print(f"  {item['ore']}: {item['blueprint']} x{format_amount(item['amount'])}")

    plans = [build_plan(refinery, config, desired_queue) for refinery in refineries]
    for plan in plans:
        print_plan(plan)

    total_actions = 0
    print("\nПрименение:" if apply else "\nОценка действий:")
    for plan in plans:
        total_actions += apply_plan(plan, grid, config, apply=apply)

    print(f"\nИтого действий: {total_actions}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление приоритетом всех очистителей на гриде")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="JSON-конфиг приоритетов")
    parser.add_argument("--write-default-config", action="store_true", help="Записать конфиг по умолчанию и выйти")
    parser.add_argument("--evaluate", action="store_true", help="Только оценить действия, ничего не менять")
    parser.add_argument("--apply", action="store_true", help="Применить изменения в очистителях")
    parser.add_argument("--from-assembler-queue", action="store_true", help="Поднимать приоритет руд по очереди сборки ассемблеров")
    parser.add_argument("--restore-displaced", action="store_true", help="Возвращать временно вынесенную нижнеприоритетную руду обратно во вход очистителя")
    parser.add_argument("--no-restore-displaced", action="store_true", help="Не возвращать временно вынесенную нижнеприоритетную руду обратно во вход очистителя")
    parser.add_argument("--loop", action="store_true", help="Повторять цикл постоянно")
    parser.add_argument("--interval", type=float, default=30.0, help="Пауза между циклами в режиме --loop")
    args = parser.parse_args()

    config_path = Path(args.config)
    if args.write_default_config:
        write_default_config(config_path)
        print(f"Конфиг записан: {config_path}")
        return

    if args.apply and args.evaluate:
        print("Нельзя одновременно использовать --apply и --evaluate")
        sys.exit(2)
    apply = bool(args.apply)
    if not apply and not args.evaluate:
        print("Флаг --apply не указан, работаю в безопасном режиме оценки (--evaluate).")

    config = load_config(config_path)
    if args.restore_displaced and args.no_restore_displaced:
        print("Нельзя одновременно использовать --restore-displaced и --no-restore-displaced")
        sys.exit(2)
    if args.restore_displaced:
        config["restore_displaced_lower_priority_ore"] = True
    if args.no_restore_displaced:
        config["restore_displaced_lower_priority_ore"] = False

    grid = prepare_grid(args.grid)
    try:
        while True:
            code = run_once(grid, config, apply=apply, from_assembler_queue=args.from_assembler_queue)
            if not args.loop:
                sys.exit(code)
            time.sleep(max(1.0, float(args.interval)))
    finally:
        close(grid)


if __name__ == "__main__":
    main()
