# AgentMap error-fix instructions

This report is written as a task file for an AI coding agent.

## Project

- Root: `C:\secontrol`
- Scope: all instruction files
- Generated at: `2026-05-30 02:45:39 UTC`
- Broken links found: `12`
- Existing linked files not indexed as instructions: `92`
- Documents with warnings: `1`

## Agent task

Fix all detected instruction-map errors from this report without changing product code behavior.

## Base repair prompt

Use this full section as the default prompt for a coding agent that will repair AgentMap findings.

### Command 1 — Fix broken links

Fix all AgentMap broken links in the selected scope, and review existing linked files that are not indexed as instruction documents.

Rules:

1. Only edit documentation and agent instruction files.
2. Do not change product code behavior.
3. Open every source document and inspect the exact source line from this report.
4. For each broken path, check whether the target file was renamed, moved, or never existed.
5. If the target exists elsewhere, replace the broken mention with a correct relative Markdown link or a correct project-root path.
6. If the target is outside the repository, mark it as a runtime path and rewrite it as a non-link path pattern.
7. If the mention is only an example, rewrite it as an explicit pattern, for example with `<name>` placeholders, so it is not interpreted as a real file path.
8. Do not silently replace `AGENT_INSTRUCTIONS.md` with `AGENTS.md` unless the referenced runbook content is actually inside `AGENTS.md`.
9. Run `python -m agentmap scan <project-root>` after editing.
10. The final result should have `broken_links: 0` for this scope, or every remaining broken link must have an explicit reason.
11. For every `not indexed as instruction` item, either add it to the AgentMap instruction index/config, link to its parent instruction explicitly, or classify it as a product/code file that should not be indexed.

### Command 2 — Fix or classify orphan instruction documents

Fix AgentMap orphan instruction documents and warnings in the selected scope.

Goal: every important `AGENTS.md`, `SKILL.md`, runbook, workflow, prompt, and agent reference document must be reachable from root `AGENTS.md`, `docs/agent/index.md`, or a central skill/index document.

Rules:

1. Do not blindly link every file from root.
2. Add intermediate indexes where useful, for example `AGENTS.md -> docs/agent-skills/README.md -> individual SKILL.md -> references/*.md`.
3. Add explicit Markdown links from parent instructions to child runbooks/skills.
4. Add parent backlinks from detailed references to their owning `SKILL.md` or `AGENTS.md` when useful.
5. If a document is intentionally orphan, add a clear explanation in the document or in `.agentmap.json` ignore/classification rules.
6. Do not change product code behavior.
7. Run `python -m agentmap scan <project-root>` and summarize the new broken-link, orphan, and warning counts.

## Ready-to-send agent prompt

Fix every broken link, orphan/warning, and instruction-map issue detected by AgentMap in `C:\secontrol`. Use this report as the authoritative task list. Execute Command 1 first, then Command 2. Do not change product code behavior; only update instruction/runbook links, examples, path patterns, or documentation routing. After changes, run `python -m agentmap scan C:\secontrol` and summarize old vs new counts.

## Broken links to fix

### `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md:230`
  - Broken target: `logs/active_alert.json`
  - Edge type: `broken_path_mention`
  - Original text: `logs/active_alert.json`
  - Required action: verify the intended destination and update the source document.

### `docs/agent-skills/gaming/secontrol-space-engineers/references/pitfalls.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/pitfalls.md:129`
  - Broken target: `script.py`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/script.py`
  - Required action: verify the intended destination and update the source document.

### `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:16`
  - Broken target: `active_alert.json`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/active_alert.json`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:23`
  - Broken target: `processed_alerts.json`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/processed_alerts.json`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:37`
  - Broken target: `.hermes/scripts/se_player_scan.py`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/.hermes/scripts/se_player_scan.py`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:38`
  - Broken target: `.hermes/scripts/se_alert_watcher.py`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/.hermes/scripts/se_alert_watcher.py`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:39`
  - Broken target: `.hermes/scripts/se_alert_agent.py`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/.hermes/scripts/se_alert_agent.py`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:40`
  - Broken target: `.hermes/scripts/logs/active_alert.json`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/.hermes/scripts/logs/active_alert.json`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/se-monitoring-pipeline.md:41`
  - Broken target: `.hermes/scripts/logs/processed_alerts.json`
  - Edge type: `broken_absolute_path_mention`
  - Original text: `/.hermes/scripts/logs/processed_alerts.json`
  - Required action: verify the intended destination and update the source document.

### `docs/workflows/docking.md`

- Source line: `docs/workflows/docking.md:14`
  - Broken target: `se-data/scripts/docking/dock.py`
  - Edge type: `broken_path_mention`
  - Original text: `se-data/scripts/docking/dock.py`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/workflows/docking.md:15`
  - Broken target: `se-data/scripts/docking/01_approach_point.py`
  - Edge type: `broken_path_mention`
  - Original text: `se-data/scripts/docking/01_approach_point.py`
  - Required action: verify the intended destination and update the source document.
