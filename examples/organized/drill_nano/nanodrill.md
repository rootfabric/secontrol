# Инструкция по управлению Nanobot Drill & Fill через secontrol

## ⚠️ ВАЖНО: НЕ ЛЕТИ К РУДЕ

Nanobot Drill имеет зону действия **1000м**. Подлетать к руде **не нужно** и опасно — корабль врежется в астероид.

Условия для работы бура:
- Корабль стоит на астероиде (`surface=0` по `asteroid_index_example.py`)
- Руда в радиусе ≤1000м от бура
- `start_drill.py` сам наведёт зону захвата через `--target`

Если `surface > 0` — сначала прилететь на астероид через `space_navigator_v4.py --nearest-asteroid`.

## ⚠️ Фильтр руды НЕ РАБОТАЕТ на этом сервере

`set_ore_filters()` ставит фильтр (`nickel=True, stone=False`), но мод на этом сервере **игнорирует его для воксельного бурения**. Бур дробит **ближайший воксель** независимо от типа руды.

Вместе с Nickel будет добываться Stone и другие руды в зоне действия. Это особенность серверного плагина.

**Важно:** перед запуском добычи **выключи ассемблеры** (или production, потребляющий Nickel), иначе скрипт никогда не накопит target amount.

## Быстрый старт

```bash
# 0. ОСТАНОВИТЬ АССЕМБЛЕРЫ (иначе Nickel будет убывать быстрее чем добывается)
#    В терминале SE вручную выключить все Assembler / Basic Refinery

# 1. Проверить, на астероиде ли мы
python examples/organized/radar/basic/asteroid_index_example.py skynet-baza0
# Ищем: surface=0.0m — значит на астероиде

# 2. Найти координаты руды
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-baza0 --material Nickel --clusters --gps

# 3. Запустить бур с наведением на цель + мониторить до 10000
python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --target -50625.8 146646.9 -137740.2 --amount 10000
```

Что делает `mine_until.py`:
- Сбрасывает и настраивает фильтры (только указанная руда; фильтр не работает на этом сервере)
- Вычисляет `AreaOffset` — наводит зону захвата на цель (триггер рескана)
- Включает бур (ждёт 10s для авто-запуска)
- Мониторит контейнеры в цикле до target amount
- Выключает бур и HUD по готовности

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
# 0. Выключить ассемблеры (иначе Nickel будет убывать)
# 1. Проверить поверхность
asteroid_index_example.py --grid skynet-baza0
# surface=0? -> можно бурить. surface>0? -> лететь на астероид.

# 2. Найти руду
shared_map_deposits.py --grid skynet-baza0 --material Nickel --clusters
# Запомнить координаты ближайшего кластера

# 3. Запустить бур + мониторинг (одна команда, НЕ ЛЕТЕТЬ К РУДЕ)
mine_until.py --grid skynet-baza0 --ore Nickel --target <X> <Y> <Z> --amount 10000

# mine_until.py сам:
#   - наводит AreaOffset на цель
#   - включает бур (ждёт 10s авто-запуска)
#   - ждёт пока накопится target amount
#   - выключает бур и HUD по готовности
```

---

## Параметры start_drill.py

| Параметр | Описание |
|---|---|
| `--grid` | Имя грида (обязательно) |
| `--ore` | Тип руды (по умолч. Nickel) |
| `--target X Y Z` | Мировые координаты цели (обязательно для наведения области) |
| `--mode` | Режим: Collect / Drill / Fill (по умолч. Collect) |

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

### Ошибка 4. Проверять только sent

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

### Когда это нужно

Если руда находится на расстоянии >37.5м от бура, зона добычи (75×75×75м) не накроет её автоматически. Нужно выставить `AreaOffset` — сдвиг центра зоны относительно бура.

**Важно:** `AreaOffset` можно выставить до **±1000м** по каждой оси. То есть бур может доставать руду на расстоянии до **1 км** от корабля. Сообщение `Target outside drill area — offset may not reach` в выводе скрипта — это предупреждение, а не ошибка. Зона спокойно накроет цель, если офсет ≤ 1000м по каждой оси. Не нужно подлетать ближе.

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

#### 4. Запустить добычу (единая команда)

`mine_until.py` сам наводит AreaOffset, включает бур и мониторит:

```bash
python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --target <X> <Y> <Z> --amount 10000
```

`start_drill.py` — если нужен только запуск без мониторинга:

```bash
python examples/organized/drill_nano/start_drill.py --grid skynet-baza0 --ore Nickel --target <X> <Y> <Z>
```

Отдельно `set_nanodrill_area.py` — только для отладки/проверки наведения.

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

### Полный пример

```bash
# 0. Выключить ассемблеры в терминале SE
# 1. Проверить что мы на астероиде
python examples/organized/radar/basic/asteroid_index_example.py skynet-baza0
# Ищем nearest asteroid: surface=0.0m

# 2. Найти руду
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0

# 3. Запустить бур + добывать 5000 никеля (сам наведётся на цель)
python examples/organized/drill_nano/mine_until.py --grid skynet-baza0 --ore Nickel --target <X> <Y> <Z> --amount 5000
```
