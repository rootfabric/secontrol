#!/usr/bin/env python3
"""Apply the proposed secontrol repository refactor.

Run this script from the root of an existing secontrol checkout:

    python apply_refactor.py

The script is intentionally idempotent:
- creates the new commands/ tree;
- copies operational scripts from old examples/ paths into commands/;
- replaces old script files with compatibility wrappers;
- writes the new agent/documentation entry points;
- keeps backups of replaced files in .refactor_backups/.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import os
import re
import runpy
import shutil
import sys
from pathlib import Path

ROOT_MARKERS = ("pyproject.toml", "src")
BACKUP_DIR = ".refactor_backups"

COMMAND_MAPPINGS: tuple[tuple[str, str], ...] = (
    # Diagnostics
    ("examples/organized/grid/basic/list_grids.py", "commands/diagnostics/list_grids.py"),
    ("examples/organized/grid/basic/print_devices.py", "commands/diagnostics/print_devices.py"),
    ("examples/organized/diagnostics/check_flight_ready.py", "commands/diagnostics/check_flight_ready.py"),
    ("examples/organized/diagnostics/check_grids.py", "commands/diagnostics/check_grids.py"),
    ("docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py", "commands/diagnostics/grid_report.py"),

    # Navigation
    ("examples/space_flight/space_navigator_v5.py", "commands/navigation/space_navigator_v5.py"),
    ("examples/space_flight/space_navigator_v4.py", "commands/navigation/space_navigator_v4.py"),
    ("examples/space_flight/voxel_distance_meter.py", "commands/navigation/voxel_distance_meter.py"),

    # Docking / parking
    ("examples/organized/parking/dock.py", "commands/docking/dock.py"),
    ("examples/organized/parking/check_docking_status.py", "commands/docking/check_docking_status.py"),
    ("examples/organized/parking/smooth_undock.py", "commands/docking/smooth_undock.py"),
    ("examples/organized/parking/undock_drone.py", "commands/docking/undock_drone.py"),
    ("examples/organized/parking/final_dock.py", "commands/docking/final_dock.py"),
    ("examples/organized/parking/park_mode.py", "commands/docking/park_mode.py"),

    # Radar / shared map
    ("examples/organized/radar/space_survey.py", "commands/radar/space_survey.py"),
    ("examples/organized/radar/ore_scanner.py", "commands/radar/ore_scanner.py"),
    ("examples/organized/radar/find_unlooted_asteroid.py", "commands/radar/find_unlooted_asteroid.py"),
    ("examples/organized/radar/basic/scan_contacts.py", "commands/radar/scan_contacts.py"),
    ("examples/organized/radar/shared_map/shared_map_sync.py", "commands/radar/shared_map_sync.py"),
    ("examples/organized/radar/shared_map/shared_map_report.py", "commands/radar/shared_map_report.py"),
    ("examples/organized/radar/shared_map/shared_map_deposits.py", "commands/radar/shared_map_deposits.py"),

    # Mining
    ("examples/organized/drill_nano/mine_ore_robot_safe_live_move.py", "commands/mining/mine_ore_robot_safe_live_move.py"),

    # Production / inventory / refinery
    ("examples/organized/assembler/basic/grid_production.py", "commands/production/grid_production.py"),
    ("examples/organized/assembler/basic/maintain_components.py", "commands/production/maintain_components.py"),
    ("examples/organized/refinery/refinery_priority_operator.py", "commands/refinery/refinery_priority_operator.py"),
    ("examples/organized/container/basic/containers_show.py", "commands/inventory/containers_show.py"),
    ("examples/organized/container/advanced/pull_items_from_docked_grid.py", "commands/inventory/pull_items_from_docked_grid.py"),

    # Projector / blueprints
    ("examples/organized/projector/align_clone_projection.py", "commands/projector/align_clone_projection.py"),
    ("examples/organized/projector/grid_blueprint_exporter.py", "commands/projector/grid_blueprint_exporter.py"),
    ("examples/organized/projector/grid_blueprint_loader.py", "commands/projector/grid_blueprint_loader.py"),
    ("examples/organized/projector/print_blueprints.py", "commands/projector/print_blueprints.py"),

    # Device-level operational helpers
    ("examples/organized/beacon/set_beacon_to_grid_name.py", "commands/devices/set_beacon_to_grid_name.py"),
    ("examples/organized/beacon/set_all_beacons_to_grid_name.py", "commands/devices/set_all_beacons_to_grid_name.py"),
)

EDUCATIONAL_EXAMPLE_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("examples/organized/basic/basic/fast_example.py", "examples/basic/connect_and_print_devices.py"),
    ("examples/organized/basic/basic/toggle_device.py", "examples/basic/toggle_device.py"),
    ("examples/organized/display/basic/display_hello.py", "examples/devices/display_hello.py"),
    ("examples/organized/lamp/intermediate/lamp_blink.py", "examples/devices/lamp_blink.py"),
    ("examples/organized/connector/basic/connector_scan_simple.py", "examples/devices/connector_scan_simple.py"),
    ("examples/organized/radar/basic/radar_controller_example.py", "examples/controllers/radar_controller_example.py"),
)

PLAYBOOK_MAPPINGS: tuple[tuple[str, str, str], ...] = (
    ("docs/agent-playbook/PLAYBOOK.md", "docs/playbooks/operator.md", "Operator playbook moved to `docs/playbooks/operator.md`."),
    ("docs/agent-dev/DEVGUIDE.md", "docs/playbooks/developer.md", "Developer playbook moved to `docs/playbooks/developer.md`."),
    ("admins/AGENTS.md", "docs/playbooks/admin.md", "Admin playbook copied to `docs/playbooks/admin.md`."),
)

ENV_EXAMPLE = """REDIS_USERNAME=
REDIS_PASSWORD=
SE_OWNER_ID=
SE_PLAYER_ID=
"""

AGENTS_MD = """# secontrol — Agent Entry Point

