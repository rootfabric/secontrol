"""
Clear all ore deposit data from SharedMapController (Redis).

After a server restart ore positions may be stale — this script wipes them
so you can do a fresh radar scan.

Usage:
    python scripts/clear_ore_data.py                       # dry-run (show what would be deleted)
    python scripts/clear_ore_data.py --apply               # actually delete
    python scripts/clear_ore_data.py --apply --keep-index  # delete keys but keep index entries
"""
import argparse
import sys

from secontrol.common import resolve_owner_id
from secontrol.controllers import SharedMapController


def main():
    parser = argparse.ArgumentParser(description="Clear ore data from SharedMapController")
    parser.add_argument("--owner-id", default=None, help="Owner ID (auto-resolved from .env)")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run)")
    parser.add_argument("--keep-index", action="store_true", help="Keep ore chunk IDs in index")
    parser.add_argument("--chunk-size", type=float, default=100.0)
    args = parser.parse_args()

    owner_id = args.owner_id or resolve_owner_id()
    ctrl = SharedMapController(owner_id=owner_id, chunk_size=args.chunk_size, storage_backend="redis")
    ctrl.load()

    idx = ctrl._load_index()
    ore_chunk_ids = list(idx.get("ores", []))

    if not ore_chunk_ids:
        print("No ore chunks in index — nothing to do.")
        return

    print(f"Owner: {owner_id}")
    print(f"Ore chunks to delete: {len(ore_chunk_ids)}")
    print(f"Ore deposits in memory: {len(ctrl.data.ores)}")
    print()

    for cid in ore_chunk_ids:
        print(f"  ore chunk: {cid}")

    if not args.apply:
        print("\n[DRY-RUN] Nothing deleted. Pass --apply to actually delete.")
        return

    # delete each ore chunk key
    deleted = 0
    for cid in ore_chunk_ids:
        try:
            ctrl.storage.delete_chunk("ores", cid)
            deleted += 1
        except Exception as e:
            print(f"  ERROR deleting {cid}: {e}")

    # clear index
    if not args.keep_index:
        idx["ores"] = []
        ctrl._save_index(idx)

    # clear in-memory data
    ctrl.data.ores.clear()

    print(f"\nDeleted {deleted}/{len(ore_chunk_ids)} ore chunk keys.")
    if not args.keep_index:
        print("Index updated (ores list cleared).")
    else:
        print("Index kept (--keep-index).")

    print("Done. Run a fresh scan with shared_map_scan.py to repopulate.")


if __name__ == "__main__":
    main()