- Source line: `docs/workflows/docking.md:16`
  - Broken target: `se-data/scripts/docking/03_connector_approach.py`
  - Edge type: `broken_path_mention`
  - Original text: `se-data/scripts/docking/03_connector_approach.py`
  - Required action: verify the intended destination and update the source document.

## Existing linked files not indexed as instructions

These links point to files that exist on disk, but AgentMap did not include them as instruction documents. They are not broken filesystem links, but they may be missing from the agent instruction map.

### `AGENTS.md`

- Source line: `AGENTS.md:21`
  - Existing target not indexed: `scripts/space_navigator_v4.py`
  - Edge type: `path_mention`
  - Original text: `scripts/space_navigator_v4.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:21`
  - Existing target not indexed: `scripts/test_flight_10km.py`
  - Edge type: `path_mention`
  - Original text: `scripts/test_flight_10km.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:27`
  - Existing target not indexed: `examples/organized/parking/check_docking_status.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/parking/check_docking_status.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:28`
  - Existing target not indexed: `examples/organized/parking/README.md`
  - Edge type: `path_mention`
  - Original text: `examples/organized/parking/README.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:43`
  - Existing target not indexed: `examples/organized/radar/ore_deposit_scanner.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/ore_deposit_scanner.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:61`
  - Existing target not indexed: `examples/organized/container/advanced/pull_items_from_docked_grid.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/container/advanced/pull_items_from_docked_grid.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:75`
  - Existing target not indexed: `examples/organized/beacon/set_beacon_to_grid_name.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/beacon/set_beacon_to_grid_name.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:76`
  - Existing target not indexed: `examples/organized/grid/intermediate/grid_rename_device_example.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/grid/intermediate/grid_rename_device_example.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:87`
  - Existing target not indexed: `src/secontrol`
  - Edge type: `directory_mention`
  - Original text: `src/secontrol/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:88`
  - Existing target not indexed: `docs/API_REFERENCE.md`
  - Edge type: `path_mention`
  - Original text: `docs/API_REFERENCE.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:92`
  - Existing target not indexed: `docs/exec-plans/tech-debt-tracker.md`
  - Edge type: `path_mention`
  - Original text: `docs/exec-plans/tech-debt-tracker.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `AGENTS.md:93`
  - Existing target not indexed: `docs/design-docs/index.md`
  - Edge type: `path_mention`
  - Original text: `docs/design-docs/index.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `admins/ai_factions/AGENTS.md`

- Source line: `admins/ai_factions/AGENTS.md:45`
  - Existing target not indexed: `admins/ai_factions/admin_create_ai_faction_and_redis_user.py`
  - Edge type: `path_mention`
  - Original text: `admins/ai_factions/admin_create_ai_faction_and_redis_user.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `admins/ai_factions/AGENTS.md:68`
  - Existing target not indexed: `admins/ai_factions/admin_assign_or_remove_grid.py`
  - Edge type: `path_mention`
  - Original text: `admins/ai_factions/admin_assign_or_remove_grid.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `admins/ai_factions/AGENTS.md:81`
  - Existing target not indexed: `admins/ai_factions/admin_spawn_grid_for_faction.py`
  - Edge type: `path_mention`
  - Original text: `admins/ai_factions/admin_spawn_grid_for_faction.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `admins/ai_factions/AGENTS.md:99`
  - Existing target not indexed: `admins/ai_factions/admin_faction_join_policy.py`
  - Edge type: `path_mention`
  - Original text: `admins/ai_factions/admin_faction_join_policy.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `agent/README.md`

