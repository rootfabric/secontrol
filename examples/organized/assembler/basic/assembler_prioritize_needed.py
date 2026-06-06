#!/usr/bin/env python3
"""Prioritize assembler queue for components needed right now.

The script is designed for Space Engineers automation through secontrol.
It rebuilds the assembler queue so urgent components go first, while preserving
all other queued items after them.

Typical usage:

    python examples/organized/assembler/basic/assembler_prioritize_needed.py --grid farpost --need InteriorPlate=2 --dry-run
    python examples/organized/assembler/basic/assembler_prioritize_needed.py --grid farpost --need InteriorPlate=2

If a BuildAndRepair/Nanobot block exposes missing item telemetry, the script can
also try to read it automatically:

    python examples/organized/assembler/basic/assembler_prioritize_needed.py --grid farpost --from-build-repair --dry-run

Important: reordering a Space Engineers assembler queue requires clearing and
re-adding the queue, because there is no stable insert-at-front command exposed
by the current wrapper. Always run --dry-run first.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Iterable


def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root(Path(__file__).resolve())
ENV_PATH = REPO_ROOT / ".env"
if ENV_PATH.exists():
    with ENV_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

SRC_PATH = REPO_ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from secontrol.common import close, prepare_grid  # noqa: E402
from secontrol.devices.assembler_device import AssemblerDevice  # noqa: E402


EPSILON = 1e-6

# Blueprint subtype -> inventory subtype. This mirrors the production scripts and
# is kept here so the script can accept both inventory names and blueprint names.
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

INVENTORY_TO_BLUEPRINT = {v.lower(): k for k, v in BLUEPRINT_TO_INVENTORY.items()}

# Human aliases, including the Russian names usually shown in terminal UI.
ALIASES = {
    "steelplate": "SteelPlate",
    "steel plate": "SteelPlate",
    "стальная пластина": "SteelPlate",
    "стальнаяпластина": "SteelPlate",
    "interiorplate": "InteriorPlate",
    "interior plate": "InteriorPlate",
    "внутренняя пластина": "InteriorPlate",
    "внутренняяпластина": "InteriorPlate",
    "smalltube": "SmallTube",
    "small tube": "SmallTube",
    "малая труба": "SmallTube",
    "малаятруба": "SmallTube",
    "largetube": "LargeTube",
    "large tube": "LargeTube",
    "большая труба": "LargeTube",
    "большая труба": "LargeTube",
    "большаятруба": "LargeTube",
    "motor": "MotorComponent",
    "motorcomponent": "MotorComponent",
    "motor component": "MotorComponent",
    "двигатель": "MotorComponent",
    "construction": "ConstructionComponent",
    "constructioncomponent": "ConstructionComponent",
    "construction component": "ConstructionComponent",
    "construction comp": "ConstructionComponent",
    "строительный компонент": "ConstructionComponent",
    "строительныйкомпонент": "ConstructionComponent",
    "metalgrid": "MetalGrid",
    "metal grid": "MetalGrid",
    "металлическая решетка": "MetalGrid",
    "металлическаярешетка": "MetalGrid",
    "powercell": "PowerCell",
    "power cell": "PowerCell",
    "энергоячейка": "PowerCell",
    "battery cell": "PowerCell",
    "radiocommunication": "RadioCommunicationComponent",
    "radiocommunicationcomponent": "RadioCommunicationComponent",
    "radio communication": "RadioCommunicationComponent",
    "радиокоммуникация": "RadioCommunicationComponent",
    "detector": "DetectorComponent",
    "detectorcomponent": "DetectorComponent",
    "компонент детектора": "DetectorComponent",
    "medical": "MedicalComponent",
    "medicalcomponent": "MedicalComponent",
    "медицинский компонент": "MedicalComponent",
    "display": "Display",
    "дисплей": "Display",
    "bulletproofglass": "BulletproofGlass",
    "bulletproof glass": "BulletproofGlass",
    "бронестекло": "BulletproofGlass",
    "computer": "ComputerComponent",
    "computercomponent": "ComputerComponent",
    "computer component": "ComputerComponent",
    "компьютер": "ComputerComponent",
    "reactor": "ReactorComponent",
    "reactorcomponent": "ReactorComponent",
    "reactor component": "ReactorComponent",
    "компонент реактора": "ReactorComponent",
    "thrust": "ThrustComponent",
    "thrustcomponent": "ThrustComponent",
    "thruster": "ThrustComponent",
    "thruster component": "ThrustComponent",
    "компонент двигателя": "ThrustComponent",
    "gravitygenerator": "GravityGeneratorComponent",
    "gravitygeneratorcomponent": "GravityGeneratorComponent",
    "gravity generator": "GravityGeneratorComponent",
    "гравитационный компонент": "GravityGeneratorComponent",
    "solarcell": "SolarCell",
    "solar cell": "SolarCell",
    "солнечная ячейка": "SolarCell",
    "superconductor": "Superconductor",
    "сверхпроводник": "Superconductor",
    "girder": "GirderComponent",
    "girdercomponent": "GirderComponent",
    "балка": "GirderComponent",
    "explosives": "ExplosivesComponent",
    "explosive": "ExplosivesComponent",
    "explosivescomponent": "ExplosivesComponent",
    "взрывчатка": "ExplosivesComponent",
}


def normalize_key(text: Any) -> str:
    value = str(text or "").strip()
    value = value.replace("MyObjectBuilder_BlueprintDefinition/", "")
    value = value.replace("MyObjectBuilder_Component/", "")
    value = value.replace("Component/", "")
    value = value.replace("BlueprintDefinition/", "")
    value = value.replace("_", " ").replace("-", " ")
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def compact_key(text: Any) -> str:
    return re.sub(r"[\s_\-.]+", "", normalize_key(text))


def blueprint_subtype(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def canonical_component(value: Any) -> str | None:
    """Return canonical blueprint subtype for a component-ish name."""
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    subtype = blueprint_subtype(raw)
    norm = normalize_key(subtype)
    compact = compact_key(subtype)

    for candidate in (norm, compact, normalize_key(raw), compact_key(raw)):
        if candidate in ALIASES:
            return ALIASES[candidate]
        if candidate.lower() in INVENTORY_TO_BLUEPRINT:
            return INVENTORY_TO_BLUEPRINT[candidate.lower()]

    for bp in BLUEPRINT_TO_INVENTORY:
        if compact == compact_key(bp):
            return bp

    for inv, bp in INVENTORY_TO_BLUEPRINT.items():
        if compact == compact_key(inv):
            return bp

    return None


def canonical_blueprint_id(component: str) -> str:
    component = canonical_component(component) or blueprint_subtype(component)
    if "/" in component:
        return component
    return f"MyObjectBuilder_BlueprintDefinition/{component}"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def format_amount(value: float) -> str:
    value = float(value)
    if math.isclose(value, round(value), abs_tol=EPSILON):
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def parse_need_entry(text: str) -> tuple[str, float]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty --need entry")

    if "=" in raw:
        name, amount = raw.split("=", 1)
    elif ":" in raw:
        name, amount = raw.rsplit(":", 1)
    elif "," in raw:
        name, amount = raw.rsplit(",", 1)
    else:
        name, amount = raw, "1"

    component = canonical_component(name.strip())
    if not component:
        raise ValueError(f"unknown component name: {name!r}")

    qty = safe_float(amount, 0.0)
    if qty <= EPSILON:
        qty = 1.0
    return component, qty


def load_needed_file(path: Path) -> OrderedDict[str, float]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    result: OrderedDict[str, float] = OrderedDict()

    def add(name: Any, amount: Any) -> None:
        component = canonical_component(name)
        if not component:
            return
        qty = safe_float(amount, 0.0)
        if qty <= EPSILON:
            return
        result[component] = result.get(component, 0.0) + qty

    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            for item in data["items"]:
                if isinstance(item, dict):
                    add(
                        item.get("blueprintSubtype")
                        or item.get("subtype")
                        or item.get("name")
                        or item.get("displayName"),
                        item.get("amount") or item.get("count") or item.get("missing") or item.get("needed"),
                    )
        else:
            for key, value in data.items():
                add(key, value)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                add(
                    item.get("blueprintSubtype")
                    or item.get("subtype")
                    or item.get("name")
                    or item.get("displayName"),
                    item.get("amount") or item.get("count") or item.get("missing") or item.get("needed"),
                )
            elif isinstance(item, str):
                component, qty = parse_need_entry(item)
                result[component] = result.get(component, 0.0) + qty

    return result


def queue_entry_blueprint(entry: dict[str, Any]) -> str:
    for key in ("blueprintId", "blueprint", "id"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    for key in ("blueprintSubtype", "subtype"):
        value = str(entry.get(key) or "").strip()
        if value:
            return canonical_blueprint_id(value)
    value = str(entry.get("itemId") or "").strip()
    if value:
        return value
    return ""


def queue_entry_amount(entry: dict[str, Any]) -> float:
    amount = safe_float(entry.get("amount"), 0.0)
    return max(0.0, amount)


def queue_entry_component(entry: dict[str, Any]) -> str | None:
    bp = queue_entry_blueprint(entry)
    return canonical_component(bp)


def find_assemblers(grid, *, assembler_id: str | None = None, name: str | None = None) -> list[AssemblerDevice]:
    assemblers = [d for d in grid.devices.values() if isinstance(d, AssemblerDevice)]

    if assembler_id:
        needle = str(assembler_id).strip()
        assemblers = [a for a in assemblers if str(getattr(a, "device_id", "")) == needle]

    if name:
        needle = name.lower().strip()
        assemblers = [a for a in assemblers if needle in str(getattr(a, "name", "") or "").lower()]

    return assemblers


def refresh_assembler(assembler: AssemblerDevice, *, timeout: float = 1.0, blueprints: bool = True) -> None:
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        try:
            assembler.update()
        except Exception:
            pass
    if blueprints:
        try:
            assembler.wait_for_blueprints(timeout=2.0)
        except Exception:
            pass


def is_build_repair_like(device: Any) -> bool:
    text = " ".join(
        str(x or "")
        for x in (
            getattr(device, "device_type", None),
            getattr(device, "name", None),
            getattr(getattr(device, "metadata", None), "device_type", None),
            getattr(getattr(device, "metadata", None), "extra", {}).get("type") if getattr(device, "metadata", None) else None,
            getattr(getattr(device, "metadata", None), "extra", {}).get("subtype") if getattr(device, "metadata", None) else None,
        )
    ).lower()

    return any(
        token in text
        for token in (
            "buildandrepair",
            "build and repair",
            "nanobot",
            "shipwelder",
            "welder",
            "nanobot_build_and_repair",
        )
    )


MISSING_KEY_RE = re.compile(r"missing|needed|required|shortage|lack|need", re.IGNORECASE)
AMOUNT_KEYS = ("amount", "count", "missing", "needed", "required", "quantity", "qty", "value")
NAME_KEYS = ("blueprintSubtype", "subtype", "subType", "name", "displayName", "item", "component", "typeId")


def extract_missing_items_from_payload(payload: Any) -> OrderedDict[str, float]:
    found: OrderedDict[str, float] = OrderedDict()

    def add(name: Any, amount: Any) -> None:
        component = canonical_component(name)
        if not component:
            return
        qty = safe_float(amount, 0.0)
        if qty <= EPSILON:
            return
        found[component] = found.get(component, 0.0) + qty

    def visit(obj: Any, *, context_missing: bool = False, depth: int = 0) -> None:
        if depth > 8:
            return

        if isinstance(obj, dict):
            name = None
            amount = None
            for key in NAME_KEYS:
                if key in obj and obj.get(key) not in (None, ""):
                    name = obj.get(key)
                    break
            for key in AMOUNT_KEYS:
                if key in obj and obj.get(key) not in (None, ""):
                    amount = obj.get(key)
                    break
            if context_missing and name is not None and amount is not None:
                add(name, amount)

            if context_missing:
                for key, value in obj.items():
                    if isinstance(value, (int, float)):
                        add(key, value)

            for key, value in obj.items():
                child_context = context_missing or bool(MISSING_KEY_RE.search(str(key)))
                visit(value, context_missing=child_context, depth=depth + 1)
            return

        if isinstance(obj, list):
            for item in obj:
                visit(item, context_missing=context_missing, depth=depth + 1)
            return

    visit(payload, context_missing=False)
    return found


def discover_needed_from_build_repair(grid, *, name_filter: str | None = None, timeout: float = 1.0) -> OrderedDict[str, float]:
    total: OrderedDict[str, float] = OrderedDict()
    candidates = []

    for device in grid.devices.values():
        if not is_build_repair_like(device):
            continue
        if name_filter and name_filter.lower() not in str(getattr(device, "name", "") or "").lower():
            continue
        candidates.append(device)

    if not candidates:
        return total

    print(f"Build/Repair devices scanned: {len(candidates)}")
    for device in candidates:
        try:
            if hasattr(device, "wait_for_telemetry"):
                device.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
            elif hasattr(device, "update"):
                device.update()
        except Exception:
            pass

        telemetry = getattr(device, "telemetry", None) or {}
        found = extract_missing_items_from_payload(telemetry)
        print(f"  {getattr(device, 'name', 'device')} ({getattr(device, 'device_id', '?')}): {len(found)} missing item groups found")
        for component, amount in found.items():
            total[component] = total.get(component, 0.0) + amount

    return total


def build_new_queue(
    current_queue: list[dict[str, Any]],
    needed: OrderedDict[str, float],
    *,
    add_missing: bool = True,
) -> list[tuple[str, float, str]]:
    """Return [(component_or_blueprint, amount, reason), ...]."""
    needed_totals: dict[str, float] = defaultdict(float)
    other_items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for entry in current_queue:
        blueprint = queue_entry_blueprint(entry)
        amount = queue_entry_amount(entry)
        if not blueprint or amount <= EPSILON:
            continue

        component = queue_entry_component(entry)
        if component and component in needed:
            needed_totals[component] += amount
            continue

        subtype = blueprint_subtype(blueprint) or blueprint
        key = subtype.lower()
        if key not in other_items:
            other_items[key] = {"blueprint": blueprint, "amount": 0.0, "subtype": subtype}
        other_items[key]["amount"] += amount

    result: list[tuple[str, float, str]] = []

    for component, required_amount in needed.items():
        queued_amount = needed_totals.get(component, 0.0)
        if add_missing:
            amount = max(queued_amount, float(required_amount))
            reason = f"needed now: required={format_amount(required_amount)}, queued={format_amount(queued_amount)}"
        else:
            amount = queued_amount
            reason = f"existing urgent queue only: queued={format_amount(queued_amount)}"
        if amount > EPSILON:
            result.append((component, amount, reason))

    for data in other_items.values():
        amount = safe_float(data.get("amount"), 0.0)
        if amount > EPSILON:
            result.append((str(data["blueprint"]), amount, "preserved from old queue"))

    return result


def queue_signature(queue: Iterable[tuple[str, float, str]]) -> tuple[tuple[str, int], ...]:
    sig = []
    for bp, amount, _ in queue:
        sig.append((blueprint_subtype(bp).lower(), int(round(float(amount) * 1000))))
    return tuple(sig)


def print_current_queue(queue: list[dict[str, Any]]) -> None:
    if not queue:
        print("Current queue: empty")
        return
    print(f"Current queue: {len(queue)} entries")
    for entry in queue[:40]:
        bp = queue_entry_blueprint(entry)
        amount = queue_entry_amount(entry)
        component = queue_entry_component(entry)
        label = component or blueprint_subtype(bp) or bp or "?"
        idx = entry.get("index", "?")
        print(f"  [{idx}] {label} x{format_amount(amount)}")
    if len(queue) > 40:
        print(f"  ... {len(queue) - 40} more entries")


def apply_queue_plan(
    assembler: AssemblerDevice,
    plan: list[tuple[str, float, str]],
    *,
    verify_timeout: float = 3.0,
    delay: float = 0.2,
    set_assemble_mode: bool = True,
) -> int:
    if set_assemble_mode:
        print("Switching assembler to assemble mode...")
        if hasattr(assembler, "set_disassemble_verified"):
            if assembler.set_disassemble_verified(False, timeout=verify_timeout):
                print("  assemble mode confirmed")
            else:
                print("  WARNING: assemble mode was not confirmed")
        else:
            assembler.set_disassemble(False)

    print("Clearing old queue...")
    if hasattr(assembler, "clear_queue_verified"):
        if not assembler.clear_queue_verified(timeout=verify_timeout):
            print("ERROR: queue clear was not confirmed")
            return 2
    else:
        sent = assembler.clear_queue()
        if sent <= 0:
            print("ERROR: clear_queue command was not sent")
            return 2
        time.sleep(max(0.2, delay))

    failed: list[tuple[str, float]] = []
    for blueprint, amount, reason in plan:
        blueprint_id = assembler.resolve_blueprint_id(blueprint, request=True)
        print(f"  add first-order queue: {blueprint_subtype(blueprint_id)} x{format_amount(amount)} — {reason}")
        if hasattr(assembler, "add_queue_item_verified"):
            ok = assembler.add_queue_item_verified(blueprint_id, amount, timeout=verify_timeout, disassemble=False)
            if not ok:
                failed.append((blueprint_id, amount))
        else:
            sent = assembler.add_queue_item(blueprint_id, amount, disassemble=False)
            if sent <= 0:
                failed.append((blueprint_id, amount))
        if delay > 0:
            time.sleep(delay)

    if failed:
        print("ERROR: failed to confirm queued items:")
        for blueprint, amount in failed:
            print(f"  - {blueprint_subtype(blueprint)} x{format_amount(amount)}")
        return 3

    return 0


def select_assembler(assemblers: list[AssemblerDevice]) -> AssemblerDevice | None:
    if not assemblers:
        return None
    for assembler in assemblers:
        telemetry = assembler.telemetry or {}
        enabled = bool(telemetry.get("enabled", telemetry.get("isWorking", True)))
        functional = bool(telemetry.get("isFunctional", True))
        if enabled and functional:
            return assembler
    return assemblers[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Move currently needed components to the front of assembler queue")
    parser.add_argument("--grid", required=True, help="Grid name or ID")
    parser.add_argument("--assembler-id", help="Exact assembler entity ID")
    parser.add_argument("--assembler-name", help="Substring of assembler name")
    parser.add_argument("--need", action="append", default=[], help="Needed component and amount, e.g. InteriorPlate=2 or 'Внутренняя пластина=2'. Can be repeated")
    parser.add_argument("--needed-file", help="JSON file with needed components: {'InteriorPlate': 2} or [{'subtype':'InteriorPlate','amount':2}]")
    parser.add_argument("--from-build-repair", action="store_true", default=True, help="Try to read missing components from BuildAndRepair/Nanobot telemetry; enabled by default")
    parser.add_argument("--no-from-build-repair", dest="from_build_repair", action="store_false", help="Do not scan BuildAndRepair/Nanobot telemetry")
    parser.add_argument("--build-repair-name", help="Substring filter for BuildAndRepair/Nanobot block name")
    parser.add_argument("--no-add-missing", dest="add_missing", action="store_false", default=True, help="Only move already queued urgent components to the front; do not add missing amounts")
    parser.add_argument("--dry-run", action="store_true", help="Print queue rebuild plan but do not change queue")
    parser.add_argument("--verify-timeout", type=float, default=3.0, help="Seconds to wait for each queue command confirmation")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between queue commands")
    parser.add_argument("--no-set-assemble-mode", dest="set_assemble_mode", action="store_false", default=True, help="Do not force DisassembleEnabled=False")
    parser.add_argument("--telemetry-timeout", type=float, default=1.0, help="Telemetry refresh timeout")
    args = parser.parse_args()

    needed: OrderedDict[str, float] = OrderedDict()

    for entry in args.need:
        component, amount = parse_need_entry(entry)
        needed[component] = needed.get(component, 0.0) + amount

    if args.needed_file:
        file_needed = load_needed_file(Path(args.needed_file))
        for component, amount in file_needed.items():
            needed[component] = needed.get(component, 0.0) + amount

    grid = prepare_grid(args.grid)
    try:
        if args.from_build_repair:
            auto_needed = discover_needed_from_build_repair(
                grid,
                name_filter=args.build_repair_name,
                timeout=args.telemetry_timeout,
            )
            for component, amount in auto_needed.items():
                needed[component] = needed.get(component, 0.0) + amount

        print(f"Grid: {grid.name}")

        if not needed:
            print("No currently needed components found.")
            print("Use --need InteriorPlate=2, or pass --needed-file missing.json, or check that BuildAndRepair telemetry exposes missing items.")
            sys.exit(2)

        print("Needed components:")
        for component, amount in needed.items():
            print(f"  - {component} x{format_amount(amount)}")

        assemblers = find_assemblers(grid, assembler_id=args.assembler_id, name=args.assembler_name)
        if not assemblers:
            print("ERROR: no assembler matched selection")
            sys.exit(1)

        assembler = select_assembler(assemblers)
        if assembler is None:
            print("ERROR: no assembler selected")
            sys.exit(1)

        refresh_assembler(assembler, timeout=args.telemetry_timeout, blueprints=True)

        print(f"Assembler: {assembler.name} ({assembler.device_id})")
        print(
            f"  mode={assembler.mode() or 'unknown'} "
            f"disassemble={bool((assembler.telemetry or {}).get('disassembleEnabled', False))} "
            f"queue_items={len(assembler.queue())}"
        )

        current_queue = assembler.queue()
        print_current_queue(current_queue)

        plan = build_new_queue(current_queue, needed, add_missing=args.add_missing)
        if not plan:
            print("Nothing to queue after plan calculation.")
            sys.exit(0)

        print("\nNew queue plan:")
        for i, (blueprint, amount, reason) in enumerate(plan, start=1):
            print(f"  [{i}] {blueprint_subtype(blueprint)} x{format_amount(amount)} — {reason}")

        old_sig = queue_signature(
            [
                (queue_entry_blueprint(entry), queue_entry_amount(entry), "old")
                for entry in current_queue
                if queue_entry_blueprint(entry) and queue_entry_amount(entry) > EPSILON
            ]
        )
        new_sig = queue_signature(plan)

        if old_sig == new_sig:
            print("\nQueue is already in the requested priority order.")
            sys.exit(0)

        if args.dry_run:
            print("\n[dry-run] Queue was not changed. Run without --dry-run to apply.")
            sys.exit(0)

        code = apply_queue_plan(
            assembler,
            plan,
            verify_timeout=args.verify_timeout,
            delay=args.delay,
            set_assemble_mode=args.set_assemble_mode,
        )

        refresh_assembler(assembler, timeout=args.telemetry_timeout, blueprints=False)
        print("\nFinal queue:")
        print_current_queue(assembler.queue())
        sys.exit(code)

    finally:
        close(grid)


if __name__ == "__main__":
    main()