You are inside `secontrol`, a Python SDK and command toolkit for controlling Space Engineers agents through the Redis gateway.

## First rule

Do not start by editing code. First inspect the current grid state, available commands, and documentation.

## Fast local setup

```bash
python -m venv .venv
. .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e \".[dev]\"
cp .env.example .env
```

Fill `.env`:

```env
REDIS_USERNAME=
REDIS_PASSWORD=
SE_OWNER_ID=
SE_PLAYER_ID=
```

Credentials are obtained from the public entry point:

```text
https://www.outenemy.ru/se/
```

## Verify installation

```bash
python -c "import secontrol; print(secontrol.__file__)"
python commands/diagnostics/list_grids.py
```

## Choose your mode

### Operator mode

Use ready commands. Do not write code unless the task cannot be done with existing commands.

Start here:

```text
docs/playbooks/operator.md
commands/README.md
```

Common commands:

```bash
python commands/diagnostics/list_grids.py
python commands/diagnostics/check_flight_ready.py --grid agent1
python commands/radar/space_survey.py --grid agent1
python commands/radar/ore_scanner.py --grid agent1
python commands/navigation/space_navigator_v5.py --grid agent1 --nearest-asteroid
python commands/docking/check_docking_status.py --grid agent1
python commands/docking/dock.py agent1 farpost0
```

### Developer mode

Use this mode when changing SDK code, adding devices, adding controllers, or fixing command scripts.

Start here:

```text
docs/playbooks/developer.md
src/secontrol/
tests/
```

Before changing behavior:

```bash
pytest tests/
```

### Admin mode

Use this mode only for server-side actions: spawning grids, teleporting, deleting grids, managing factions, chat, voxels, or admin utilities.

Start here:

```text
docs/playbooks/admin.md
admins/
```

## Repository map

```text
src/secontrol/      Python SDK
commands/           runnable operational commands for agents
examples/           minimal educational examples
docs/playbooks/     operator, developer, admin guides
docs/workflows/     multi-step mission workflows
docs/skills/        reusable agent skills
tests/              automated tests
tmp/                temporary files only
```

