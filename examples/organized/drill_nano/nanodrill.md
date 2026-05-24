# Инструкция по управлению Nanobot Drill & Fill через secontrol

## ⚠️ ВАЖНО: НЕ ЛЕТИ К РУДЕ

Nanobot Drill имеет зону действия **1000м**. Подлетать к руде **не нужно** и опасно — корабль врежется в астероид.

Условия для работы бура:
- Корабль стоит на астероиде (`surface=0` по `asteroid_index_example.py`)
- Руда в радиусе ≤1000м от бура
- `mine_until.py` сам наведёт зону через `--target`

Если `surface > 0` — сначала прилететь на астероид через `space_navigator_v4.py`.

## 🔴 КРИТИЧНО: WorkMode сбрасывает AreaOffset

**WorkMode (Collect/Drill/Fill) сбрасывает AreaOffset на 0.**

Поэтому `set_nanodrill_area.py` + ручная настройка бура **не работают** —
если после `set_nanodrill_area.py` вызвать WorkMode, офсеты пропадут.

**Правильный порядок:**
```
WorkMode → AreaOffset  (именно в такой последовательности!)
```

`mine_until.py` делает это правильно. Используй только его.

## Фильтр руды на этом сервере

`set_ore_filters()` ставит фильтр, но мод на этом сервере может
**игнорировать его для воксельного бурения**. Вместе с Nickel
может добываться Stone. Это особенность серверного плагина.

## Быстрый старт

```bash
# 0. Проверить известные месторождения
python examples/organized/radar/shared_map/shared_map_deposits.py \
    --grid skynet-baza0 --material Nickel --clusters --gps

# Если руда не найдена — сканировать:
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500
# Если scanner вернул 0 руды — см. Шаг 1 ниже (scan_and_wait)

# 1. Долететь до руды
python examples/space_flight/space_navigator_v4.py \
    --grid skynet-baza0 \
    --target="-50626.7,146646.4,-137736.2" \
    --arrival 50

# 2. Добыть 10000 никеля (одна команда — всё включено)
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --target -50626.734 146646.403 -137736.175 \
    --amount 10000 \
    --check-interval 5
```

Что делает `mine_until.py`:
- Сбрасывает и настраивает фильтры (Collect, Ore, Nickel)
- **Ставит WorkMode, потом AreaOffset** (правильный порядок!)
- Включает бур (ждёт ~10s для авто-запуска)
- Мониторит контейнеры в цикле до target amount
- Показывает rate (ед/сек) и ETA
- Выключает бур и HUD по готовности

### ⚠️ Если scanner вернул 0 руды

`ore_deposit_scanner.py` может показать 0 ore cells (stale data).
Форсировать свежий скан через `OreDetectorDevice.scan_and_wait()`:

```bash
python -c "
from secontrol import Grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
grid = Grid.from_name('skynet-baza0')
det = grid.find_devices_by_type(OreDetectorDevice)[0]
det.scan_and_wait(radius=500, ore_only=True, timeout=30)
cells = det.ore_cells()
print(f'Найдено ячеек: {len(cells)}')
ores = set(c['ore'] for c in cells)
for o in sorted(ores):
    print(f'  {o}: {sum(1 for c in cells if c[\"ore\"]==o)}')
"
```

### Мониторинг добычи (контейнеры)

Руда поступает в грузовые контейнеры через конвейер. Проверять надо их:

```python
import time

from secontrol import Grid

grid = Grid.from_name("skynet-baza0")

# Получить всю руду на гриде
items = grid.get_all_grid_items()
nickel_total = 0
for item in items:
    subtype = str(item.get("item_subtype", ""))
    if "Nickel" in subtype:
        nickel_total += item.get("amount", 0)
        print(f"{item.get('display_name')}: {item.get('amount'):.1f}")

print(f"Total Nickel Ore: {nickel_total:.1f}")
```

Или через ContainerDevice:

