# secontrol — Agent Index

Quick-nav for AI agents. Two tracks:

---

## In-game tasks (flight, building, docking, mining)

**Start here:** `docs/agent-skills/README.md` — full skill list with descriptions

| Task | Doc |
|---|---|
| **Flight / Navigation** | `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md` |
| **Docking** | `docs/workflows/docking.md` |
| **Building (projector + welder)** | `agent/skills/se-projection-builder.md` |
| **Approach asteroid** | `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md` |
| **Grid status report** | `docs/agent-skills/gaming/se-grid-status-report/SKILL.md` |
| **Production / Assembler** | `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md` |
| **Blueprint XML** | `docs/agent-skills/gaming/secontrol-space-engineers/references/blueprint-editing.md` |
| **Radar / Voxel scanning** | `docs/agent-skills/gaming/secontrol-space-engineers/references/asteroid-scanning.md` |
| **Redis monitoring** | `docs/agent-skills/gaming/game-server-automation/SKILL.md` |

---

## Library development (adding devices, fixing bugs, extending)

**Start here:** `agent/REPO_GUIDE.md` — full developer reference

| Task | Doc |
|---|---|
| **Source structure** | `src/secontrol/` (see REPO_GUIDE.md for map) |
| **API reference** | `docs/API_REFERENCE.md` |
| **Device reference** | `docs/DEVICE_REFERENCE.md` |
| **Examples catalog** | `docs/EXAMPLES.md` |
| **Architecture** | `ARCHITECTURE.md` |
| **Tech debt** | `docs/exec-plans/tech-debt-tracker.md` |
| **Design decisions** | `docs/design-docs/index.md` |
| **Run tests** | `pytest tests/` |
| **Build package** | `python -m build` |

---

## Required env vars

```
REDIS_USERNAME     # from outenemy.ru/se
REDIS_PASSWORD     # from outenemy.ru/se
SE_OWNER_ID        # Space Engineers owner ID
SE_PLAYER_ID       # Player ID (falls back to owner)
```

Place in `.env` at project root.