#!/usr/bin/env python3
"""Save a blueprint XML of a grid via the on-board projector.

Uses the SE-bridge projector plugin command ``export_grid_blueprint``. The
projector serialises the grid it is mounted on (and any connected subgrids when
``include_connected=True``) into a ``MyObjectBuilder_ShipBlueprintDefinition``
XML and stores it under the projector's ``:blueprint`` Redis key. This script
polls that key, decodes the XML, and writes it to disk.

Default output path follows the SE convention:
    %APPDATA%/SpaceEngineers/Blueprints/local/<grid_name>/bp.sbc

Use ``--also-copy`` to mirror the same XML to additional locations (for example
the project repo's ``C:\\secontrol\\blueprints\\<grid>-raw.sbc``).

Usage:
    python scripts/save_grid_blueprint.py <grid_name_or_id>
    python scripts/save_grid_blueprint.py <grid> --output C:/some/dir/grid.sbc
    python scripts/save_grid_blueprint.py <grid> --also-copy C:/secontrol/blueprints/grid-raw.sbc
    python scripts/save_grid_blueprint.py <grid> --dry-run
    python scripts/save_grid_blueprint.py <grid> --no-include-connected

Exit codes:
    0 - blueprint written successfully (or dry-run completed)
    1 - no projector on grid, request failed, timeout, or sanity check failed
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from secontrol.common import close, prepare_grid


DEFAULT_APPDATA_BLUEPRINTS = Path.home() / "AppData" / "Roaming" / "SpaceEngineers" / "Blueprints" / "local"
POLL_INTERVAL_S = 1.0
DEFAULT_TIMEOUT_S = 30.0
ENABLE_VERIFY_TIMEOUT_S = 5.0


def _canonical_blueprint_path(grid_name: str) -> Path:
    safe = (grid_name or "").strip() or "grid"
    return DEFAULT_APPDATA_BLUEPRINTS / safe / "bp.sbc"


def _find_projector(grid):
    projectors = grid.find_devices_by_type("projector")
    if not projectors:
        raise RuntimeError("no projector device on grid")
    return projectors[0]


def _ensure_projector_enabled(projector) -> bool:
    """Make sure the projector is enabled. Returns True if a state change was sent."""
    if (projector.telemetry or {}).get("enabled") is True:
        return False
    projector.set_enabled(True)
    try:
        projector.wait_for_telemetry(timeout=ENABLE_VERIFY_TIMEOUT_S, wait_for_new=True, need_update=True)
    except Exception:
        pass
    return True


def _wait_for_xml(projector, timeout: float) -> dict:
    """Poll projector.blueprint_xml() until the snapshot appears or timeout."""
    deadline = time.time() + timeout
    last_len = -1
    while time.time() < deadline:
        snap = projector.blueprint_snapshot()
        if isinstance(snap, dict) and snap.get("ok") and isinstance(snap.get("xml"), str):
            return snap
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"blueprint XML did not appear within {timeout:.0f}s")


def _sanity_check(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if "<MyObjectBuilder_ShipBlueprintDefinition" not in text:
        raise RuntimeError("file does not contain ShipBlueprintDefinition tag")
    return {
        "size_bytes": path.stat().st_size,
        "xml_chars": len(text),
        "grid_count": text.count("<CubeGrid>"),
        "block_count": text.count("<MyObjectBuilder_CubeBlock"),
    }


def _copy_to(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("grid", help="Source grid name (substring match) or numeric grid id.")
    p.add_argument("--output", "-o", type=Path, default=None,
                   help="Destination .sbc file (default: %%APPDATA%%/SpaceEngineers/Blueprints/local/<gridname>/bp.sbc).")
    p.add_argument("--also-copy", "-c", type=Path, action="append", default=[],
                   help="Extra destination to copy the same XML to. Repeatable.")
    p.add_argument("--include-connected", dest="include_connected", action="store_true", default=True,
                   help="Include connected subgrids in the export (default).")
    p.add_argument("--no-include-connected", dest="include_connected", action="store_false",
                   help="Export only the projector host grid.")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                   help=f"Seconds to wait for the projector snapshot (default: {DEFAULT_TIMEOUT_S}).")
    p.add_argument("--no-enable", action="store_true",
                   help="Skip enabling the projector (assume it is already ON).")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve the grid, locate the projector, print the plan, but do not request or write.")
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    try:
        grid.refresh_devices()
        grid_name = grid.name
        print(f"Grid: {grid_name} (id={grid.grid_id})")

        projector = _find_projector(grid)
        print(f"Projector: {projector.name} (telemetry_key={projector.telemetry_key})")

        output_path = args.output or _canonical_blueprint_path(grid_name)
        print(f"Output: {output_path}")
        for extra in args.also_copy:
            print(f"Also-copy: {extra}")

        if args.dry_run:
            print()
            print("Dry-run: would call projector.request_grid_blueprint(include_connected=%s) "
                  "and write to %s" % (args.include_connected, output_path))
            return 0

        if not args.no_enable:
            changed = _ensure_projector_enabled(projector)
            if changed:
                print("Projector was OFF, sent set_enabled(True).")
            else:
                print("Projector is already enabled.")

        print(f"Requesting grid blueprint export (include_connected={args.include_connected})...")
        projector.request_grid_blueprint(include_connected=args.include_connected)
        print(f"  waiting up to {args.timeout:.0f}s on snapshot...")

        snap = _wait_for_xml(projector, args.timeout)
        xml = snap["xml"]
        print(f"  snapshot ok={snap.get('ok')}, gridName={snap.get('gridName')!r}, "
              f"gridCount={snap.get('gridCount')}, xml_chars={len(xml)}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml, encoding="utf-8")
        print(f"  wrote {output_path} ({output_path.stat().st_size} bytes)")

        stats = _sanity_check(output_path)
        print(f"  sanity: {stats}")

        for extra in args.also_copy:
            dest = _copy_to(output_path, Path(extra))
            print(f"  copied -> {dest} ({dest.stat().st_size} bytes)")

        print()
        print("Done.")
        return 0
    finally:
        close(grid)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
