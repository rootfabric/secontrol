# Agent Playbook — Готовые команды для работы в игре

Агент работает в игре? Начни здесь. Все команды — копировать и запускать. Никакого кодирования без крайней необходимости нестандартных задач.



### Быстрые команды

```bash
# Проверить состояние корабля (все гриды)
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py

# Проверить конкретный грид (например, agent0)
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent0

# Проверить готовность к полёту (батареи, водород)
python examples/organized/diagnostics/check_flight_ready.py agent0

# Обзор пространства (астероиды в радиусе 50км)
python examples/organized/radar/space_survey.py --grid agent0

# Сканировать руды
python examples/organized/radar/ore_scanner.py --grid agent0

# Синхронизировать данные в Redis
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent0

# Лететь к ближайшему астероиду
python examples/space_flight/space_navigator_v4.py --grid agent0 --nearest-asteroid
```

---

## Быстрый старт

```bash
# 1. Что вокруг меня?
python examples/organized/radar/space_survey.py --grid agent1

# 2. Какие руды уже известны?
python examples/organized/radar/shared_map/shared_map_report.py --grid agent1

# 3. Лететь к ближайшему неисследованному астероиду
python examples/space_flight/space_navigator_v4.py --grid agent1 --nearest-asteroid

# 4. Отсканировать руды
python examples/organized/radar/ore_scanner.py --grid agent1

# 5. Синхронизировать данные в Redis
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1
```

---

## Как узнать имя грида

Параметр `--grid` поддерживает **неполное имя** (регистронезависимый поиск). Если не знаете точное имя:

```bash
# Список всех гридов
python -c "from secontrol.common import get_all_grids; [print(f'{name} (ID: {gid})') for gid, name in get_all_grids()]"

# Или через готовый скрипт
python examples/organized/grid/basic/list_grids.py
```

После этого можно использовать любую уникальную часть имени:
```bash
python examples/organized/radar/space_survey.py --grid Mining
```

Если совпадений несколько — скрипт покажет все варианты и попросит уточнить.

---

## Навигация

### Обзор пространства

```bash
# Сканировать гриды и игроков вокруг (радар, без вокселей)
python examples/organized/radar/basic/scan_contacts.py --grid agent1

# Все астероиды в радиусе 20км + какие разведаны
python examples/organized/radar/space_survey.py --grid agent1

# Увеличить радиус до 50км
python examples/organized/radar/space_survey.py --grid agent1 --radius 50000

# Только неразведанные
python examples/organized/radar/space_survey.py --grid agent1 --unexplored

# Где конкретная руда?
python examples/organized/radar/space_survey.py --grid agent1 --ore Platinum

# С GPS-маркерами для копирования в SE
python examples/organized/radar/space_survey.py --grid agent1 --gps

# JSON для программной обработки
python examples/organized/radar/space_survey.py --grid agent1 --json
```

### Полёты

```bash
# Полёт к ближайшему астероиду (автоматический A* pathfinding)
python examples/space_flight/space_navigator_v4.py --grid agent1 --nearest-asteroid

# Полёт к конкретным координатам
python examples/space_flight/space_navigator_v4.py --grid agent1 --target="X,Y,Z" --arrival 50

# Полёт к GPS-точке
python examples/space_flight/space_navigator_v4.py --grid agent1 --target="GPS:Name:X:Y:Z:" --arrival 50

# Ограничить скорость (например приближение к астероиду)
python examples/space_flight/space_navigator_v4.py --grid agent1 --target="X,Y,Z" --max-speed 30
```

### Парковка и стыковка

```bash
# Проверить статус стыковки
python examples/organized/parking/check_docking_status.py --grid agent1

# Документация по стыковке
# docs/agent-skills/gaming/secontrol-space-engineers/references/space-docking.md
```

---

## Добыча ресурсов

### Сканирование

```bash
# Универсальный скан (файл + Redis)
python examples/organized/radar/ore_scanner.py --grid agent1

# Скан с меньшим радиусом
python examples/organized/radar/ore_scanner.py --grid agent1 --radius 500

# Только файл, без Redis
python examples/organized/radar/ore_scanner.py --grid agent1 --no-redis

# Поиск руды в последнем скане
python examples/organized/radar/ore_scanner.py --find Platinum
```

### Проверка данных

```bash
# Полный отчёт по рудам в SharedMap
python examples/organized/radar/shared_map/shared_map_report.py --grid agent1

# Найти конкретную руду
python examples/organized/radar/shared_map/shared_map_deposits.py --grid agent1 --material Platinum --clusters --gps

# Синхронизация локальных файлов в Redis
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1
```

### Найти неисследованный астероид

```bash
# Ближайший неисследованный астероид
python examples/organized/radar/find_unlooted_asteroid.py --grid agent1 --gps
```

### Бурение (Nanobot Drill)

```bash
# Документация: examples/organized/drill_nano/nanodrill_agent.md
# Быстрый старт: docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-quickstart.md
```

---

## Строительство

```bash
# Строительство блоков (проектор + BARS)
# docs/agent-skills/gaming/se-projection-builder.md

# Статус грида (блоки, повреждения, контейнеры)
# docs/agent-skills/gaming/se-grid-status-report/SKILL.md
```

---

## Производство и инвентарь

```bash
# Перемещение ресурсов на базу
python examples/organized/container/advanced/pull_items_from_docked_grid.py --grid agent1
```

---

## Управление устройствами

```bash
# Переименовать маяк
python examples/organized/beacon/set_beacon_to_grid_name.py --grid agent1

# Переименовать устройство
python examples/organized/grid/intermediate/grid_rename_device_example.py --grid agent1
```

---

## Мониторинг

```bash
# Redis мониторинг, алерты
# docs/agent-skills/gaming/game-server-automation/SKILL.md
```

---

## Стандартные пайплайны

### Пайплайн: Разведка нового астероида

```
1. Обзор:        space_survey.py --grid agent1 --unexplored --gps
2. Навигация:    space_navigator_v4.py --grid agent1 --target="X,Y,Z"
3. Скан:         ore_scanner.py --grid agent1
4. Синхронизация: shared_map_sync.py --grid agent1
```

### Пайплайн: Добыча руды

```
1. Найти руду:   shared_map_deposits.py --grid agent1 --material Platinum --clusters
2. Навигация:    space_navigator_v4.py --grid agent1 --target="X,Y,Z"
3. Бурение:      nanodrill scripts (docs/organized/drill_nano/nanodrill_agent.md)
```

### Пайплайн: После рестарта сервера

```
1. Очистить:     clear_ore_data.py --apply
2. Скан:         ore_scanner.py --grid agent1
3. Синхронизация: shared_map_sync.py --grid agent1 --source all
```

---

## Важно

- **Все пути** — от корня проекта `C:\secontrol\`
- **Временные файлы** — только в `tmp/`
- **Скрипт по умолчанию для скана руд** — `ore_scanner.py` (файл + Redis)
- **Скрипт по умолчанию для обзора** — `space_survey.py`


---

## Скиллы

`docs/agent-skills/README.md`

---