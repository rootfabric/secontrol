#!/usr/bin/env python3
"""
SE Grid Status Report — full overview of all grids.
Outputs block stats, damage, device states, and container inventories.

Usage:
    python3 scripts/grid_report.py              # all grids
    python3 scripts/grid_report.py skynet-baza0  # single grid
"""
import sys
import time
from collections import Counter
from secontrol.common import get_all_grids, prepare_grid

def format_amount(amt):
    if isinstance(amt, float):
        return f'{amt:,.0f}' if amt >= 1000 else f'{amt:.2f}'
    return str(amt)

def report_grid(gid, gname):
    grid = prepare_grid(str(gid))
    time.sleep(0.8)

    print(f'\n{"="*60}')
    print(f'  {gname} (ID: {gid})')
    print(f'{"="*60}')
    print(f'  Blocks: {len(grid.blocks)}  |  Devices: {len(grid.devices)}')

    # --- Block breakdown ---
    types = Counter()
    damaged_blocks = []
    disabled_count = 0
    for bid, block in grid.blocks.items():
        types[f'{block.subtype}'] += 1
        state = block.state or {}
        if hasattr(block, 'is_damaged') and block.is_damaged:
            # Skip armor — damaged armor is normal
            if 'Armor' not in (block.subtype or ''):
                damaged_blocks.append(block)
        if state.get('enabled') == False:
            disabled_count += 1

    print(f'  Disabled: {disabled_count}')
    if damaged_blocks:
        print(f'  ⚠️  DAMAGED ({len(damaged_blocks)}):')
        for b in damaged_blocks:
            print(f'      [{b.block_type}] {b.subtype} (id={b.block_id})')

    # --- Devices ---
    print(f'\n  --- Devices ({len(grid.devices)}) ---')
    for did, dev in sorted(grid.devices.items(), key=lambda x: x[1].device_type):
        t = dev.telemetry or {}
        enabled = t.get('enabled', '?')
        extra = ''

        if dev.device_type == 'battery':
            inp = t.get('currentInput', '?')
            out = t.get('currentOutput', '?')
            stored = t.get('storedPower', '?')
            cap = t.get('maxStoredPower', '?')
            extra = f'  in={inp}W out={out}W stored={stored}/{cap}MWh'

        elif dev.device_type == 'solarpanel':
            extra = f'  output={t.get("currentOutput", "?")}W'

        elif dev.device_type == 'refinery':
            inp_inv = t.get('inputInventory', {})
            out_inv = t.get('outputInventory', {})
            producing = t.get('isProducing', '?')
            inp_items = inp_inv.get('items', []) if isinstance(inp_inv, dict) else []
            out_items = out_inv.get('items', []) if isinstance(out_inv, dict) else []
            extra = f'  producing={producing} in={len(inp_items)} out={len(out_items)}'

        elif dev.device_type == 'assembler':
            producing = t.get('isProducing', '?')
            queue = t.get('queue', [])
            extra = f'  producing={producing} queue={len(queue)}'

        elif dev.device_type == 'projector':
            rem = t.get('remainingBlocks', '?')
            build = t.get('buildableBlocks', '?')
            proj = t.get('isProjecting', '?')
            extra = f'  projecting={proj} remaining={rem} buildable={build}'

        elif dev.device_type == 'connector':
            status = t.get('connectorStatus', '?')
            connected = t.get('connectorIsConnected', '?')
            extra = f'  status={status} connected={connected}'

        elif dev.device_type == 'cockpit':
            extra = f'  hasPilot={t.get("hasPilot", "?")}'

        elif dev.device_type == 'remote_control':
            extra = f'  autopilot={t.get("autopilot", "?")}'

        elif dev.device_type == 'nanobot_drill_system':
            extra = f'  mining={t.get("isMining", "?")}'

        elif dev.device_type == 'thruster':
            thrust = t.get('currentThrust', '?')
            max_t = t.get('maxThrust', '?')
            extra = f'  thrust={thrust}/{max_t}'

        status_icon = '✅' if enabled == True else ('❌' if enabled == False else '❓')
        print(f'  {status_icon} [{dev.device_type}] id={did}{extra}')

    # --- Container inventories ---
    containers_found = False
    for did, dev in grid.devices.items():
        if dev.device_type == 'container':
            if not containers_found:
                print(f'\n  --- Containers ---')
                containers_found = True
            inv = dev.get_inventory()
            t = dev.telemetry or {}
            name = t.get('CustomName', 'Container')
            enabled = t.get('enabled', '?')
            icon = '✅' if enabled == True else '❌'
            print(f'  {icon} [{name}] {inv.current_mass:,.0f} кг | {inv.current_volume:.1f}/{inv.max_volume:.0f} л ({inv.fill_ratio*100:.1f}%)')
            if inv.items:
                for item in inv.items:
                    print(f'      {item.display_name}: {format_amount(item.amount)}')
            else:
                print(f'      (пусто)')

    # --- Refinery/Assembler inventories ---
    for did, dev in grid.devices.items():
        if dev.device_type in ('refinery', 'assembler'):
            t = dev.telemetry or {}
            name = t.get('CustomName', t.get('displayName', dev.device_type))
            for label, key in [('INPUT', 'inputInventory'), ('OUTPUT', 'outputInventory')]:
                inv = t.get(key, {})
                if not isinstance(inv, dict):
                    continue
                items = inv.get('items', [])
                mass = inv.get('currentMass', 0)
                if items:
                    print(f'  [{name}] {label} ({mass:,.0f} кг):')
                    for item in items:
                        dn = item.get('displayName', item.get('subtype', '?'))
                        print(f'      {dn}: {format_amount(item.get("amount", 0))}')


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