- Source line: `agent/README.md:16`
  - Existing target not indexed: `agent/skills`
  - Edge type: `directory_mention`
  - Original text: `agent/skills/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `agent/REPO_GUIDE.md`

- Source line: `agent/REPO_GUIDE.md:28`
  - Existing target not indexed: `src/secontrol`
  - Edge type: `directory_mention`
  - Original text: `src/secontrol/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:146`
  - Existing target not indexed: `src/secontrol/devices`
  - Edge type: `directory_mention`
  - Original text: `src/secontrol/devices/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:147`
  - Existing target not indexed: `src/secontrol/devices/__init__.py`
  - Edge type: `path_mention`
  - Original text: `src/secontrol/devices/__init__.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:149`
  - Existing target not indexed: `src/secontrol/base_device.py`
  - Edge type: `path_mention`
  - Original text: `src/secontrol/base_device.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:194`
  - Existing target not indexed: `ARCHITECTURE.md`
  - Edge type: `markdown_link`
  - Original text: `ARCHITECTURE.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:195`
  - Existing target not indexed: `docs/API_REFERENCE.md`
  - Edge type: `markdown_link`
  - Original text: `docs/API_REFERENCE.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:198`
  - Existing target not indexed: `docs/design-docs/index.md`
  - Edge type: `markdown_link`
  - Original text: `docs/design-docs/index.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:199`
  - Existing target not indexed: `docs/exec-plans/tech-debt-tracker.md`
  - Edge type: `markdown_link`
  - Original text: `docs/exec-plans/tech-debt-tracker.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `agent/REPO_GUIDE.md:202`
  - Existing target not indexed: `CHANGELOG.md`
  - Edge type: `markdown_link`
  - Original text: `CHANGELOG.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/DEVICE_REFERENCE.md`

- Source line: `docs/DEVICE_REFERENCE.md:3`
  - Existing target not indexed: `src/secontrol/devices`
  - Edge type: `directory_mention`
  - Original text: `src/secontrol/devices/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/EXAMPLES.md`

- Source line: `docs/EXAMPLES.md:3`
  - Existing target not indexed: `examples/organized`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:19`
  - Existing target not indexed: `examples/organized/basic/basic/fast_example.py`
  - Edge type: `path_mention`
  - Original text: `basic/basic/fast_example.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:20`
  - Existing target not indexed: `examples/organized/basic/basic/toggle_device.py`
  - Edge type: `path_mention`
  - Original text: `basic/basic/toggle_device.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:21`
  - Existing target not indexed: `examples/organized/basic/intermediate/gui_telemetry_viewer.py`
  - Edge type: `path_mention`
  - Original text: `basic/intermediate/gui_telemetry_viewer.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:22`
  - Existing target not indexed: `examples/organized/basic/intermediate/ore_scan.py`
  - Edge type: `path_mention`
  - Original text: `basic/intermediate/ore_scan.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:23`
  - Existing target not indexed: `examples/organized/basic/intermediate/nanobot_drill_filter_example.py`
  - Edge type: `path_mention`
  - Original text: `basic/intermediate/nanobot_drill_filter_example.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:80`
  - Existing target not indexed: `examples/organized/connector/basic/connector_full_demo.py`
  - Edge type: `path_mention`
  - Original text: `basic/connector_full_demo.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:81`
  - Existing target not indexed: `examples/organized/connector/basic/connector_scan_simple.py`
  - Edge type: `path_mention`
  - Original text: `basic/connector_scan_simple.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:89`
  - Existing target not indexed: `examples/organized/container/basic`
  - Edge type: `directory_mention`
  - Original text: `container/basic/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:95`
  - Existing target not indexed: `examples/organized/container/intermediate`
  - Edge type: `directory_mention`
  - Original text: `container/intermediate/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:104`
  - Existing target not indexed: `examples/organized/container/advanced`
  - Edge type: `directory_mention`
  - Original text: `container/advanced/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:111`
  - Existing target not indexed: `examples/organized/inventory/advanced`
  - Edge type: `directory_mention`
  - Original text: `inventory/advanced/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:302`
  - Existing target not indexed: `examples/organized/refinery/intermediate/refinery_queue_example.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/refinery_queue_example.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:303`
  - Existing target not indexed: `examples/organized/refinery/intermediate/refinery_priority.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/refinery_priority.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:313`
  - Existing target not indexed: `examples/organized/assembler/intermediate/assembler_queue_viewer.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/assembler_queue_viewer.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:314`
  - Existing target not indexed: `examples/organized/assembler/intermediate/assembler_queue_clear.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/assembler_queue_clear.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:315`
  - Existing target not indexed: `examples/organized/assembler/intermediate/assembler_blueprints_viewer.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/assembler_blueprints_viewer.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:316`
  - Existing target not indexed: `examples/organized/assembler/advanced/assembler_produce.py`
  - Edge type: `path_mention`
  - Original text: `advanced/assembler_produce.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:326`
  - Existing target not indexed: `examples/organized/lamp/intermediate/lamp_blink.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/lamp_blink.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:327`
  - Existing target not indexed: `examples/organized/lamp/intermediate/lamp_blind.py`
  - Edge type: `path_mention`
  - Original text: `intermediate/lamp_blind.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:337`
  - Existing target not indexed: `examples/organized/artillery/basic/artillery_fire.py`
  - Edge type: `path_mention`
  - Original text: `basic/artillery_fire.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:353`
  - Existing target not indexed: `examples/organized/parking`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/parking/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:371`
  - Existing target not indexed: `examples/organized/parking/README.md`
  - Edge type: `path_mention`
  - Original text: `examples/organized/parking/README.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/EXAMPLES.md:506`
  - Existing target not indexed: `docs/API_REFERENCE.md`
  - Edge type: `markdown_link`
  - Original text: `API_REFERENCE.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/NANOBOT_DRILL_ANALYSIS.md`

