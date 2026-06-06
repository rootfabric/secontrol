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

# Слить все ресурсы со всех припаркованных кораблей (запускается на базе)
python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo

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



## Каталог миссий missions

Готовые сценарии под ключ — параметризованные последовательности команд с правилами безопасности и обработкой ошибок. Если запрос пользователя совпадает с миссией — используй её, не собирай пайплайн вручную.

Каталог: `docs/agents-missions/`

| Миссия | Описание |
|---|---|
| [SE Ore Collection Mission](agents-missions/se-ore-collection-mission.md) | Добыча ресурсов. Добыть N руды (Uranium/Platinum/Iron/...) кораблём, вернуться на базу, пристыковаться, перегрузить cargo. По умолчанию: `ship=skynet-agent0`, `base=skynet-farpost0`, `ore=Uranium`, `amount=3000`. Включает правила остановки при ошибках и запрет на «выдуманные» GPS. |


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

**Рекомендуется использовать `space_navigator_v5.py`** — быстрый перелёт с сохранением защиты от столкновений и автоматическим boost в открытом космосе. Подробнее: `C:\secontrol\examples\space_flight\README_v5.md`

```bash
# Полёт к ближайшему астероиду (v5)
python examples/space_flight/space_navigator_v5.py --grid agent1 --nearest-asteroid --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80

# Полёт к GPS/координатам (v5) — например на базу
python examples/space_flight/space_navigator_v5.py --grid agent1 --target="GPS:Base:-137317:-111140:-82039:" --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80

# Полёт к конкретным координатам (v5)
python examples/space_flight/space_navigator_v5.py --grid agent1 --target="X,Y,Z" --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80
```

Аналогичные команды через v4 (медленнее, но подробнее логи):
```bash
python examples/space_flight/space_navigator_v4.py --grid agent1 --nearest-asteroid
python examples/space_flight/space_navigator_v4.py --grid agent1 --target="GPS:Name:X:Y:Z:" --arrival 50
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

## Производство и инвентарь

```bash
# Что может произвести грид (все чертежи конструкторов)
python examples/organized/assembler/basic/grid_production.py --grid farpost0

# С материалами для каждого чертежа
python examples/organized/assembler/basic/grid_production.py --grid farpost0 --full

# Поддерживать запас компонентов (по умолчанию из production_targets.json)
python examples/organized/assembler/basic/maintain_components.py --grid farpost0

# Посмотреть что будет без запуска
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --dry-run

# Свой файл целей
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --config my_targets.json

# Показать содержимое контейнеров грида
python examples/organized/container/basic/containers_show.py --grid farpost0

# Перегрузить ресурсы с корабля на базу (корабль должен быть пристыкован)
python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0

# Слить ВСЁ со ВСЕХ пристыкованных кораблей в контейнер базы (запускается на базе)
python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo
python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --dry-run
python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo --exclude-type ore

# Управление очередью конструктора: examples/organized/assembler/README.md
```

### Слить все ресурсы со всех пристыкованных кораблей (на стороне базы)

`pull_from_attached_ships.py` запускается **на базе**. Скрипт сам находит
все пристыкованные корабли по коннекторам базы со статусом `Connected` и
поочерёдно вытягивает из них содержимое (контейнеры, кокпиты, буры,
рефайнери, ассемблеры) в указанный контейнер базы. Если контейнер
заполнится — автоматически переключится на следующий свободный с тем же
тегом.

```bash
# Базовый запуск — слить всё в контейнер с тегом [cargo]
python examples/organized/container/advanced/pull_from_attached_ships.py \
    --base-grid skynet-farpost0 --target-tag cargo

# Указать конкретный контейнер по имени
python examples/organized/container/advanced/pull_from_attached_ships.py \
    --base-grid skynet-farpost0 --target-container "Main Storage"

# Только посмотреть, что есть на пристыкованных (без переноса)
python examples/organized/container/advanced/pull_from_attached_ships.py \
    --base-grid skynet-farpost0 --dry-run

# Не трогать руду (оставить на кораблях для переплавки)
python examples/organized/container/advanced/pull_from_attached_ships.py \
    --base-grid skynet-farpost0 --target-tag cargo --exclude-type ore

# Не переносить конкретный предмет (например, канистры с водородом)
python examples/organized/container/advanced/pull_from_attached_ships.py \
    --base-grid skynet-farpost0 --target-tag cargo --exclude-subtype Hydrogen
```

**Сравнение с `pull_items_from_docked_grid.py`:**

| Скрипт | Кто указан | Что делает |
|---|---|---|
| `pull_items_from_docked_grid.py` | конкретная пара source→target | тянет ресурсы с одного грида в другой |
| `pull_from_attached_ships.py` | только база | сам находит ВСЕХ, кто пристыкован к базе, и сливает |

### Файл целей production_targets.json

```json
{
  "SteelPlate": 100,
  "InteriorPlate": 50,
  "ConstructionComponent": 50,
  "SmallTube": 20,
  "LargeTube": 10,
  "MotorComponent": 20,
  "ComputerComponent": 20,
  "MetalGrid": 10,
  "Display": 5,
  "BulletproofGlass": 5
}
```


---

## Очистители (Refinery)

### Оценка приоритетов (безопасный режим)

Посмотреть план изменений, ничего не меняя:

```bash
python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --evaluate
```

### Применить изменения

```bash
python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --apply
```
### Учитывать очередь сборки (boost при дефиците слитков)

```bash
python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --apply --from-assembler-queue
```

### Автоматический цикл (повтор каждые 30 сек)

```bash
python examples/organized/refinery/refinery_priority_operator.py --grid farpost0 --apply --loop --interval 30
```

### Что делает скрипт

1. Находит все очистители на гриде
2. Собирает руду со всех контейнеров
3. Сортирует руду по приоритету из `refinery_priority_config.json`
4. Для каждого очистителя:
   - Переписывает очередь (какие blueprint-ы и в каком порядке)
   - Перекладывает руду во входной инвентарь (первая руда = первая плавится)
5. Если включён `--from-assembler-queue` — поднимает руду в приоритете, если нужен слиток для очереди сборки

### Порядок руд по умолчанию

```
Uranium → Platinum → Gold → Silver → Cobalt → Magnesium → Nickel → Silicon → Iron → Stone
```

Первая руда — самый высокий приоритет. Изменить можно в `examples/organized/refinery/refinery_priority_config.json`.

### Теги контейнеров-источников

Скрипт ищет контейнеры с тегами `[source]`, `[input]`, `[ore]` в имени. Если таких нет — берёт все контейнеры на гриде.

### Безопасность

- `--evaluate` ничего не меняет, только показывает план
- Скрипт не удаляет руду, только переносит между инвентарями
- Перед первым применением всегда сначала `--evaluate`

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
4. Стыковка:     dock.py [ship_id] [base_id] [approach_distance]
5. Выгрузка:     pull_items_from_docked_grid.py --source-grid [ship] --target-grid [base] --target-container "Cargo"
   (или, на стороне базы: pull_from_attached_ships.py --base-grid [base] --target-tag cargo)
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
- **Руды не конвертируются в другие!** Каждая руда перерабатывается ТОЛЬКО в слитки того же типа:
  - Gold ore → Gold ingot (только!)
  - Platinum ore → Platinum ingot (только!)
  - Silver ore → Silver ingot (только!)
  - Нельзя получить Gold из Platinum, Silver, Cobalt или любой другой руды.
  - Если Gold нет на карте — так и сообщи пользователю. НЕ выдумывай «конвертацию» или «переплавку» одной руды в другую.


---