```python
from secontrol import Grid
from secontrol.devices.container_device import ContainerDevice

grid = Grid.from_name("skynet-baza0")
for c in grid.find_devices_by_type(ContainerDevice):
    c.update()
    for inv in c.inventories():
        for item in (inv.items or []):
            subtype = str(item.subtype or "")
            if "Nickel" in subtype:
                print(f"{c.name}: {item.display_name}: {item.amount:.1f}")
```

### Остановка бура

```bash
python examples/organized/drill_nano/stop_drill.py --grid skynet-baza0
```

Отключает питание, ShowArea и ShowOnHUD.

---

## Полный пайплайн для агента

```bash
# 0. Проверить известные руды
shared_map_deposits.py --grid skynet-baza0 --material Nickel --clusters --gps
# Если руда есть → шаг 2 (полёт), скан не нужен

# 1. Если руды нет — сканировать
ore_deposit_scanner.py --grid skynet-baza0 --radius 500
# Если scanner вернул 0 ore cells:
python -c "
from secontrol import Grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
grid = Grid.from_name('skynet-baza0')
det = grid.find_devices_by_type(OreDetectorDevice)[0]
det.scan_and_wait(radius=500, ore_only=True, timeout=30)
cells = det.ore_cells()
for c in cells:
    if c['ore'] == 'Nickel':
        print(f'Nickel: {c[\"position\"]}')
"

# 2. Долететь до руды
space_navigator_v4.py --grid skynet-baza0 --target="X,Y,Z" --arrival 50

# 3. Добыть (одна команда — mine_until сам всё делает)
mine_until.py --grid skynet-baza0 --ore Nickel --target X Y Z --amount 10000 --check-interval 5
```

**⚠️ НЕ ИСПОЛЬЗОВАТЬ `set_nanodrill_area.py` перед `mine_until.py`!**
WorkMode внутри `mine_until.py` сбросит AreaOffset, который поставил
`set_nanodrill_area.py`. `mine_until.py` сам вычисляет AreaOffset
в правильном порядке (после WorkMode).

---

## Параметры mine_until.py

| Параметр | Описание |
|---|---|
| `--grid` | Имя грида (обязательно) |
| `--ore` | Тип руды (по умолч. Nickel) |
| `--target X Y Z` | Мировые координаты цели (обязательно) |
| `--amount` | Сколько добыть (delta от текущего, обязательно) |
| `--mode` | Режим: Collect / Drill / Fill (по умолч. Collect) |
| `--check-interval` | Как часто проверять контейнеры (сек, по умолч. 5) |

---

## Ожидаемый вывод после настройки

```text
work mode: Collect
priority: [
  '1137917536;False',
  '1579040667;False',
  '2112235764;False',
  '-723128632;True',
  '-122448462;False',
  '-2115209756;False',
  '2104309205;False',
  '1033257407;False',
  '-496794321;False',
  '-510410391;False',
  '1880922462;False'
]
known ores: {
  'stone': False,
  'ice': False,
  'iron': False,
  'nickel': True,
  'silicon': False,
  'cobalt': False,
  'magnesium': False,
  'silver': False,
  'gold': False,
  'platinum': False,
  'uranium': False
}
```

Главная проверка:
- Только выбранная руда `True`, остальные `False`
- `work mode: Collect` (или Drill)
- `OnOff: True`
- `ShowArea: True`

---

## Что означают основные параметры

### WorkMode

```text
0 = Fill
1 = Collect
2 = Drill
```

Для выборочной добычи нужен именно:

```python
drill.set_work_mode("Collect")
```

Не использовать:

```python
drill.set_work_mode("Drill")
drill.start_drilling()
```

`Drill` может выгрызать всё внутри области и захватывать лишний камень.

### OreFilter

Материальный фильтр вокселей.