## Temporary files

All generated scans, backups, logs, intermediate JSON files, and experiments must go to:

```text
tmp/
```

Do not create random files in the project root.
"""

COMMANDS_README = """# secontrol commands

Ready-to-run operational commands for Space Engineers agents.

These scripts are intended to be used directly by agents and operators. Keep educational API snippets in `examples/`; keep runnable workflows here.

## Diagnostics

```bash
python commands/diagnostics/list_grids.py
python commands/diagnostics/grid_report.py agent1
python commands/diagnostics/check_flight_ready.py --grid agent1
```

## Navigation

```bash
python commands/navigation/space_navigator_v5.py --grid agent1 --nearest-asteroid
python commands/navigation/space_navigator_v5.py --grid agent1 --target="GPS:Base:-137317:-111140:-82039:" --arrival 80
```

## Docking

```bash
python commands/docking/check_docking_status.py --grid agent1
python commands/docking/dock.py agent1 farpost0
python commands/docking/smooth_undock.py agent1 farpost0 40
```

## Radar and ores

```bash
python commands/radar/space_survey.py --grid agent1
python commands/radar/ore_scanner.py --grid agent1
python commands/radar/shared_map_report.py --grid agent1
python commands/radar/shared_map_deposits.py --grid agent1 --material Platinum --clusters --gps
```

## Mining

```bash
python commands/mining/mine_ore_robot_safe_live_move.py --grid agent1 --ore Platinum --amount 5000
```

## Production

```bash
python commands/production/grid_production.py --grid farpost0 --full
python commands/production/maintain_components.py --grid farpost0 --dry-run
python commands/production/maintain_components.py --grid farpost0
```

## Refinery

```bash
python commands/refinery/refinery_priority_operator.py --grid farpost0 --evaluate
python commands/refinery/refinery_priority_operator.py --grid farpost0 --apply
```

## Projector

```bash
python commands/projector/align_clone_projection.py farpost0 "C:\\Users\\root\\AppData\\Roaming\\SpaceEngineers\\Blueprints\\local\\skynet-agent0\\bp.sbc"
```

## Inventory

```bash
python commands/inventory/containers_show.py --grid farpost0
python commands/inventory/pull_items_from_docked_grid.py --source-grid agent1 --target-grid farpost0
```

## Rule for agents

1. Look for a ready command in `commands/`.
2. If no command exists, look for an SDK example in `examples/`.
3. If no example exists, read `docs/playbooks/developer.md` and then add code.
"""

EXAMPLES_README = """# secontrol examples

Small educational examples for learning the `secontrol` SDK.

Operational scripts have been moved to `commands/`. Use this directory for minimal API examples only.

## Basic

```bash
python examples/basic/connect_and_print_devices.py
python examples/basic/toggle_device.py
```

## Devices

```bash
python examples/devices/display_hello.py
python examples/devices/lamp_blink.py
python examples/devices/connector_scan_simple.py
```

## Controllers

```bash
python examples/controllers/radar_controller_example.py
```

## Difference between examples and commands

- `examples/` shows small SDK patterns.
- `commands/` contains tools that an agent can run in the live game world.
"""

DOCS_README = """# secontrol documentation

This directory contains documentation for operators, developers, administrators, workflows, skills, and API references.

## Start here

- `QUICKSTART_AGENT.md` — fastest local setup for an agent.
- `COMMANDS.md` — operational command catalog.
- `playbooks/operator.md` — commands and workflows for live game operation.
- `playbooks/developer.md` — SDK development and extension guide.
- `playbooks/admin.md` — server-side administrative actions.

## References

- `API_REFERENCE.md` — public SDK API.
- `DEVICE_REFERENCE.md` — supported Space Engineers device abstractions.
- `workflows/` — multi-step mission flows.
- `skills/` — reusable agent skills.
- `design/` — design notes and architectural decisions.
- `roadmap/` — roadmap, status, and technical debt.
"""

QUICKSTART_AGENT = """# Agent quick start

