"""Dump full grid info to find block orientation vectors."""
import sys, os, time, json

sys.path.insert(0, "C:/secontrol/src")
from secontrol.common import prepare_grid

grid = prepare_grid("skynet-baza0")
time.sleep(2)

info = grid.info or {}
print(f"Grid info keys: {list(info.keys())}")

# Check blocks in grid info
blocks = info.get("blocks", info.get("Blocks", []))
print(f"Blocks: {len(blocks) if isinstance(blocks, list) else type(blocks)}")

if isinstance(blocks, list) and blocks:
    first = blocks[0]
    print(f"\nFirst block keys: {list(first.keys()) if isinstance(first, dict) else type(first)}")
    if isinstance(first, dict):
        for k, v in first.items():
            if isinstance(v, (int, float, str, bool)):
                print(f"  {k}: {v}")
            elif isinstance(v, dict):
                print(f"  {k}: dict keys={list(v.keys())}")
            elif isinstance(v, list):
                print(f"  {k}: list len={len(v)}")
    
    # Find a thruster block
    thruster_blocks = [b for b in blocks if isinstance(b, dict) and "Thrust" in str(b.get("type", b.get("Type", "")))]
    if thruster_blocks:
        print(f"\nThruster blocks found: {len(thruster_blocks)}")
        example = thruster_blocks[0]
        print(json.dumps(example, indent=2, default=str)[:3000])

grid.close()