```python
drill.set_ore_filters(["Ice"], work_mode="Collect")
drill.set_ore_filters(["Uranium"], work_mode="Collect")
drill.set_ore_filters(["Ice", "Uranium", "Iron"], work_mode="Collect")
```

**На сервере skynet-baza0 OreFilter не работает для воксельного бурения.** Фильтр выставляется (в телеметрии `nickel=True, stone=False`), но мод его игнорирует и бурит ближайший воксель.

### CollectFilter

Фильтр типов подбираемых объектов.

Для льда использовать:

```python
drill.set_collect_filter(["Ore"])
```

Не использовать для обычной работы:

```python
drill.set_collect_filter(["all"])
```

`["all"]` разрешает подбирать floating objects камня, поэтому камень может попадать в инвентарь.

---

## Результат тестового запуска (2026-05-24)

| Параметр | Значение |
|---|---|
| Корабль | skynet-baza0 |
| Руда | Nickel |
| Цель | -50626.734, 146646.403, -137736.175 |
| Расстояние от бура | 163м |
| Офсеты | FB=+161.3, UD=+21.8, LR=-14.3 |
| Целей найдено | 45 всего, 3 Nickel |
| Добыто | 10 279 ед. (10.28 тонн) |
| Время | 3 мин 50 сек |
| Скорость | ~45 ед/с |
| Команд | 1 (mine_until.py) |

**Точная последовательность команд:**
```bash
# 1. Проверка shared map — найдено 2 кластера никеля
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-baza0 --material Nickel --clusters --gps

# 2. Скан — вернул 0 (stale data)
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500

# 3. Форсированный скан — 31 ячейка никеля
python -c "..."  # scan_and_wait()

# 4. Полёт к руде
python examples/space_flight/space_navigator_v4.py --grid skynet-baza0 --target="-50625.8,146646.9,-137740.2" --arrival 50

# 5. Добыча (одна команда — всё остальное автоматически)
python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --target -50626.734 146646.403 -137736.175 --amount 10000 --check-interval 5
```

## Типовые ошибки

### Ошибка 1. Оставили ScriptControlled включенным

Плохо:

```python
drill.set_script_controlled(True)
drill.turn_on()
```

Правильно:

```python
drill.set_script_controlled(True)
drill.set_ore_filters(["Ice"], work_mode="Collect")
drill.set_script_controlled(False)
drill.turn_on()
```

### Ошибка 2. Вызвали start_drilling

Плохо:

```python
drill.start_drilling()
```

Правильно:

```python
drill.set_work_mode("Collect")
drill.turn_on()
```

### Ошибка 3. Поставили CollectFilter all

Плохо:

```python
drill.set_collect_filter(["all"])
```

Правильно:

```python
drill.set_collect_filter(["Ore"])
```

### Ошибка 4. WorkMode до AreaOffset

Плохо:
```python
drill.set_raw_property("Drill.AreaOffsetFrontBack", 161.3)   # ← offset ПЕРЕД WorkMode
drill.set_work_mode("Collect")                                 # ← WorkMode СБРАСЫВАЕТ offset
drill.turn_on()
# Результат: targets=0, AreaOffset сброшен в 0
```

Правильно:
```python
drill.set_work_mode("Collect")                                 # ← WorkMode ПЕРВЫМ
drill.set_raw_property("Drill.AreaOffsetFrontBack", 161.3)    # ← offset ПОСЛЕ WorkMode
drill.turn_on()
```

Или просто используй `mine_until.py`, который делает это правильно.

### Ошибка 6. Полагаться на scanner при 0 руды

`ore_deposit_scanner.py` использует `RadarController`, который читает из
общей сканированной области. Если скан уже был сделан навигатором без
`ore_only=True`, рудные ячейки могут отсутствовать.

**Решение:** использовать прямой вызов `OreDetectorDevice.scan_and_wait()`,
который форсирует свежий скан с `ore_only=True`.

### Ошибка 7. Проверять только sent