This guide is the shortest path from a fresh checkout to a working local agent environment.

## 1. Clone and install

```bash
git clone https://github.com/rootfabric/secontrol.git
cd secontrol

python -m venv .venv
. .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e \".[dev]\"
```

## 2. Configure Redis gateway access

Create `.env` in the repository root:

```env
REDIS_USERNAME=
REDIS_PASSWORD=
SE_OWNER_ID=
SE_PLAYER_ID=
```

`REDIS_USERNAME` and `REDIS_PASSWORD` are obtained from:

```text
https://www.outenemy.ru/se/
```

## 3. Verify installation

```bash
python -c "import secontrol; print(secontrol.__file__)"
python commands/diagnostics/list_grids.py
```

## 4. First useful commands

```bash
python commands/diagnostics/list_grids.py
python commands/diagnostics/check_flight_ready.py --grid agent1
python commands/radar/space_survey.py --grid agent1
python commands/radar/ore_scanner.py --grid agent1
python commands/navigation/space_navigator_v5.py --grid agent1 --nearest-asteroid
python commands/docking/check_docking_status.py --grid agent1
python commands/docking/dock.py agent1 farpost0
```

## 5. Where to go next

- Agent/operator guide: `docs/playbooks/operator.md`
- Developer guide: `docs/playbooks/developer.md`
- Admin guide: `docs/playbooks/admin.md`
- Commands catalog: `commands/README.md`
- SDK examples: `examples/README.md`
- Architecture: `ARCHITECTURE.md`
"""

COMMANDS_DOC = """# Commands catalog

The canonical command location is `commands/`.

Use `commands/README.md` for the compact command list. This document exists so documentation links can point to a stable docs path.

## Categories

- `commands/diagnostics/` — grid reports, readiness checks, device inspection.
- `commands/navigation/` — space navigation and voxel distance tools.
- `commands/docking/` — docking, undocking, connector checks.
- `commands/radar/` — space surveys, ore scans, shared-map reports.
- `commands/mining/` — Nanobot Drill mining workflows.
- `commands/production/` — assembler and component maintenance.
- `commands/refinery/` — refinery priority and queue control.
- `commands/projector/` — blueprint and projector workflows.
- `commands/inventory/` — containers and cross-grid item transfers.
- `commands/devices/` — small device operations that are useful in real runs.
"""

REDIRECT_EXAMPLES_MD = """# Examples Reference — moved

Operational scripts are now documented in:

```text
commands/README.md
docs/COMMANDS.md
```

Small SDK examples are documented in:

```text
examples/README.md
```

The old `examples/organized/` scripts are kept as compatibility wrappers where possible.
"""

README_QUICKSTART_BLOCK = """## Agent quick start

This repository contains:

- `src/secontrol/` — Python SDK for Space Engineers telemetry and control.
- `commands/` — ready-to-run operational commands for agents.
- `examples/` — small educational examples for learning the SDK.
- `docs/playbooks/` — operator, developer, and admin guides.

### 1. Clone and install

```bash
git clone https://github.com/rootfabric/secontrol.git
cd secontrol

python -m venv .venv
. .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e \".[dev]\"
```

### 2. Configure Redis gateway access

Create `.env` in the repository root:

```env
REDIS_USERNAME=
REDIS_PASSWORD=
SE_OWNER_ID=
SE_PLAYER_ID=
```

`REDIS_USERNAME` and `REDIS_PASSWORD` are obtained from:

```text
https://www.outenemy.ru/se/
```

### 3. Verify connection

```bash
python -c "import secontrol; print(secontrol.__file__)"
python commands/diagnostics/list_grids.py
```

### 4. First useful commands

