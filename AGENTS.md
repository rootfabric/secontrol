# secontrol — Agent Index

Quick-nav for AI agents. Two tracks:

---

## Space Survival (космос — полёты, парковка, майнинг)

Для любых действий в космосе — агент должен начинать отсюда.

### Перелёты

| Task | Doc |
|---|---|
| **Полёт в космосе** (между астероидами, к базе) | `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md` → `SpaceNavigatorController` |
| **Полёт к астероиду** (готовый скилл) | `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md` |
| **Примеры** | `examples/space_flight/space_navigator_v4.py` |

### Парковка / точные перемещения

| Task | Doc |
|---|---|
| **Стыковка** (коннектор к коннектору) | `docs/agent-skills/gaming/secontrol-space-engineers/references/space-docking.md` + `docs/workflows/docking.md` |
| **Sub-meter maneuvers** (парковка, финальное сближение) | `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md` → low-level `rc.goto()` / `fly_to_point()` |

### Добыча ресурсов

| Task | Doc |
|---|---|
| **Бурение наносборщиком** | `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-mining-workflow.md` |
| **Скан руды** (Voxel / OreDetector) | `docs/agent-skills/gaming/secontrol-space-engineers/references/asteroid-scanning.md` + `ore_deposit_scanner.py` |
| **Скан месторождений** (готовый скрипт) | `examples/organized/radar/ore_deposit_scanner.py` |

---

## Build & Deploy (строительство, производство, мониторинг)

### Строительство

| Task | Doc |
|---|---|
| **Строительство блоков** (проектор + BARS) | `agent/skills/se-projection-builder.md` |
| **Blueprint XML** | `docs/agent-skills/gaming/secontrol-space-engineers/references/blueprint-editing.md` |
| **Покраска / разборка блоков** | `docs/agent-skills/gaming/se-projection-builder/references/grind-mode-detail.md` + `color-conversion.md` |

### Производство / инвентарь

| Task | Doc |
|---|---|
| **Production / Assembler** | `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md` |
| **Статус грида** (блоки, повреждения, контейнеры) | `docs/agent-skills/gaming/se-grid-status-report/SKILL.md` |

### Мониторинг

| Task | Doc |
|---|---|
| **Redis мониторинг, алерты** | `docs/agent-skills/gaming/game-server-automation/SKILL.md` |

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

---

## Временные файлы

Все временные файлы (сканы, бэкапы, промежуточные данные и т.д.) помещать в папку `tmp/` в корне проекта. Не создавать временные файлы в корне или в других местах проекта.