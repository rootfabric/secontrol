#!/usr/bin/env python3
"""
space_miner_drill.py — Configure Nanobot Drill for gold mining on skynet-baza0.

Computes drill area offset to point at gold ore coordinates,
configures drill settings, starts mining, and monitors progress.

Usage:
    python scripts/space_miner_drill.py --dry-run       # show settings only
    python scripts/space_miner_drill.py                  # configure + mine
    python scripts/space_miner_drill.py --monitor-only   # just monitor existing state
"""

import sys
import os
import time
import math
import argparse
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/se-data/.env"))
sys.path.insert(0, "/workspace/src")

from secontrol.common import prepare_grid

# Gold ore coordinates from ore_deposit_scanner (world coords)
GOLD_WORLD = (98942.151, 81380.992, -131202.034)


def cross(a, b):
    return {
        'x': a['y'] * b['z'] - a['z'] * b['y'],
        'y': a['z'] * b['x'] - a['x'] * b['z'],
        'z': a['x'] * b['y'] - a['y'] * b['x'],
    }


def dot(a, b):
    return a['x'] * b['x'] + a['y'] * b['y'] + a['z'] * b['z']


def vec_sub(a, b):
    return {
        'x': a['x'] - b['x'],
        'y': a['y'] - b['y'],
        'z': a['z'] - b['z'],
    }


def vec_mag(v):
    return math.sqrt(v['x']**2 + v['y']**2 + v['z']**2)


def get_drill_world_pos(rc_pos, orient, drill_local):
    """Compute drill block world position from RC position and drill local offset."""
    fwd = orient['forward']
    up = orient['up']
    right = cross(fwd, up)

    lx, ly, lz = drill_local
    return {
        'x': rc_pos['x'] + lx * right['x'] + ly * up['x'] + lz * fwd['x'],
        'y': rc_pos['y'] + lx * right['y'] + ly * up['y'] + lz * fwd['y'],
        'z': rc_pos['z'] + lx * right['z'] + ly * up['z'] + lz * fwd['z'],
    }


def compute_area_offset(rc_pos, orient, drill_local, target_world):
    """Compute drill area offset in ship-local coordinates to point at target."""
    fwd = orient['forward']
    up = orient['up']
    right = cross(fwd, up)

    # Drill world position
    drill_pos = get_drill_world_pos(rc_pos, orient, drill_local)

    # Vector from drill to target in world coords
    ddx = target_world[0] - drill_pos['x']
    ddy = target_world[1] - drill_pos['y']
    ddz = target_world[2] - drill_pos['z']

    # Project onto ship-local axes
    local_fwd = ddx * fwd['x'] + ddy * fwd['y'] + ddz * fwd['z']
    local_up = ddx * up['x'] + ddy * up['y'] + ddz * up['z']
    local_right = ddx * right['x'] + ddy * right['y'] + ddz * right['z']

    return local_fwd, local_up, local_right


