#!/usr/bin/env python3
"""Fast grid-by-name lookup for secontrol.

Usage:
    python find_grid.py                       # list all grids (id, name)
    python find_grid.py farpost0              # resolve substring to id
    python find_grid.py "база фарпост"        # cyrillic works too
    python find_grid.py farpost0 --id-only    # print only the numeric id
    python find_grid.py farpost0 --json       # one JSON object per match

Exit codes:
    0  - at least one match (or list mode printed the catalog)
    1  - no match (or zero grids visible to the owner)
    2  - misconfiguration (REDIS_USERNAME missing / Redis unreachable)

The resolver lives in src/secontrol/common.py (_resolve_grid_identifier).
This script is a thin CLI wrapper that adds a clear listing mode and
predictable exit codes for pipelines.
"""
from __future__ import annotations

import argparse
import json
import sys

from secontrol.common import get_all_grids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find a Space Engineers grid by name or id substring.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Grid name, id, or substring. Omit to list all grids.",
    )
    parser.add_argument(
        "--id-only",
        action="store_true",
        help="Print only the numeric grid_id (first match).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON lines: one object per match (or all grids in list mode).",
    )
    parser.add_argument(
        "--include-subgrids",
        action="store_true",
        help="Include sub-grids in the list (excluded by default).",
    )
    args = parser.parse_args()

    try:
        grids = get_all_grids(exclude_subgrids=not args.include_subgrids)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"redis error: {e}", file=sys.stderr)
        return 2

    if not grids:
        print("no grids visible to this owner", file=sys.stderr)
        return 1

    if not args.query:
        if args.json:
            for gid, name in grids:
                print(json.dumps({"grid_id": gid, "name": name}, ensure_ascii=False))
        else:
            for gid, name in grids:
                print(f"{gid}\t{name}")
        return 0

    q = args.query.strip()
    ql = q.lower()
    exact = [(gid, name) for gid, name in grids if name == q]
    matches = exact or [(gid, name) for gid, name in grids if ql in name.lower()]

    if not matches:
        print(f"no match for '{q}'. available grids:", file=sys.stderr)
        for gid, name in grids:
            print(f"  {gid}\t{name}", file=sys.stderr)
        return 1

    if args.id_only:
        print(matches[0][0])
        return 0

    if args.json:
        for gid, name in matches:
            print(json.dumps({"grid_id": gid, "name": name}, ensure_ascii=False))
        return 0

    if len(matches) > 1:
        print(f"warning: {len(matches)} matches for '{q}' (showing all):", file=sys.stderr)

    for gid, name in matches:
        print(f"{gid}\t{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