- Source line: `docs/NANOBOT_DRILL_ANALYSIS.md:186`
  - Existing target not indexed: `examples/organized/basic/intermediate/nanobot_drill_filter_example.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/basic/intermediate/nanobot_drill_filter_example.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/NANOBOT_DRILL_ANALYSIS.md:195`
  - Existing target not indexed: `examples/organized/autopilot/harvest/simple_nano_focus_to_res.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/autopilot/harvest/simple_nano_focus_to_res.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/NANOBOT_DRILL_ANALYSIS.md:213`
  - Existing target not indexed: `examples/organized/autopilot/harvest/harvest_full.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/autopilot/harvest/harvest_full.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/README.md`

- Source line: `docs/agent-skills/README.md:4`
  - Existing target not indexed: `docs/agent-skills/gaming`
  - Edge type: `directory_mention`
  - Original text: `docs/agent-skills/gaming/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/README.md:20`
  - Existing target not indexed: `docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py`
  - Edge type: `markdown_link`
  - Original text: `se-grid-status-report/scripts/grid_report.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/game-server-automation/SKILL.md`

- Source line: `docs/agent-skills/gaming/game-server-automation/SKILL.md:144`
  - Existing target not indexed: `examples/organized`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/game-server-automation/SKILL.md:144`
  - Existing target not indexed: `examples/organized/parking`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/parking/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/game-server-automation/SKILL.md:164`
  - Existing target not indexed: `ARCHITECTURE.md`
  - Edge type: `markdown_link`
  - Original text: `ARCHITECTURE.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md`

- Source line: `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md:26`
  - Existing target not indexed: `examples/space_flight/test_flight_nearest_asteroid.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/test_flight_nearest_asteroid.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md:56`
  - Existing target not indexed: `examples/space_flight/test_flight_10km.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/test_flight_10km.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md:57`
  - Existing target not indexed: `examples/space_flight/space_navigator_v4.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/space_navigator_v4.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md:58`
  - Existing target not indexed: `src/secontrol/controllers/space_navigator_controller.py`
  - Edge type: `path_mention`
  - Original text: `src/secontrol/controllers/space_navigator_controller.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/se-grid-status-report/SKILL.md`

