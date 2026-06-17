#!/usr/bin/env python3
"""
SE Grid Status Report - compact overview for agent use.
Outputs block stats, damage, power/fuel status, and container inventories.

Usage:
    python3 scripts/grid_report.py              # all grids
    python3 scripts/grid_report.py skynet-baza0  # single grid
"""
import sys
import time
from secontrol.common import get_all_grids, prepare_grid
from secontrol.fleet_dashboard.redis_reader import FleetRedisReader


def format_amount(amt):
    if isinstance(amt, float):
        return f'{amt:,.0f}' if amt >= 1000 else f'{amt:.2f}'
    return str(amt)


def _safe_inventory(dev):
    inv = getattr(dev, 'inventory', None)
    if callable(inv):
        try:
            return inv()
        except Exception:
            return None
    return inv


def report_grid(gid, gname):
    grid = prepare_grid(str(gid))
    time.sleep(0.8)

    reader = FleetRedisReader()
    telemetry_map = reader._discover_telemetry(gid)

    print(f'\n{"=" * 50}')
    print(f'  {gname} (ID: {gid})')
    print(f'{"=" * 50}')
    print(f'  Blocks: {len(grid.blocks)}  |  Devices: {len(grid.devices)}')

    damaged_blocks = []
    disabled_count = 0
    for bid, block in grid.blocks.items():
        state = block.state or {}
        if hasattr(block, 'is_damaged') and block.is_damaged:
            if 'Armor' not in (block.subtype or ''):
                damaged_blocks.append(block)
        if state.get('enabled') == False:
            disabled_count += 1

    print(f'  Disabled blocks: {disabled_count}')
    if not damaged_blocks:
        print(f'  Integrity: ALL INTACT')
    else:
        print(f'  Integrity: {len(damaged_blocks)} DAMAGED:')
        for b in damaged_blocks:
            print(f'    [{b.block_type}] {b.subtype} (id={b.block_id})')

    batteries = []
    hydrogen_tanks = []
    reactors = []
    total_power_stored = 0.0
    total_power_capacity = 0.0
    total_hydrogen = 0.0
    total_hydrogen_capacity = 0.0
    total_uranium = 0
    has_hydrogen_thrusters = False
    has_ion_thrusters = False
    thruster_hydrogen = 0
    thruster_ion = 0
    thruster_atmospheric = 0

    for did, dev in grid.devices.items():
        t = telemetry_map.get(did, dev.telemetry or {})
        dtype = dev.device_type
        if dtype == 'battery':
            stored = t.get('currentStoredPower', 0.0) or t.get('storedPower', 0.0)
            capacity = t.get('maxStoredPower', 1.0)
            charge_pct = (stored / capacity * 100) if capacity else 0
            name = t.get('CustomName', t.get('displayName', 'Battery'))
            batteries.append({'name': name, 'stored': stored, 'capacity': capacity, 'pct': charge_pct})
            total_power_stored += stored
            total_power_capacity += capacity
        elif dtype == 'oxygentank':
            subtype = str(t.get('subtype', '')).lower()
            if 'hydrogen' in subtype:
                fr = t.get('filledRatio')
                fp = t.get('filledPercent')
                level = (float(fr) * 100 if fr is not None else float(fp) if fp is not None else 0.0)
                cap_str = t.get('capacity', '0')
                max_vol = float(cap_str) if cap_str else 0.0
                name = t.get('CustomName', t.get('displayName', 'HydrogenTank'))
                hydrogen_tanks.append({'name': name, 'level': level, 'max': max_vol})
                total_hydrogen += level * max_vol / 100
                total_hydrogen_capacity += max_vol
        elif dtype == 'reactor':
            name = t.get('CustomName', t.get('displayName', 'Reactor'))
            reactors.append({'name': name})
            inv = _safe_inventory(dev)
            if inv and getattr(inv, 'items', None):
                for item in inv.items:
                    if 'uranium' in item.display_name.lower():
                        total_uranium += item.amount
        elif dtype == 'thruster':
            subtype = str(t.get('subtype', '')).lower()
            dev_type = str(t.get('type', ''))
            if 'hydrogen' in subtype or 'hydrogenthrust' in subtype or 'HydrogenEngine' in dev_type:
                has_hydrogen_thrusters = True
                thruster_hydrogen += 1
            elif 'ion' in subtype:
                has_ion_thrusters = True
                thruster_ion += 1
            else:
                thruster_atmospheric += 1

    thruster_parts = []
    if thruster_hydrogen > 0:
        thruster_parts.append(f'{thruster_hydrogen} hydrogen')
    if thruster_ion > 0:
        thruster_parts.append(f'{thruster_ion} ion')
    if thruster_atmospheric > 0:
        thruster_parts.append(f'{thruster_atmospheric} atmospheric')
    if thruster_parts:
        print(f'  Thrusters: {", ".join(thruster_parts)}')

    if total_power_capacity > 0:
        total_pct = (total_power_stored / total_power_capacity * 100)
        icon = '[OK]' if total_pct >= 50 else ('[WARN]' if total_pct >= 20 else '[FAIL]')
        print(f'  Batteries: {icon} {total_power_stored:.2f}/{total_power_capacity:.2f} MWh ({total_pct:.1f}%)')
        for bat in batteries:
            print(f'    {bat["name"]}: {bat["stored"]:.2f}/{bat["capacity"]:.2f} MWh ({bat["pct"]:.1f}%)')

    if reactors:
        print(f'  Reactors: {total_uranium} uranium')
        for r in reactors:
            print(f'    {r["name"]}')
            inv = None
            for did, dev in grid.devices.items():
                if dev.device_type == 'reactor':
                    t = telemetry_map.get(did, dev.telemetry or {})
                    name = t.get('CustomName', t.get('displayName', 'Reactor'))
                    if name == r['name']:
                        inv = _safe_inventory(dev)
                        break
            if inv and inv.items:
                for item in inv.items:
                    print(f'      {item.display_name}: {format_amount(item.amount)}')

    if hydrogen_tanks:
        total_h_pct = (total_hydrogen / total_hydrogen_capacity * 100) if total_hydrogen_capacity > 0 else 0
        icon = '[OK]' if total_h_pct >= 50 else ('[WARN]' if total_h_pct >= 20 else '[FAIL]')
        print(f'  Hydrogen: {icon} {total_hydrogen:,.0f}/{total_hydrogen_capacity:,.0f} L ({total_h_pct:.1f}%)')
        for tank in hydrogen_tanks:
            print(f'    {tank["name"]}: {tank["level"]:.1f}%')
    elif has_hydrogen_thrusters:
        print(f'  Hydrogen: [WARN] no hydrogen tanks found')

    all_inventory_items = []
    total_inventory_mass = 0.0

    for did, dev in grid.devices.items():
        t = telemetry_map.get(did, dev.telemetry or {})
        dtype = dev.device_type
        name = t.get('CustomName', t.get('displayName', dtype))
        if dtype == 'container':
            inv = _safe_inventory(dev)
            mass = inv.current_mass if inv else 0.0
            total_inventory_mass += mass
            if inv and getattr(inv, 'items', None):
                for item in inv.items:
                    all_inventory_items.append({'name': item.display_name, 'amount': item.amount, 'source': name})
        elif dtype == 'reactor':
            inv = _safe_inventory(dev)
            if inv:
                total_inventory_mass += inv.current_mass if inv.current_mass else 0.0
                if getattr(inv, 'items', None):
                    for item in inv.items:
                        all_inventory_items.append({'name': item.display_name, 'amount': item.amount, 'source': name})
        elif dtype in ('refinery', 'assembler'):
            for label, key in [('INPUT', 'inputInventory'), ('OUTPUT', 'outputInventory')]:
                inv_data = t.get(key, {})
                if not isinstance(inv_data, dict):
                    continue
                items = inv_data.get('items', [])
                mass = inv_data.get('currentMass', 0)
                if items:
                    total_inventory_mass += mass
                    for item in items:
                        all_inventory_items.append({'name': item.get('displayName', item.get('subtype', '?')), 'amount': item.get('amount', 0), 'source': name + ' ' + label})

    from collections import defaultdict
    aggregated = defaultdict(lambda: {'amount': 0.0, 'sources': []})
    for item in all_inventory_items:
        key = item['name']
        aggregated[key]['amount'] += item['amount']
        if item['source'] not in aggregated[key]['sources']:
            aggregated[key]['sources'].append(item['source'])

    if aggregated:
        print('  Containers:')
        for name, data in sorted(aggregated.items()):
            sources_str = ', '.join(data['sources']) if len(data['sources']) <= 2 else ', '.join(data['sources'][:2]) + '...'
            print(f'    {name}: {format_amount(data["amount"])} ({sources_str})')
    else:
        print('  Containers: (empty)')

    hydrogen_warning = None
    flight_ready = True
    if has_hydrogen_thrusters and hydrogen_tanks:
        total_h_pct = (total_hydrogen / total_hydrogen_capacity * 100) if total_hydrogen_capacity > 0 else 0
        if total_h_pct < 20:
            if not has_ion_thrusters and thruster_atmospheric == 0:
                flight_ready = False
                hydrogen_warning = f'CRITICAL: No hydrogen fuel ({total_h_pct:.0f}%) and no thrust backup!'
            elif len(reactors) == 0 and (not batteries or all(b['pct'] < 20 for b in batteries)):
                flight_ready = False
                hydrogen_warning = f'CRITICAL: No hydrogen ({total_h_pct:.0f}%), no reactor, battery low!'
            else:
                hydrogen_warning = f'WARNING: Low hydrogen ({total_h_pct:.0f}%), ion/electric available'
        elif total_h_pct < 50:
            hydrogen_warning = f'Low hydrogen: {total_h_pct:.0f}%'
        else:
            hydrogen_warning = f'OK: {total_h_pct:.0f}%'
    elif has_hydrogen_thrusters and not hydrogen_tanks:
        flight_ready = False
        hydrogen_warning = f'CRITICAL: Hydrogen thrusters present but no tank found!'

    if hydrogen_warning:
        icon = '[OK]' if 'OK' in hydrogen_warning else ('[WARN]' if 'WARNING' in hydrogen_warning else '[FAIL]')
        print(f'  Fuel Status: {icon} {hydrogen_warning}')

    if batteries:
        low_battery = all(b['pct'] < 20 for b in batteries)
        if low_battery and len(reactors) == 0:
            flight_ready = False
            print(f'  [FAIL] CRITICAL: Battery low (<20%) and no reactor!')
        elif low_battery:
            flight_ready = False
            print(f'  [FAIL] Battery low (<20%)')
        elif any(b['pct'] < 30 for b in batteries) and len(reactors) == 0:
            flight_ready = False
            print(f'  [FAIL] Battery <30% and no reactor - no power backup!')
        elif any(b['pct'] < 30 for b in batteries):
            print(f'  [WARN] Battery low (<30%)')

    if flight_ready:
        print(f'  [OK] READY FOR FLIGHT')
    else:
        print(f'  [FAIL] NOT READY FOR FLIGHT')

    print(f'  Total inventory mass: {total_inventory_mass:,.0f} kg ({len(aggregated)} types)')


def main():
    target_name = sys.argv[1] if len(sys.argv) > 1 else None

    grids = get_all_grids()

    if target_name:
        matches = [(gid, gname) for gid, gname in grids if target_name.lower() in gname.lower()]
        if not matches:
            print(f'Grid "{target_name}" not found. Available:')
            for gid, gname in grids:
                print(f'  {gname}')
            sys.exit(1)
        for gid, gname in matches:
            report_grid(gid, gname)
    else:
        for gid, gname in grids:
            try:
                report_grid(gid, gname)
            except Exception as e:
                print(f'\n=== {gname}: ERROR {e} ===')


if __name__ == '__main__':
    main()