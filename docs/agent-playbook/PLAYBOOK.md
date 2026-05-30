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

### Проверка перед полётом: припаркован ли грид

**Перед любым полётом** проверь, припаркован ли грид. Если да — отстыкуйся перед движением.

```bash
# 1. Проверить статус стыковки
python examples/organized/parking/check_docking_status.py --grid agent1

# 2. Если припаркован — отстыковаться
python examples/organized/parking/smooth_undock.py [ship_id] [base_id] [distance]
```

> **Важно:** `space_navigator_v4.py` не сможет двигать припаркованный грид. Всегда проверяй статус стыковки перед полётом.

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

Автоматическая стыковка в 3 фазы:

| Фаза | Что делает |
|---|---|
| **1. Approach** | Летит к точке за 100м перед целевым коннектором |
| **2. Rotate** | Поворачивает корабль коннектором к цели |
| **3. Lock** | Подлёт по оси коннектора (fast → slow → creep) + автоблокировка |

```bash
# Стыковка корабля к базе
python examples/organized/parking/dock.py [ship_id] [target_id] [approach_distance]


# Примеры:
python examples/organized/parking/dock.py skynet-baza2 skynet-farpost0
python examples/organized/parking/dock.py 104571351454649539 84360909276756422 80

# Проверить статус стыковки
python examples/organized/parking/check_docking_status.py --grid agent1

# Расстыковка
python examples/organized/parking/smooth_undock.py [ship_id] [base_id] [distance]
```

---

## Добыча ресурсов

### Сканирование

```bash
# Универсальный скан (файл + Redis)
python examples/organized/radar/ore_scanner.py --grid agent1
```

### Проверка данных

```bash
# Полный отчёт по рудам в SharedMap
python examples/organized/radar/shared_map/shared_map_report.py --grid agent1

# Найти конкретную руду
python examples/organized/radar/shared_map/shared_map_deposits.py --grid agent1 --material Platinum --clusters --gps


### Найти неисследованный астероид

```bash
# Ближайший неисследованный астероид
python examples/organized/radar/find_unlooted_asteroid.py --grid agent1 --gps
```

### Бурение (Nanobot Drill)

```bash
# Бурение руды (безопасный режим)
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --grid agent1 --ore Platinum --amount 5000
```

```bash
# С увеличенным радиусом сканирования
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --grid agent1 --ore Uranium --amount 3000 --scan-radius 1000
```

```bash
# Добыть руду (Nanobot Drill) — автоматически скан + бур + сбор с игрой в параметры если не добывает сходу
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --grid skynet-agent0 --ore Ice --amount 500000 --scan-radius 1500 --area-size 75 --density-radius 20 --max-points 120 --startup-timeout 90 --no-progress-timeout 60 --working-point-min-seconds 180 --check-interval 0.5 --stone-safety-delta 20 --inventory-delta-threshold 10 --max-stone-per-ore-ratio 0.05
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
# Показать содержимое контейнеров грида
python examples/organized/container/basic/containers_show.py --grid farpost0

# В JSON-формате
python examples/organized/container/basic/containers_show.py --grid farpost0 --json

# Перегрузить ресурсы с корабля на базу (корабль должен быть пристыкован)
python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0
```


---

## Управление устройствами

```bash
# Переименовать маяк на одном корабле
python examples/organized/beacon/set_beacon_to_grid_name.py --grid agent1

# Переименовать ВСЕ маяки на ВСЕХ кораблях (под названия кораблей)
python examples/organized/beacon/set_all_beacons_to_grid_name.py

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
0. Проверить парковку: check_docking_status.py --grid agent1
   → если припаркован: smooth_undock.py [ship_id] [base_id] [distance]
1. Обзор:        space_survey.py --grid agent1 --unexplored --gps
2. Навигация:    space_navigator_v4.py --grid agent1 --target="X,Y,Z"
3. Скан:         ore_scanner.py --grid agent1
4. Синхронизация: shared_map_sync.py --grid agent1
```

### Пайплайн: Добыча руды

```
0. Проверить парковку: check_docking_status.py --grid agent1
   → если припаркован: smooth_undock.py [ship_id] [base_id] [distance]
1. Найти руду:   shared_map_deposits.py --grid agent1 --material Platinum --clusters
2. Навигация:    space_navigator_v4.py --grid agent1 --target="X,Y,Z"
3. Бурение:      mine_ore_robot_safe_live_move.py --grid agent1 --ore Platinum --amount 5000
```

### Пайплайн: После рестарта сервера

```
1. Очистить:     clear_ore_data.py --apply
2. Скан:         ore_scanner.py --grid agent1
3. Синхронизация: shared_map_sync.py --grid agent1 --source all
```

---

## Важно

- **Перед полётом** — проверяй статус стыковки (`check_docking_status.py`). Припаркованный грид не летит.
- **Все пути** — от корня проекта `C:\secontrol\`
- **Временные файлы** — только в `tmp/`
- **Скрипт по умолчанию для скана руд** — `ore_scanner.py` (файл + Redis)
- **Скрипт по умолчанию для обзора** — `space_survey.py`


---

## Скиллы

`docs/agent-skills/README.md`

---