def main():
    parser = argparse.ArgumentParser(description="Nanobot Drill gold mining")
    parser.add_argument("--grid", default="skynet-baza0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--monitor-only", action="store_true")
    parser.add_argument("--monitor-time", type=int, default=60)
    parser.add_argument("--reset", action="store_true", help="Full drill reset before mining")
    args = parser.parse_args()

    print(f"⛏️  Connecting to {args.grid}...")
    grid = prepare_grid(args.grid)
    time.sleep(1)

    # Find devices
    from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice
    from secontrol.devices.remote_control_device import RemoteControlDevice
    from secontrol.devices.container_device import ContainerDevice

    drill = next((d for d in grid.devices.values()
                  if isinstance(d, NanobotDrillSystemDevice)), None)
    rc = next((d for d in grid.devices.values()
               if isinstance(d, RemoteControlDevice)), None)
    cargo = next((d for d in grid.devices.values()
                  if isinstance(d, ContainerDevice)), None)

    if not drill:
        print("❌ No Nanobot Drill found on grid!")
        return 1

    if not rc:
        print("❌ No Remote Control found on grid!")
        return 1

    print(f"  Drill: id={drill.device_id}")
    print(f"  RC: id={rc.device_id}")
    if cargo:
        print(f"  Cargo: id={cargo.device_id}")

    # Get ship position and orientation
    rc.update()
    time.sleep(1)
    rc.update()
    rc_tel = rc.telemetry or {}
    rc_pos = rc_tel.get('position', {})
    orient = rc_tel.get('orientation', {})

    if not rc_pos or not orient:
        print("❌ RC telemetry unavailable (no position/orientation)")
        return 1

    print(f"\n📍 Ship position: ({rc_pos['x']:.1f}, {rc_pos['y']:.1f}, {rc_pos['z']:.1f})")
    dist_to_gold = math.sqrt(
        (rc_pos['x'] - GOLD_WORLD[0])**2 +
        (rc_pos['y'] - GOLD_WORLD[1])**2 +
        (rc_pos['z'] - GOLD_WORLD[2])**2
    )
    print(f"  Distance to gold: {dist_to_gold:.1f}m")

    # Get drill block local offset from grid.blocks
    # Get drill block local offset from grid blocks
    drill_local = None
    try:
        # grid.blocks might be a dict of block_id -> block_info
        if hasattr(grid, 'blocks') and grid.blocks:
            if isinstance(grid.blocks, dict):
                for bid, block in grid.blocks.items():
                    if hasattr(block, 'get'):
                        if str(block.get('id', '')) == str(drill.device_id):
                            lp = block.get('local_position', {})
                            if lp:
                                drill_local = (lp.get('x', 0), lp.get('y', 0), lp.get('z', 0))
                                break
    except Exception:
        pass

    # Fallback: use (0, 0, 0) relative to RC — fine when close to ore
    if not drill_local:
        print("  ⚠️  Could not determine drill local offset, using (0, 0, 0)")
        drill_local = (0.0, 0.0, 0.0)

    print(f"  Drill local offset: ({drill_local[0]:.1f}, {drill_local[1]:.1f}, {drill_local[2]:.1f})")

    # Orientation vectors
    fwd = orient['forward']
    up = orient['up']
    right = cross(fwd, up)

    print(f"\n🧭 Ship orientation:")
    print(f"  Forward: ({fwd['x']:.3f}, {fwd['y']:.3f}, {fwd['z']:.3f})")
    print(f"  Up:      ({up['x']:.3f}, {up['y']:.3f}, {up['z']:.3f})")
    print(f"  Right:   ({right['x']:.3f}, {right['y']:.3f}, {right['z']:.3f})")

    # Compute area offset
    local_fwd, local_up, local_right = compute_area_offset(
        rc_pos, orient, drill_local, GOLD_WORLD
    )

    print(f"\n📐 Area offset (ship-local):")
    print(f"  FrontBack:  {local_fwd:+.1f}m")
    print(f"  UpDown:     {local_up:+.1f}m")
    print(f"  LeftRight:  {local_right:+.1f}m")

    offset_mag = math.sqrt(local_fwd**2 + local_up**2 + local_right**2)
    print(f"  Magnitude:  {offset_mag:.1f}m")

    # Drill world position for verification
    drill_pos = get_drill_world_pos(rc_pos, orient, drill_local)
    drill_to_gold = math.sqrt(
        (GOLD_WORLD[0] - drill_pos['x'])**2 +
        (GOLD_WORLD[1] - drill_pos['y'])**2 +
        (GOLD_WORLD[2] - drill_pos['z'])**2
    )
    print(f"  Drill→Gold distance: {drill_to_gold:.1f}m")

    # Check drill area coverage
    AREA_HALF = 37.5  # 75m / 2
    if drill_to_gold < AREA_HALF:
        print(f"  ✅ Gold is WITHIN drill area ({AREA_HALF}m radius) — offset optional")
    elif drill_to_gold < AREA_HALF * 1.5:
        print(f"  ⚠️  Gold at edge of drill area — offset may help")
    else:
        print(f"  ❌ Gold outside drill area — MUST set offset or fly closer")

    if args.dry_run:
        print("\n🔍 DRY RUN — no changes made")
        return 0

    # Monitor only mode
    if args.monitor_only:
        print("\n📊 Monitoring drill state...")
        return monitor_drill(drill, cargo, args.monitor_time)

    # === Configure drill ===
    print(f"\n⛏️  Configuring drill...")

    # Full reset if requested
    if args.reset:
        print("  🔄 Full drill reset...")
        drill.stop_drilling()
        time.sleep(0.5)
        drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": False}})
        time.sleep(1)
        drill.set_property("AreaOffsetUpDown", 0.0)
        drill.set_property("AreaOffsetFrontBack", 0.0)
        drill.set_property("AreaOffsetLeftRight", 0.0)
        time.sleep(0.3)

    # WorkMode = 2 (Drill) — use raw command (set_work_mode is bugged!)
    print("  Setting WorkMode=2 (Drill)...")
    drill.send_command({"cmd": "set", "payload": {"property": "Drill.WorkMode", "value": 2}})
    time.sleep(0.3)

    # ScriptControlled = False for auto-mining
    print("  Setting ScriptControlled=False...")
    drill.set_property("ScriptControlled", False)
    time.sleep(0.3)

    # Conveyor for auto-transfer to cargo
    print("  Enabling conveyor...")
    drill.set_use_conveyor(True)
    time.sleep(0.2)

    # Set area offset to point at gold
    if offset_mag > 5:  # only set offset if significant
        print(f"  Setting AreaOffset → gold...")
        drill.set_property("AreaOffsetUpDown", local_up)
        drill.set_property("AreaOffsetFrontBack", local_fwd)
        drill.set_property("AreaOffsetLeftRight", local_right)
        time.sleep(0.3)
    else:
        print(f"  Offset small ({offset_mag:.1f}m), using defaults")

    # Turn on drill
    print("  Turning on drill...")
    drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": True}})
    time.sleep(1)

    # Start drilling
    print("  Starting drilling...")
    drill.start_drilling()
    time.sleep(2)

    # Initial state check
    drill.update()
    time.sleep(1)
    tel = drill.telemetry or {}
    props = tel.get('properties', {})
    targets = tel.get('drill_possibledrilltargets', [])
    current = props.get('Drill.CurrentDrillTarget') or tel.get('drill_currentdrilltarget')

    print(f"\n📊 Drill state after start:")
    print(f"  Enabled: {drill.is_enabled()}")
    print(f"  WorkMode: {tel.get('drill_workmode')}")
    print(f"  ScriptControlled: {tel.get('drill_scriptcontrolled')}")
    print(f"  PossibleDrillTargets: {len(targets)}")
    print(f"  CurrentDrillTarget: {current}")

    if targets:
        gold_targets = [t for t in targets if 'Gold' in str(t)]
        print(f"  Gold targets: {len(gold_targets)}")
        if gold_targets:
            print(f"  ⛏️  GOLD FOUND IN DRILL AREA!")
            for gt in gold_targets[:3]:
                print(f"    {gt}")
        stone_targets = [t for t in targets if 'MoonRock' in str(t) or 'SmallMoonRock' in str(t)]
        print(f"  Stone targets: {len(stone_targets)}")
    else:
        print("  ⚠️  No targets found — drill may need repositioning")
        # Try sweep if no targets
        print("  🔄 Trying offset sweep...")
        found = sweep_offsets(drill)
        if not found:
            print("  ❌ No targets found after sweep — ship may need to reposition")

    # Monitor
    if args.monitor_time > 0:
        monitor_drill(drill, cargo, args.monitor_time)

    return 0


