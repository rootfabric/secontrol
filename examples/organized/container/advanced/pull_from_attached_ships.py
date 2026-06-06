#!/usr/bin/env python3
"""
Слить ВСЕ ресурсы со всех пристыкованных кораблей в инвентарь базы.

Скрипт запускается НА СТОРОНЕ БАЗЫ. База сама находит припаркованные корабли
по своим коннекторам (status == 'Connected') и поочерёдно вытягивает из них
все предметы (контейнеры, кокпиты, буры, рефайнери, ассемблеры) в указанный
контейнер базы. Контейнер назначения автоматически переключается на
свободный, если текущий заполнен.

Использование:
    # Слить всё со всех пристыкованных кораблей в контейнер с тегом [cargo]
    python examples/organized/container/advanced/pull_from_attached_ships.py \
        --base-grid skynet-baza1 --target-tag cargo

    # Использовать конкретный контейнер по имени
    python examples/organized/container/advanced/pull_from_attached_ships.py \
        --base-grid DroneBase --target-container "Main Storage"

    # Только посмотреть, что есть на пристыкованных, без переноса
    python examples/organized/container/advanced/pull_from_attached_ships.py \
        --base-grid skynet-baza1 --dry-run

    # Не переносить руду (оставить на корабле для переплавки)
    python examples/organized/container/advanced/pull_from_attached_ships.py \
        --base-grid skynet-baza1 --target-tag cargo --exclude-type ore
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

from secontrol.common import resolve_owner_id
from secontrol.redis_client import RedisEventClient
from secontrol import Grid
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.devices.ship_drill_device import ShipDrillDevice
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.devices.assembler_device import AssemblerDevice


DEFAULT_BASE_GRID = "DroneBase"


def _refresh_connectors(grid: Grid) -> list[ConnectorDevice]:
    """Update all connectors on the grid and return them."""
    connectors = list(grid.find_devices_by_type(ConnectorDevice))
    for c in connectors:
        c.send_command({"cmd": "update"})
    time.sleep(0.3)
    return connectors


def _is_connected(connector: ConnectorDevice) -> bool:
    """A connector is considered docked when status == 'Connected' and
    a foreign grid is referenced via otherConnectorGridId."""
    if not connector.telemetry:
        return False
    status = str(connector.telemetry.get("connectorStatus", "")).strip()
    other = connector.telemetry.get("otherConnectorGridId")
    return status == "Connected" and other is not None


def find_docked_grids(base: Grid, base_id: str) -> list[dict]:
    """Inspect base connectors and return descriptors of every distinct
    foreign grid currently docked to the base."""
    seen: dict[str, dict] = {}
    for c in _refresh_connectors(base):
        if not _is_connected(c):
            continue
        other_id = str(c.telemetry.get("otherConnectorGridId"))
        if not other_id or other_id == str(base_id):
            continue
        other_connector_id = c.telemetry.get("otherConnectorId")
        entry = seen.setdefault(
            other_id,
            {
                "other_grid_id": other_id,
                "other_connector_id": str(other_connector_id) if other_connector_id is not None else None,
                "base_connector": c,
            },
        )
        # If we later see a different base connector, prefer the one with
        # an explicit otherConnectorId (more reliable).
        if other_connector_id is not None and entry.get("other_connector_id") in (None, "None"):
            entry["other_connector_id"] = str(other_connector_id)
            entry["base_connector"] = c
    return list(seen.values())


def select_target_container(
    candidates: list[ContainerDevice],
    name: str | None,
    tag: str | None,
) -> ContainerDevice:
    """Pick the initial destination container by name, tag, or fallback."""
    if name:
        for c in candidates:
            if c.name == name:
                return c
    if tag:
        for c in candidates:
            if c.has_tag(tag):
                return c
    return candidates[0] if candidates else None


def pick_next_container(
    current: ContainerDevice,
    candidates: list[ContainerDevice],
) -> ContainerDevice | None:
    """Return `current` if it has free space, otherwise the first candidate
    with free space, else None when everything is full."""
    current.send_command({"cmd": "update"})
    time.sleep(0.1)
    if current.capacity()["fillRatio"] < 1.0:
        return current
    for cont in candidates:
        if cont.device_id == current.device_id:
            continue
        cont.send_command({"cmd": "update"})
        time.sleep(0.1)
        if cont.capacity()["fillRatio"] < 1.0:
            print(f"  → переключаюсь на контейнер {cont.name}")
            return cont
    return None


def iter_source_inventories(
    device,
    exclude_types: set[str],
    exclude_subtypes: set[str],
) -> Iterable[tuple[str, object | None]]:
    """Yield (label, source_inventory_or_None) pairs we should drain from
    this device. `source_inventory=None` means "use the default inventory"."""
    if isinstance(device, RefineryDevice):
        for label in ("input", "output"):
            inv = device.input_inventory() if label == "input" else device.output_inventory()
            if inv is None or not getattr(inv, "items", None):
                continue
            if _inventory_fully_blacklisted(inv, exclude_types, exclude_subtypes):
                continue
            yield label, inv
        return

    # Assembler / container / cockpit / drill — single inventory each
    yield (None, None)


def _inventory_fully_blacklisted(inv, exclude_types: set[str], exclude_subtypes: set[str]) -> bool:
    items = getattr(inv, "items", None) or []
    if not items:
        return True
    for it in items:
        if (it.type or "").lower() in exclude_types:
            continue
        if (it.subtype or "").lower() in exclude_subtypes:
            continue
        return False
    return True


def drain_device(
    device,
    candidates: list[ContainerDevice],
    target: ContainerDevice,
    exclude_types: set[str],
    exclude_subtypes: set[str],
    dry_run: bool,
) -> int:
    """Drain one device into `target` (rotating candidates if full)."""
    moved = 0
    for label, source_inv in iter_source_inventories(device, exclude_types, exclude_subtypes):
        items = device.items(source_inv) if source_inv else device.items()
        if not items:
            continue

        inv_desc = f" ({label})" if label else ""
        print(f"\n>>> {device.name}{inv_desc}  [{device.device_type}]")
        for it in items:
            type_str = f"{it.type}:" if it.type else ""
            print(f"    {it.amount:,.0f} x {type_str}{it.display_name or it.subtype}")
            if (it.type or "").lower() in exclude_types:
                continue
            if (it.subtype or "").lower() in exclude_subtypes:
                continue

        if dry_run:
            continue

        chosen = pick_next_container(target, candidates)
        if chosen is None:
            print("    [!!] все контейнеры базы заполнены, пропускаю")
            target = candidates[0] if candidates else target
            continue
        target = chosen

        try:
            result = device.move_all(target, source_inventory=source_inv)
            time.sleep(0.4)
            device.send_command({"cmd": "update"})
            time.sleep(0.1)
            remaining = device.items(source_inv) if source_inv else device.items()
            if result > 0:
                moved += result
                print(f"    [OK] перенесено {result} тип(ов) → {target.name}")
            else:
                print("    [!!] команда ушла, но сервер не подтвердил перенос")
            if remaining:
                print("    [!!] осталось в источнике:")
                for it in remaining:
                    print(f"        {it.amount:,.0f} x {it.display_name or it.subtype}")
        except Exception as exc:
            print(f"    [ERROR] {exc}")
    return moved


def gather_drainable_devices(grid: Grid, exclude_connector_id: str | None) -> list:
    """Return all inventory-bearing devices on `grid` that we want to drain,
    minus the connector used for the transfer (so the connection survives)."""
    devices: list = []
    for cls in (ContainerDevice, CockpitDevice, ShipDrillDevice, RefineryDevice, AssemblerDevice):
        devices.extend(grid.find_devices_by_type(cls))

    if exclude_connector_id:
        devices = [d for d in devices if str(d.device_id) != str(exclude_connector_id)]
    return devices


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Слить все ресурсы со всех пристыкованных кораблей в инвентарь базы.",
    )
    parser.add_argument("--base-grid", default=DEFAULT_BASE_GRID,
                        help=f"Имя или ID грида-базы (по умолчанию: {DEFAULT_BASE_GRID})")
    parser.add_argument("--target-container", default=None,
                        help="Имя конкретного контейнера на базе для приёма")
    parser.add_argument("--target-tag", default=None,
                        help="Тег контейнера на базе (например 'cargo', 'ingot')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать содержимое пристыкованных, без переноса")
    parser.add_argument("--exclude-type", action="append", default=[],
                        metavar="TYPE",
                        help="Не переносить предметы этого типа (можно несколько раз, "
                             "например: --exclude-type ore)")
    parser.add_argument("--exclude-subtype", action="append", default=[],
                        metavar="SUBTYPE",
                        help="Не переносить предметы с этим subtype (можно несколько раз)")
    args = parser.parse_args()

    exclude_types = {t.lower() for t in args.exclude_type}
    exclude_subtypes = {s.lower() for s in args.exclude_subtype}

    owner_id = resolve_owner_id()
    client = RedisEventClient()

    try:
        all_grids = client.list_grids(owner_id)
        base_info = next((g for g in all_grids
                          if g.get("name") == args.base_grid
                          or str(g.get("id")) == str(args.base_grid)), None)
        if base_info is None:
            print(f"База '{args.base_grid}' не найдена.", file=sys.stderr)
            print(f"Доступные гриды: {[g.get('name') for g in all_grids]}", file=sys.stderr)
            return 1

        base = Grid(client, owner_id, str(base_info["id"]), owner_id,
                    name=base_info.get("name"))
        base_id = str(base_info["id"])
        print(f"=== База: {base.name} (id={base_id}) ===\n")

        containers = list(base.find_devices_by_type(ContainerDevice))
        if not containers:
            print("На базе нет ни одного контейнера — некуда сливать.", file=sys.stderr)
            return 1
        target = select_target_container(containers, args.target_container, args.target_tag)
        if target is None:
            print("Контейнер-приёмник не найден (проверь --target-container / --target-tag).",
                  file=sys.stderr)
            return 1
        print(f"Контейнер-приёмник: {target.name}"
              f"{f'  [tag={args.target_tag}]' if args.target_tag else ''}")

        docked = find_docked_grids(base, base_id)
        if not docked:
            print("\nПристыкованных кораблей не найдено (нет коннекторов со статусом 'Connected').")
            return 0
        print(f"Найдено пристыкованных гридов: {len(docked)}\n")

        # Сопоставляем ID грида → имя для отчёта
        name_by_id = {str(g.get("id")): g.get("name", "unnamed") for g in all_grids}

        grand_total = 0
        for entry in docked:
            sub_id = entry["other_grid_id"]
            sub_name = name_by_id.get(sub_id, f"id={sub_id}")
            sub_connector_id = entry.get("other_connector_id")
            print(f"\n========== {sub_name} (id={sub_id}) ==========")

            subgrid = Grid(client, owner_id, sub_id, owner_id, name=sub_name)
            devices = gather_drainable_devices(subgrid, sub_connector_id)
            if not devices:
                print("  на гриде нет инвентарных устройств для опустошения")
                continue
            print(f"  устройств с инвентарём: {len(devices)}")
            for d in devices:
                grand_total += drain_device(
                    d, containers, target, exclude_types, exclude_subtypes, args.dry_run,
                )

        print(f"\n=== ИТОГО: перенесено {grand_total} тип(ов) предметов"
              f"{'  (DRY RUN)' if args.dry_run else ''} ===")
        if grand_total == 0 and not args.dry_run:
            print("Если ничего не перенеслось — проверь, что контейнеры реально "
                  "пристыкованы (статус 'Connected') и не заблокированы merge-блоками.")
        return 0

    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