`sent: 18` означает только то, что команды были отправлены в Redis/подписчикам. Это не гарантирует, что мод реально применил фильтр.

Проверять надо:

```python
print("work mode:", drill.get_work_mode())
print("priority:", drill.debug_get_priority_list_raw())
print("known ores:", drill.debug_get_enabled_known_ores())
print("status:", drill.debug_status())
```

---

## Требования к C#-плагину

Чтобы фильтры работали, серверный плагин должен:

1. При вызове `Drill.SetDrillEnabled` передавать не позицию `i`, а `oreHash` из строки `DrillPriorityList`, если он есть.
2. Применять фильтр не только к `Drill.SetDrillEnabled`, но и к `Drill.SetCollectEnabled`, если доступен `Drill.CollectPriorityList`.
3. Обрабатывать команду `OreFilter`.
4. Обрабатывать команду `CollectFilter`.
5. Возвращать в телеметрию хотя бы `Drill.DrillPriorityList`.

Правильный итог после `OreFilter(["Ice"])`:

```text
Stone = False
Ice = True
Iron = False
Nickel = False
Silicon = False
Cobalt = False
Magnesium = False
Silver = False
Gold = False
Platinum = False
Uranium = False
```

---

## Практическое правило

Для добычи только льда:

```python
drill.set_script_controlled(True)
drill.set_collect_filter(["Ore"])
drill.set_ore_filters(["Ice"], work_mode="Collect")
drill.set_work_mode("Collect")
drill.set_script_controlled(False)
drill.set_work_mode("Collect")
drill.turn_on()
```

Не использовать:

```python
drill.set_collect_filter(["all"])
drill.start_drilling()
drill.set_work_mode("Drill")
```

---

## Выставление зоны добычи на цель (AreaOffset)

### 🔴 КРИТИЧНО: WorkMode сбрасывает AreaOffset

**WorkMode (Collect / Drill / Fill) сбрасывает AreaOffset на 0.**

Поэтому ВСЕГДА ставь AreaOffset **после** WorkMode. Правильный порядок:
```
1. Выключить бур
2. Настроить фильтры (ScriptControlled=true → CollectFilter → OreFilter)
3. Установить WorkMode (Collect/Drill/Fill)  ← сбрасывает AreaOffset
4. ScriptControlled=false
5. WorkMode ещё раз (для надёжности)
6. **AreaOffset**  ← ТОЛЬКО ТЕПЕРЬ!
7. Включить бур
```

**`mine_until.py` делает это правильно.**
**`set_nanodrill_area.py` НЕ делает этого** — он только ставит AreaOffset.

Если запустить `set_nanodrill_area.py`, а потом вызвать `WorkMode`
(через mine_until.py или напрямую) — AreaOffset сбросится в 0.

### Когда это нужно

Если руда находится на расстоянии >37.5м от бура, зона добычи (75×75×75м) не накроет её автоматически. Нужно выставить `AreaOffset` — сдвиг центра зоны относительно бура.

**Важно:** `AreaOffset` можно выставить до **±1000м** по каждой оси. То есть бур может доставать руду на расстоянии до **1 км** от корабля. Не нужно подлетать ближе.

### Процесс

#### 1. Получить координаты руды

Через `ore_deposit_scanner.py`:

```bash
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 | grep -i nickel
```

Результат — мировые координаты цели (X Y Z).

#### 2. Запустить `set_nanodrill_area.py` с --dry-run

```bash
python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target <X> <Y> <Z> --dry-run
```

Скрипт выведет:
- Позицию корабля и бура
- Расстояние до цели
- Предлагаемые офсеты в drill-локальных координатах (FrontBack, UpDown, LeftRight)

Если цель дальше ~75м от бура — скрипт предупредит. Нужно подлететь ближе.

#### 3. Проверить DRILL_AXIS_MAP

В `set_nanodrill_area.py` есть константа `DRILL_AXIS_MAP` — она определяет, как оси грида (Right=X, Up=Y, Forward=Z) транслируются в оси бура (LeftRight, UpDown, FrontBack).

