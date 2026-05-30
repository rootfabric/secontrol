# Agent Skills — Space Engineers / secontrol

Hermes agent skills для работы с Space Engineers через secontrol.
Все скиллы находятся в `/workspace/docs/agent-skills/gaming/`.

## Быстрый доступ

| Скилл | Описание | Когда использовать |
|---|---|---|
| [secontrol-space-engineers](gaming/secontrol-space-engineers/SKILL.md) | **Основной** — полный SDK: гриды, устройства, инвентарь, блюпринты, производство, навигация | Любая работа с SE через secontrol |
| [se-grid-status-report](gaming/se-grid-status-report/SKILL.md) | Статус-репорт: блоки, повреждения, устройства, содержимое контейнеров | «Покажи все корабли», «что в контейнерах», «есть ли повреждения» |
| [se-projection-builder](gaming/se-projection-builder/SKILL.md) | Проекционный цикл: загрузка XML → варка → проверка → BARS покраска | Строительство по блюпринтам, покраска блоков |
| [se-asteroid-approach](gaming/se-asteroid-approach/SKILL.md) | Полёт к астероиду: скан → навигация → подход | Добыча руды, исследование астероидов |
| [game-server-automation](gaming/game-server-automation/SKILL.md) | Redis pub/sub, keyspace notifications, мониторинг | Мониторинг событий, алерты |

## Скрипты

| Скрипт | Описание |
|---|---|
| [scripts/grid_report.py](se-grid-status-report/scripts/grid_report.py) | Генерация полного отчёта по всем гридам (или конкретному) |

## Структура

```
docs/agent-skills/gaming/
├── secontrol-space-engineers/      # Основной SDK скилл
│   ├── SKILL.md
│   └── references/
│       ├── asteroid-flight-pattern.md
│       ├── asteroid-scanning.md
│       ├── blueprint-editing.md
│       ├── construction-planning.md
│       ├── dronebase-telemetry.md
│       ├── hermes-kanban-subprocess.md
│       ├── inventory-patterns.md
│       ├── manual-flight-controller.md
│       ├── monitoring-pipeline.md
│       ├── nanobot-drill-debugging.md
│       ├── nanobot-drill-mining-workflow.md
│       ├── navigation-and-flight.md
│       ├── projection-alignment.md
│       ├── se-block-types.md
│       ├── se-monitoring-pipeline.md
│       ├── space-docking.md
│       └── voxel-distance-diagnostics.md
├── se-grid-status-report/          # Статус-репорт
│   ├── SKILL.md
│   └── scripts/
│       └── grid_report.py
├── se-projection-builder/          # Проекционный цикл
│   ├── SKILL.md
│   └── references/
│       ├── blocks-vs-devices.md
│       ├── color-conversion.md
│       ├── grind-color-investigation.md
│       └── grind-mode-detail.md
├── se-asteroid-approach/           # Полёт к астероиду
│   └── SKILL.md
└── game-server-automation/         # Redis мониторинг
    ├── SKILL.md
    └── references/
        └── secontrol-grids.md
```

## Как использовать

### Из Hermes CLI
```bash
# Загрузить скилл
hermes skill view secontrol-space-engineers

# Или через Python
from hermes_tools import skill_view
skill_view('secontrol-space-engineers')
```

### Из кода (Python)
```python
# Базовый паттерн
from secontrol.common import get_all_grids, prepare_grid

# Список всех гридов
grids = get_all_grids()

# Подключиться к конкретному гриду
grid = prepare_grid('skynet-baza0')  # имя или ID

# Найти устройства
for did, dev in grid.devices.items():
    print(f'{dev.device_type}: {did}')
```

## Pitfalls (из памяти)

1. `prepare_grid()` — **только строковый аргумент**. `prepare_grid(123456)` (int) = неправильный грид.
2. `time.sleep(0.8)` между подключениями к гридам — иначе Redis таймауты.
3. Контейнеры: `get_inventory()` для ContainerDevice, телеметрия для Refinery/Assembler.
4. `block.state` может быть `None` — всегда `or {}`.
5. Броня всегда `functional=False` — это нормально, не баг.
6. Blueprint XML может раздуваться — стриппировать до минимального перед загрузкой.
7. `set_offset`/`set_rotation` — дельта, не абсолют. Встраивать в XML перед загрузкой.
8. Трастеры требуют `hasPilot` или `RemoteControl`.
9. Nanobot Drill в космосе: `ScriptControlled=False`, `start_drilling()` обязателен.