```bash
# Show known grids
python commands/diagnostics/list_grids.py

# Check a ship before flight
python commands/diagnostics/check_flight_ready.py --grid agent1

# Survey nearby space
python commands/radar/space_survey.py --grid agent1

# Scan ores
python commands/radar/ore_scanner.py --grid agent1

# Fly to the nearest asteroid
python commands/navigation/space_navigator_v5.py --grid agent1 --nearest-asteroid

# Check docking status
python commands/docking/check_docking_status.py --grid agent1

# Dock ship to base
python commands/docking/dock.py agent1 farpost0
```

### 5. Where to go next

- Agent/operator guide: `docs/playbooks/operator.md`
- Developer guide: `docs/playbooks/developer.md`
- Admin guide: `docs/playbooks/admin.md`
- Commands catalog: `commands/README.md`
- SDK examples: `examples/README.md`
- Architecture: `ARCHITECTURE.md`
"""

README_COMMANDS_BLOCK = """## Commands

Ready-to-run operational scripts are located in [`commands`](commands). These are the scripts an agent should try first before writing new code.

Main categories:

- `commands/diagnostics/` — grid reports and readiness checks.
- `commands/navigation/` — flight and asteroid navigation.
- `commands/docking/` — connector docking and undocking.
- `commands/radar/` — space surveys, ore scans, shared-map reports.
- `commands/mining/` — Nanobot Drill mining workflows.
- `commands/production/` — assembler and component maintenance.
- `commands/refinery/` — refinery queue and priority control.
- `commands/projector/` — blueprint and projector workflows.
- `commands/inventory/` — container and cross-grid transfers.

See [`commands/README.md`](commands/README.md) for copy-paste commands.
"""

README_EXAMPLES_BLOCK = """## Examples

Minimal SDK examples are located in [`examples`](examples). They are intended for learning API patterns, not for operating a live agent.

Operational scripts moved to [`commands`](commands). The old `examples/organized/...` paths are kept as compatibility wrappers where possible.
"""

README_DOCS_BLOCK = """## Documentation