- Source line: `docs/agent-skills/gaming/se-grid-status-report/SKILL.md:30`
  - Existing target not indexed: `docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py`
  - Edge type: `path_mention`
  - Original text: `docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/se-grid-status-report/SKILL.md:149`
  - Existing target not indexed: `examples/organized/diagnostics/check_flight_ready.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/diagnostics/check_flight_ready.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md:33`
  - Existing target not indexed: `docs/API_REFERENCE.md`
  - Edge type: `path_mention`
  - Original text: `docs/API_REFERENCE.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md:37`
  - Existing target not indexed: `docs/design-docs/index.md`
  - Edge type: `path_mention`
  - Original text: `docs/design-docs/index.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md:38`
  - Existing target not indexed: `docs/exec-plans/tech-debt-tracker.md`
  - Edge type: `path_mention`
  - Original text: `docs/exec-plans/tech-debt-tracker.md`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md:211`
  - Existing target not indexed: `examples/organized/radar/ore_deposit_scanner.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/ore_deposit_scanner.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-mining-workflow.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-mining-workflow.md:12`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_deposits.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_deposits.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-mining-workflow.md:17`
  - Existing target not indexed: `examples/organized/radar/ore_deposit_scanner.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/ore_deposit_scanner.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-mining-workflow.md:34`
  - Existing target not indexed: `examples/space_flight/space_navigator_v4.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/space_navigator_v4.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-mining-workflow.md:41`
  - Existing target not indexed: `examples/organized/drill_nano`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/drill_nano/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md:19`
  - Existing target not indexed: `examples/organized/diagnostics/check_flight_ready.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/diagnostics/check_flight_ready.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md:65`
  - Existing target not indexed: `examples/space_flight/space_navigator_v4.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/space_navigator_v4.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md:87`
  - Existing target not indexed: `examples/organized/parking/dock.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/parking/dock.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/agent-skills/gaming/secontrol-space-engineers/references/space-docking.md`

- Source line: `docs/agent-skills/gaming/secontrol-space-engineers/references/space-docking.md:171`
  - Existing target not indexed: `scripts/space_docker.py`
  - Edge type: `path_mention`
  - Original text: `scripts/space_docker.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/workflows/ore-mining-workflow.md`

- Source line: `docs/workflows/ore-mining-workflow.md:9`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_deposits.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_deposits.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/ore-mining-workflow.md:14`
  - Existing target not indexed: `examples/organized/radar/ore_deposit_scanner.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/ore_deposit_scanner.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/ore-mining-workflow.md:18`
  - Existing target not indexed: `examples/space_flight/space_navigator_v4.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/space_navigator_v4.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/ore-mining-workflow.md:25`
  - Existing target not indexed: `examples/organized/drill_nano`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/drill_nano/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/ore-mining-workflow.md:54`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_report.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_report.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/ore-mining-workflow.md:64`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_scan.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_scan.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `docs/workflows/space-navigator-v4.md`

- Source line: `docs/workflows/space-navigator-v4.md:9`
  - Existing target not indexed: `examples/space_flight/space_navigator_v4.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/space_navigator_v4.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/space-navigator-v4.md:39`
  - Existing target not indexed: `examples/space_flight/test_flight_10km.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/test_flight_10km.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `docs/workflows/space-navigator-v4.md:42`
  - Existing target not indexed: `examples/space_flight/test_flight_nearest_asteroid.py`
  - Edge type: `path_mention`
  - Original text: `examples/space_flight/test_flight_nearest_asteroid.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `examples/organized/drill_nano/nanodrill_agent.md`

- Source line: `examples/organized/drill_nano/nanodrill_agent.md:212`
  - Existing target not indexed: `examples/organized/drill_nano`
  - Edge type: `directory_mention`
  - Original text: `examples/organized/drill_nano/`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

### `examples/organized/radar/shared_map/AGENTS.md`

- Source line: `examples/organized/radar/shared_map/AGENTS.md:16`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_scan.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_scan.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `examples/organized/radar/shared_map/AGENTS.md:31`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_deposits.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_deposits.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `examples/organized/radar/shared_map/AGENTS.md:48`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_report.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_report.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `examples/organized/radar/shared_map/AGENTS.md:58`
  - Existing target not indexed: `examples/organized/radar/shared_map/shared_map_memory.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/shared_map_memory.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.
- Source line: `examples/organized/radar/shared_map/AGENTS.md:66`
  - Existing target not indexed: `examples/organized/radar/shared_map/clear_ore_data.py`
  - Edge type: `path_mention`
  - Original text: `examples/organized/radar/shared_map/clear_ore_data.py`
  - Required action: decide whether this file should become an indexed instruction/runbook, should be linked through a parent instruction, or should remain a normal product/code reference.

## Additional instruction-map warnings

### `docs/agent-skills/gaming/secontrol-space-engineers/references/pitfalls.md`

- Document is larger than 32 KiB; some agents may truncate project instructions.

## Expected final response

When the fixes are done, summarize:

- which source documents were edited;
- which broken links were fixed;
- which links were intentionally converted to examples or path patterns;
- the new AgentMap scan summary.
