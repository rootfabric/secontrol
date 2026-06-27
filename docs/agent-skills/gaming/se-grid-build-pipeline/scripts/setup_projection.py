#!/usr/bin/env python3
"""Project a blueprint or prefab onto a Projector block, with safe defaults
for inter-grid welding.

Behavior:
  1. Resolve grid (substring match) and pick the Projector block
     (by name if --projector-name is given, otherwise the first one).
  2. Power on the projector (`set_enabled(True)`).
  3. Load the projection source:
       --prefab <PrefabId>          -> load_prefab(prefab_id, keep=True)
       --blueprint-xml <file>       -> load_blueprint_xml(xml, keep=True)
       (omit both to skip loading and only adjust an already-loaded projection)
  4. Apply projection flags for inter-grid welding:
       instantBuild        = False  (player must weld progressively, so merge
                                     blocks and conveyors spawn correctly)
       showOnlyBuildable   = False  (operator needs to see the full silhouette)
       keepProjection      = True   (don't clear on load)
       projectionLocked    = True   (don't drift while welding)
       alignGrids          = True   (weld across grids cleanly)
       useAdaptiveOffsets  = True
       useAdaptiveRotation = True
  5. Optional scale/offset/rotation (raw integers from CLI, applied via
     set_scale / set_offset / set_rotation).

Usage:
    python scripts/setup_projection.py skynet-farpost0 \
        --prefab LargeGrid/StarterMiner \
        --projector-name "Projector 1"

    python scripts/setup_projection.py skynet-farpost0 \
        --blueprint-xml blueprints/scout_v3.sbc \
        --scale 0.5 --offset 1 0 -2 --rotation 0 90 0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from secontrol.common import prepare_grid
from secontrol.devices.projector_device import ProjectorDevice


def _pick_projector(grid, name: str | None) -> ProjectorDevice:
    candidates = grid.find_devices_by_type(ProjectorDevice)
    if not candidates:
        raise SystemExit("ERROR: no Projector device on grid {!r}".format(grid.name))
    if name:
        for dev in candidates:
            t = dev.telemetry or {}
            label = t.get("customName") or t.get("name") or ""
            if label.lower() == name.lower():
                return dev
        raise SystemExit(
            "ERROR: projector {!r} not found. Available: {}".format(
                name,
                [(d.telemetry or {}).get("customName") or d.device_id for d in candidates],
            )
        )
    return candidates[0]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grid", help="Grid name or id (substring match).")
    p.add_argument("--projector-name", default=None,
                   help="Pick a specific projector by customName (default: first).")
    p.add_argument("--prefab", default=None,
                   help="Prefab id to load, e.g. LargeGrid/StarterMiner.")
    p.add_argument("--blueprint-xml", default=None,
                   help="Path to a *.sbc ShipBlueprintDefinition file.")
    p.add_argument("--scale", type=float, default=None,
                   help="Projection scale (e.g. 0.5).")
    p.add_argument("--offset", type=int, nargs=3, default=None,
                   metavar=("X", "Y", "Z"),
                   help="Projection offset (cells).")
    p.add_argument("--rotation", type=int, nargs=3, default=None,
                   metavar=("X", "Y", "Z"),
                   help="Projection rotation (degrees, 0/90/180/270).")
    args = p.parse_args()

    grid = prepare_grid(args.grid)
    print("Grid: {} ({})  blocks={}".format(grid.name, grid.grid_id, len(grid.blocks)))

    proj = _pick_projector(grid, args.projector_name)
    t = proj.telemetry or {}
    print("Projector: id={}  name={!r}".format(
        proj.device_id,
        t.get("customName") or t.get("name"),
    ))

    if not t.get("enabled"):
        print("Powering on projector...")
        proj.set_enabled(True)
    else:
        print("Projector already enabled.")

    if args.prefab and args.blueprint_xml:
        raise SystemExit("ERROR: pass only one of --prefab / --blueprint-xml")

    if args.prefab:
        print("Loading prefab: {!r}".format(args.prefab))
        proj.load_prefab(args.prefab, keep=True)
    elif args.blueprint_xml:
        path = Path(args.blueprint_xml)
        xml = path.read_text(encoding="utf-8")
        print("Loading blueprint XML from {!r} ({} chars)".format(path, len(xml)))
        proj.load_blueprint_xml(xml, keep=True)

    print("Applying safe inter-grid welding flags...")
    proj.set_flags(
        instant_build=False,
        show_only_buildable=False,
        keep_projection=True,
        lock_projection=True,
        align_grids=True,
        use_adaptive_offsets=True,
        use_adaptive_rotation=True,
    )

    if args.scale is not None:
        print("scale={}".format(args.scale))
        proj.set_scale(args.scale)
    if args.offset is not None:
        x, y, z = args.offset
        print("offset=({}, {}, {})".format(x, y, z))
        proj.set_offset(x, y, z)
    if args.rotation is not None:
        x, y, z = args.rotation
        print("rotation=({}, {}, {})".format(x, y, z))
        proj.set_rotation(x, y, z)

    print()
    print("OK. Next step: configure_welding.py <grid>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