- [Agent quick start](docs/QUICKSTART_AGENT.md) - fastest local setup for an agent.
- [Commands catalog](commands/README.md) - ready-to-run operational commands.
- [Operator playbook](docs/playbooks/operator.md) - navigation, mining, construction, production, inventory, and monitoring.
- [Developer guide](docs/playbooks/developer.md) - project structure, APIs, controllers, devices, code conventions, and testing.
- [Admin guide](docs/playbooks/admin.md) - server administration, grid spawning, teleportation, chat, AI factions, and block/voxel operations.
- [API reference](docs/API_REFERENCE.md) - library API documentation.
- [Device reference](docs/DEVICE_REFERENCE.md) - supported Space Engineers device abstractions.
- [Architecture](ARCHITECTURE.md) - deeper architecture notes.
- [Wiki](https://github.com/rootfabric/secontrol/wiki/home) - project wiki.
"""

LEGACY_WRAPPER_TEMPLATE = '''#!/usr/bin/env python3
"""Compatibility wrapper.

This operational script was moved to `{target_path}`.
The old path is kept so existing playbooks and shell history keep working.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _add_repo_root_to_path() -> None:
    current = Path(__file__).resolve()
    for parent in (current.parent, *current.parents):
        if (parent / "pyproject.toml").exists() and (parent / "commands").exists():
            sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Cannot locate secontrol repository root")


if __name__ == "__main__":
    _add_repo_root_to_path()
    runpy.run_module("{module_name}", run_name="__main__")
'''

REDIRECT_TEMPLATE = """# Moved

{message}

Current path:

```text
{target_path}
```
"""


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for parent in (current, *current.parents):
        if all((parent / marker).exists() for marker in ROOT_MARKERS):
            return parent
    raise SystemExit("ERROR: run this script from the root of the secontrol repository")


def timestamp() -> str:
    return _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_package_dirs(root: Path, relative_file_path: str) -> None:
    path = root / relative_file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    relative_parts = Path(relative_file_path).parent.parts
    if not relative_parts:
        return
    accumulated = root
    for part in relative_parts:
        accumulated = accumulated / part
        if part in {"commands"} or "commands" in accumulated.parts:
            init_file = accumulated / "__init__.py"
            if not init_file.exists():
                init_file.write_text("\"\"\"Runnable secontrol command package.\"\"\"\n", encoding="utf-8")


def backup_file(root: Path, relative_path: str) -> None:
    source = root / relative_path
    if not source.exists() or source.is_dir():
        return
    backup = root / BACKUP_DIR / timestamp() / relative_path
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)


def write_text(root: Path, relative_path: str, content: str, backup: bool = True) -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists() and target.is_file():
        backup_file(root, relative_path)
    target.write_text(content, encoding="utf-8", newline="\n")


def copy_file(root: Path, source_relative: str, target_relative: str) -> bool:
    source = root / source_relative
    target = root / target_relative
    if not source.exists() or not source.is_file():
        return False
    ensure_package_dirs(root, target_relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup_file(root, target_relative)
    shutil.copy2(source, target)
    copy_sidecar_files(source, target.parent)
    return True


def copy_sidecar_files(source: Path, target_dir: Path) -> None:
    for pattern in ("*.json", "*.toml", "*.yaml", "*.yml", "README.md"):
        for sidecar in source.parent.glob(pattern):
            if sidecar.name == source.name:
                continue
            destination = target_dir / sidecar.name
            if not destination.exists():
                shutil.copy2(sidecar, destination)


def module_name_from_command_path(command_path: str) -> str:
    path = Path(command_path).with_suffix("")
    return ".".join(path.parts)


def replace_old_script_with_wrapper(root: Path, old_relative: str, new_relative: str) -> None:
    old_path = root / old_relative
    if not old_path.exists() or not old_path.is_file():
        return
    module_name = module_name_from_command_path(new_relative)
    wrapper = LEGACY_WRAPPER_TEMPLATE.format(target_path=new_relative, module_name=module_name)
    write_text(root, old_relative, wrapper, backup=True)


def copy_tree_if_exists(root: Path, source_relative: str, target_relative: str) -> None:
    source = root / source_relative
    target = root / target_relative
    if not source.exists() or not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)


def replace_section(content: str, heading: str, replacement: str) -> str:
    pattern = re.compile(rf"(?ms)^## {re.escape(heading)}\n.*?(?=^## |\Z)")
    if pattern.search(content):
        return pattern.sub(replacement.rstrip() + "\n\n", content, count=1)
    return content.rstrip() + "\n\n" + replacement.rstrip() + "\n"


def update_readme(root: Path) -> None:
    readme_path = root / "README.md"
    if not readme_path.exists():
        write_text(root, "README.md", README_QUICKSTART_BLOCK)
        return

    content = readme_path.read_text(encoding="utf-8")
    if "## Agent quick start" not in content:
        marker = "Public entry point: <https://www.outenemy.ru/se/>"
        if marker in content:
            content = content.replace(marker, marker + "\n\n" + README_QUICKSTART_BLOCK, 1)
        else:
            lines = content.splitlines()
            if lines and lines[0].startswith("# "):
                content = lines[0] + "\n\n" + README_QUICKSTART_BLOCK + "\n\n" + "\n".join(lines[1:])
            else:
                content = README_QUICKSTART_BLOCK + "\n\n" + content

    content = replace_section(content, "Commands", README_COMMANDS_BLOCK)
    content = replace_section(content, "Examples", README_EXAMPLES_BLOCK)
    content = replace_section(content, "Documentation", README_DOCS_BLOCK)
    write_text(root, "README.md", content, backup=True)


def create_docs(root: Path) -> None:
    write_text(root, ".env.example", ENV_EXAMPLE, backup=False)
    write_text(root, "AGENTS.md", AGENTS_MD)
    write_text(root, "commands/README.md", COMMANDS_README, backup=False)
    write_text(root, "examples/README.md", EXAMPLES_README, backup=False)
    write_text(root, "docs/README.md", DOCS_README, backup=False)
    write_text(root, "docs/QUICKSTART_AGENT.md", QUICKSTART_AGENT, backup=False)
    write_text(root, "docs/COMMANDS.md", COMMANDS_DOC, backup=False)

    for directory in ("docs/playbooks", "docs/design", "docs/roadmap", "docs/archive", "tmp"):
        (root / directory).mkdir(parents=True, exist_ok=True)

    for source, target, message in PLAYBOOK_MAPPINGS:
        source_path = root / source
        if source_path.exists() and source_path.is_file():
            target_path = root / target
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if not target_path.exists():
                shutil.copy2(source_path, target_path)
            if source != "admins/AGENTS.md":
                write_text(root, source, REDIRECT_TEMPLATE.format(message=message, target_path=target), backup=True)

    copy_tree_if_exists(root, "docs/agent-skills", "docs/skills")

    examples_doc = root / "docs/EXAMPLES.md"
    if examples_doc.exists():
        write_text(root, "docs/EXAMPLES.md", REDIRECT_EXAMPLES_MD, backup=True)


def create_commands(root: Path) -> tuple[int, list[str]]:
    copied = 0
    missing: list[str] = []

    for source, target in COMMAND_MAPPINGS:
        if copy_file(root, source, target):
            replace_old_script_with_wrapper(root, source, target)
            copied += 1
        else:
            missing.append(source)

    for source, target in EDUCATIONAL_EXAMPLE_MAPPINGS:
        if copy_file(root, source, target):
            copied += 1
        else:
            missing.append(source)

    return copied, missing


def write_manifest(root: Path, copied: int, missing: list[str]) -> None:
    lines = [
        "# Refactor manifest",
        "",
        f"Applied at: {timestamp()}",
        "",
        f"Copied files: {copied}",
        f"Missing source files: {len(missing)}",
        "",
    ]
    if missing:
        lines.append("## Missing files")
        lines.append("")
        lines.extend(f"- `{item}`" for item in missing)
        lines.append("")
    lines.extend(
        [
            "## Created/updated entry points",
            "",
            "- `AGENTS.md`",
            "- `README.md`",
            "- `.env.example`",
            "- `commands/README.md`",
            "- `examples/README.md`",
            "- `docs/README.md`",
            "- `docs/QUICKSTART_AGENT.md`",
            "- `docs/COMMANDS.md`",
            "- `docs/playbooks/operator.md`",
            "- `docs/playbooks/developer.md`",
            "- `docs/playbooks/admin.md`",
            "",
        ]
    )
    write_text(root, "tmp/refactor_manifest.md", "\n".join(lines), backup=False)


def run_syntax_check(root: Path) -> int:
    check_targets = [root / "commands", root / "examples" / "basic", root / "examples" / "devices", root / "examples" / "controllers"]
    python_files = [str(path) for target in check_targets if target.exists() for path in target.rglob("*.py")]
    if not python_files:
        return 0
    import py_compile

    errors = 0
    for file_name in python_files:
        try:
            py_compile.compile(file_name, doraise=True)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"SYNTAX ERROR: {file_name}: {exc}", file=sys.stderr)
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply secontrol documentation and command-tree refactor")
    parser.add_argument("--root", default=".", help="Path to secontrol repository root")
    parser.add_argument("--skip-syntax-check", action="store_true", help="Skip py_compile syntax checks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(args.root))
    os.chdir(root)

    create_docs(root)
    copied, missing = create_commands(root)
    update_readme(root)
    write_manifest(root, copied, missing)

    syntax_errors = 0
    if not args.skip_syntax_check:
        syntax_errors = run_syntax_check(root)

    print(f"Refactor applied in: {root}")
    print(f"Copied files: {copied}")
    print(f"Missing source files: {len(missing)}")
    if missing:
        print("Missing files are listed in tmp/refactor_manifest.md")
    if syntax_errors:
        print(f"Syntax errors: {syntax_errors}", file=sys.stderr)
        return 2
    print("Syntax check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