Для **skynet-baza0** (Nanobot Drill развёрнут):
```python
DRILL_AXIS_MAP = {
    "LeftRight": (0, 1),  # grid X → drill LeftRight
    "UpDown":    (2, 1),  # grid Z → drill UpDown   (drill_up = grid_forward)
    "FrontBack": (1, 1),  # grid Y → drill FrontBack (drill_forward = grid_up)
}
```

Если бур установлен без разворота (совпадает с осями грида):
```python
DRILL_AXIS_MAP = {
    "LeftRight": (0, 1),  # grid X → drill LeftRight
    "UpDown":    (1, 1),  # grid Y → drill UpDown
    "FrontBack": (2, 1),  # grid Z → drill FrontBack
}
```

#### 4. Запустить добычу (единственная команда)

**Использовать только `mine_until.py`.** Он сам наводит AreaOffset
(в правильном порядке — после WorkMode), включает бур и мониторит:

```bash
python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --target <X> <Y> <Z> --amount 10000
```

**Не использовать `set_nanodrill_area.py` отдельно.** Если запустить
`set_nanodrill_area.py`, а потом `mine_until.py` — WorkMode внутри
`mine_until.py` сбросит AreaOffset, поставленный `set_nanodrill_area.py`.

`set_nanodrill_area.py` можно использовать только для отладки/проверки
наведения (с `--dry-run`), но не как часть пайплайна добычи.

### Определение DRILL_AXIS_MAP для нового грида

Если зона визуально уходит не в ту сторону — маппинг осей неверен. Вот как это определить:

1. Поставьте небольшой офсет по одной оси (например, `UpDown = 10`), остальные оставьте 0
2. Посмотрите, в какую мировую сторону сдвинулась зона (визуально на HUD)
3. Определите, какая ось грида соответствует этой оси бура
4. Повторите для каждой оси

Примеры симптомов:

| Как установили | Куда зона ушла | Ошибка в маппинге |
|---|---|---|
| UpDown = +10 | Назад (-Forward) | drill_up = grid_forward, а не grid_up |
| UpDown = +10 | Вниз (-Up) | drill_up = -grid_up, а не grid_up |
| FrontBack = +10 | Вверх (+Up) | drill_forward = grid_up, а не grid_forward |

### Полный пример (верифицирован 2026-05-24)

```bash
# 0. Проверить известные руды
python examples/organized/radar/shared_map/shared_map_deposits.py \
    --grid skynet-baza0 --material Nickel --clusters --gps
# Вывод: 2 кластера, ближайший 214м

# 1. Сканировать (на всякий случай)
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500

# 2. Долететь до кластера
python examples/space_flight/space_navigator_v4.py \
    --grid skynet-baza0 \
    --target="-50625.8,146646.9,-137740.2" \
    --arrival 50

# Навигатор долетел до (-50618, 146650, -137569), nearest voxel 154м

# 3. Форсировать скан (scanner вернул 0):
python -c "
from secontrol import Grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
import time
grid = Grid.from_name('skynet-baza0')
det = grid.find_devices_by_type(OreDetectorDevice)[0]
det.scan_and_wait(radius=500, ore_only=True, timeout=30)
time.sleep(1)
cells = det.ore_cells()
print(f'Найдено ячеек: {len(cells)}')
nickel = [c for c in cells if c['ore'] == 'Nickel']
print(f'Nickel: {len(nickel)}')
for c in nickel[:3]:
    print(f'  {c[\"position\"]} content={c[\"content\"]}')
"
# Вывод: 31 Nickel cell

# 4. Добыть 10 000 никеля (одна команда!)
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --target -50626.734 146646.403 -137736.175 \
    --amount 10000 \
    --check-interval 5

# Результат: 10 279 ед. за 3мин 50сек, rate ~45 ед/с
```
