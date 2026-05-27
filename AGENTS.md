# secontrol — Agent Index

Quick-nav for AI agents. Two tracks:

---

## Space Survival (космос — полёты, парковка, майнинг)

**⚡ ПЕРВОЕ — посмотри готовые скрипты:**
👉 `docs/agent-skills/gaming/secontrol-space-engineers/OPERATIONS.md`

Там все готовые решения: навигация, докинг, добыча, диагностика.

### Перелёты

| Task | Doc |
|---|---|
|| **Полёт в космосе** (между астероидами, к базе) | `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md` → `SpaceNavigatorController` |
|| **Полёт к астероиду** (готовый скилл) | `docs/agent-skills/gaming/se-asteroid-approach/SKILL.md` |
|| **Примеры полётов** | `scripts/space_navigator_v4.py`, `scripts/test_flight_10km.py` |

### Парковка / точные перемещения

| Task | Doc |
|---|---|
| **Проверить парковку гридов** | `examples/organized/parking/check_docking_status.py` |
| **Парковка дронов (полный справочник)** | `examples/organized/parking/README.md` |
| **Стыковка** (коннектор к коннектору) | `docs/agent-skills/gaming/secontrol-space-engineers/references/space-docking.md` + `docs/workflows/docking.md` |
| **Sub-meter maneuvers** (парковка, финальное сближение) | `docs/agent-skills/gaming/secontrol-space-engineers/references/navigation-and-flight.md` → low-level `rc.goto()` / `fly_to_point()` |

### Добыча ресурсов

| Task | Doc |
|---|---|
| **Проверить разведанные руды** (SharedMapController / JSON) | `examples/organized/radar/shared_map/AGENTS.md` → `shared_map_deposits.py` / `shared_map_report.py` |
| **Бурение наносборщиком** | `examples/organized/drill_nano/nanodrill_agent.md` — полная инструкция по Nanobot Drill (мод Outenemy) + рабочие скрипты |
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
| **Перемещение ресурсов на базу** | `examples/organized/container/advanced/pull_items_from_docked_grid.py` — выгружает контейнеры, кокпиты, буры, рефини (input/output) на припаркованном гриде |
| **Production / Assembler** | `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md` |
| **Статус грида** (блоки, повреждения, контейнеры) | `docs/agent-skills/gaming/se-grid-status-report/SKILL.md` |

### Мониторинг

| Task | Doc |
|---|---|
| **Redis мониторинг, алерты** | `docs/agent-skills/gaming/game-server-automation/SKILL.md` |

### Управление устройствами

| Task | Doc |
|---|---|
| **Переименовать маяк** (контент, видный всем) | `examples/organized/beacon/set_beacon_to_grid_name.py` |
| **Переименовать устройство** | `examples/organized/grid/intermediate/grid_rename_device_example.py` |

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