def sweep_offsets(drill):
    """Sweep area offsets to find targets."""
    for axis, prop in [
        ("UpDown", "AreaOffsetUpDown"),
        ("FrontBack", "AreaOffsetFrontBack"),
        ("LeftRight", "AreaOffsetLeftRight"),
    ]:
        for offset in range(-40, 45, 10):
            drill.set_property(prop, float(offset))
            time.sleep(0.5)
            drill.update()
            time.sleep(0.5)
            targets = drill.telemetry.get('drill_possibledrilltargets', [])
            if targets:
                print(f"  ✅ Found {len(targets)} targets at {axis}={offset}")
                return True
    return False


def monitor_drill(drill, cargo, duration):
    """Monitor drilling progress."""
    print(f"\n📊 Monitoring for {duration}s...")
    start = time.time()

    # Initial inventory snapshot
    gold_before = 0
    if cargo:
        try:
            cargo.update()
            time.sleep(0.5)
            for inv in cargo.inventories():
                for item in (inv.items or []):
                    if 'Gold' in (item.subtype or ''):
                        gold_before = item.amount
        except Exception:
            pass

    print(f"  Gold Ore before: {gold_before:.1f}")

    while time.time() - start < duration:
        elapsed = int(time.time() - start)
        time.sleep(3)

        try:
            drill.update()
            time.sleep(0.5)
            tel = drill.telemetry or {}
            props = tel.get('properties', {})
            targets = tel.get('drill_possibledrilltargets', [])
            current = props.get('Drill.CurrentDrillTarget') or tel.get('drill_currentdrilltarget')

            gold_targets = [t for t in targets if 'Gold' in str(t)]
            mining_status = "⛏️" if current else "⏸️"

            # Check inventory
            gold_now = gold_before
            if cargo:
                try:
                    cargo.update()
                    time.sleep(0.3)
                    for inv in cargo.inventories():
                        for item in (inv.items or []):
                            if 'Gold' in (item.subtype or ''):
                                gold_now = item.amount
                except Exception:
                    pass

            print(f"  [{elapsed:3d}s] {mining_status} "
                  f"Targets={len(targets)}(Au={len(gold_targets)}) "
                  f"Mining={current or 'None':20s} "
                  f"Gold={gold_now:.0f} (+{gold_now - gold_before:.0f})")

            # Re-enable if drill auto-disabled
            if not drill.is_enabled():
                print("    ⚠️  Drill auto-disabled! Re-enabling...")
                drill.send_command({"cmd": "set", "payload": {"property": "OnOff", "value": True}})
                time.sleep(0.5)
                drill.start_drilling()

        except Exception as e:
            print(f"  [{elapsed:3d}s] Error: {e}")

    # Final summary
    gold_final = gold_before
    if cargo:
        try:
            cargo.update()
            time.sleep(0.5)
            for inv in cargo.inventories():
                for item in (inv.items or []):
                    if 'Gold' in (item.subtype or ''):
                        gold_final = item.amount
        except Exception:
            pass

    print(f"\n📈 Summary:")
    print(f"  Gold Ore: {gold_before:.0f} → {gold_final:.0f} (+{gold_final - gold_before:.0f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
