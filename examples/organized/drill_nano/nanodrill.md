# Инструкция по управлению Nanobot Drill & Fill через secontrol

## Цель

Настроить Nanobot Drill & Fill так, чтобы он добывал выбранный материал, например `Ice`, и не забирал лишний камень в инвентарь.

Проверенный рабочий сценарий для льда:

- `WorkMode = Collect`
- `OreFilter = Ice`
- `CollectFilter = Ore`
- `ScriptControlled` включается только временно на время применения фильтров
- после применения фильтров `ScriptControlled` обязательно выключается
- `Drill_On` не вызывать

Важно: в текущем поведении мода камень может физически ломаться/удаляться, если он мешает области работы, но при правильном `CollectFilter` он не должен подбираться как floating object.

---

## Правильная последовательность настройки

1. Выключить блок.
2. Включить `ScriptControlled`.
3. Применить фильтр типов подбора: `CollectFilter = Ore`.
4. Применить фильтр материалов: `OreFilter = Ice`, `WorkMode = Collect`.
5. Ещё раз явно поставить `WorkMode = Collect`.
6. Выключить `ScriptControlled`.
7. Ещё раз явно поставить `WorkMode = Collect`.
8. Включить блок.
9. Не вызывать `start_drilling()` / `Drill_On`.

---

## Рабочий пример для добычи только льда

```python
from __future__ import annotations

import time

from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice


GRID_NAME = "taburet2"


def main() -> None:
    grid = Grid.from_name(GRID_NAME)
    drills = grid.find_devices_by_type(NanobotDrillSystemDevice)

    if not drills:
        raise RuntimeError("Nanobot Drill System devices were not found")

    for index, item in enumerate(drills):
        print(
            f"{index}: "
            f"name={item.name!r}, "
            f"device_id={item.device_id}, "
            f"telemetry_key={item.telemetry_key}"
        )

    drill = drills[0]

    sent = 0

    try:
        sent += drill.turn_off()
        time.sleep(0.3)
    except Exception as exc:
        print("turn_off failed:", exc)

    sent += drill.set_script_controlled(True)
    time.sleep(0.2)

    # Не использовать ["all"], иначе бур сможет подбирать floating objects камня.
    sent += drill.set_collect_filter(["Ore"])

    # Материальный фильтр: только Ice.
    sent += drill.set_ore_filters(["Ice"], work_mode="Collect")

    sent += drill.set_work_mode("Collect")
    time.sleep(0.2)

    sent += drill.set_script_controlled(False)

    try:
        sent += drill.set_script_controlled_action(False)
    except Exception as exc:
        print("ScriptControlled_Off action failed:", exc)

    time.sleep(0.2)

    sent += drill.set_work_mode("Collect")
    sent += drill.turn_on()

    print("sent:", sent)

    time.sleep(1.0)

    print("work mode:", drill.get_work_mode())
    print("priority:", drill.debug_get_priority_list_raw())
    print("known ores:", drill.debug_get_enabled_known_ores())
    print("status:", drill.debug_status())


if __name__ == "__main__":
    main()
```

---

## Ожидаемый вывод после настройки

```text
work mode: Collect
priority: [
  '1137917536;False',
  '1579040667;True',
  '2112235764;False',
  '-723128632;False',
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
  'ice': True,
  'iron': False,
  'nickel': False,
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

```text
'1137917536;False'  -> Stone выключен
'1579040667;True'   -> Ice включен
work mode: Collect
```

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

#### 4. Установить офсеты

Без `--dry-run` скрипт отправит команды на сервер:

```bash
python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target <X> <Y> <Z>
```

Можно добавить `--reset-area`, чтобы сначала обнулить все офсеты.

#### 5. Проверить

```bash
python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target <X> <Y> <Z> --dry-run
```

Убедиться, что `Drill to target distance` уменьшилось (теперь это расстояние от центра зоны до цели, а не от бура до цели).

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
# Получить координаты никеля
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0

# Подлететь ближе (если нужно)
# ...

# Прицелить зону бура на никель
python examples/organized/drill_nano/set_nanodrill_area.py --grid skynet-baza0 --target -50626.3 146646.9 -137739.8

# Настроить фильтр на никель и включить
python -c "
from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

grid = Grid.from_name('skynet-baza0')
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]
drill.set_script_controlled(True)
drill.set_collect_filter(['Ore'])
drill.set_ore_filters(['Nickel'], work_mode='Collect')
drill.set_work_mode('Collect')
drill.set_script_controlled(False)
drill.turn_on()
"
```
