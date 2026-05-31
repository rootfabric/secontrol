# Инструкция агенту: Nanobot Drill Automation Fix

Эта инструкция заменяет старые заметки по `mine_until.py`/`start_drill.py`. Она рассчитана на мод **Outenemy Nanobot Drill System - Automation Fixes** и Python-библиотеку `secontrol`.

## 0. Правило обработки руд (НЕ ВЫДУМЫВАТЬ)

Каждая руда перерабатывается **ТОЛЬКО** в слитки своего типа:
- Gold ore → Gold ingot (и больше ни во что)
- Platinum ore → Platinum ingot (и больше ни во что)
- Silver ore → Silver ingot (и больше ни во что)
- Нет никакой конвертации руд друг в друга. Не сочиняй про «переплавку» Iron в Gold, Silver в Gold, Platinum в Gold и т.п.
- Если пользователь просит добыть Gold, а его нет на карте — так и скажи, не предлагай добыть другое «вместо» золота.

## 1. Главные правила безопасности

1. На сервере должен быть загружен только один вариант Nanobot Drill. Нельзя одновременно держать оригинальный Nanobot Drill and Fill System и fork `Outenemy Nanobot Drill System - Automation Fixes`.
2. Для выборочной добычи использовать только режим **Collect**.
3. Реальные raw-значения режима:
   - `Drill = 1`
   - `Collect = 2`
   - `Fill = 4`
4. Никогда не использовать старую карту `Collect=1, Drill=2, Fill=0`. Это опасно: бур уходит в Drill и может брать камень.
5. Правильный порядок команд:
   1. `OnOff = False`
   2. отключить `CollectIfIdle` и `TerrainClearingMode`
   3. включить `ScriptControlled = True`
   4. выставить фильтры: `CollectFilter = Ore`, `OreFilter = нужная руда`
   5. выставить `Drill.WorkMode = 2`
   6. выключить `ScriptControlled = False`
   7. ещё раз выставить `Drill.WorkMode = 2`
   8. только потом выставлять `AreaOffset` и размеры области
   9. включать бур
6. `WorkMode` может сбросить `AreaOffset`. Поэтому сначала режим, потом область.
7. Если в telemetry появился `current=... Stone_..` или `targets` содержат только нецелевые материалы, агент должен сразу выключить бур и не двигать область дальше при включённом блоке.
8. Если `Stone delta > 0`, это аварийный признак. Для обычной выборочной добычи ожидается `Stone +0.0`.

## 2. Скрипты, которые оставить для нормальной работы

### Основные рабочие скрипты

#### `mine_ore_robot_safe_live_move.py`
Основной универсальный скрипт для добычи любой руды.

Использовать для обычной автоматической добычи:

```powershell
cd C:\secontrol

python examples\organized\drill_nano\mine_ore_robot_safe_live_move.py `
  --grid skynet-baza1 `
  --ore Platinum `
  --amount 5000 `
  --scan-radius 500 `
  --area-size 75 `
  --density-radius 20 `
  --max-points 120 `
  --startup-timeout 90 `
  --no-progress-timeout 60 `
  --working-point-min-seconds 180 `
  --check-interval 0.5 `
  --stone-safety-delta 20 `
  --inventory-delta-threshold 10 `
  --max-stone-per-ore-ratio 0.05
```

Для `--live-move` использовать только если уже проверено, что мод и фильтры работают стабильно. При появлении wrong target скрипт обязан останавливаться перед переносом зоны.

#### `mine_platinum_simple_v11_safe.py`
Проверенный простой сценарий именно для платины. Использовать как базовый тест после обновления мода.

```powershell
cd C:\secontrol

python examples\organized\drill_nano\mine_platinum_simple_v11_safe.py `
  --grid skynet-baza1 `
  --amount 5000 `
  --scan-radius 500 `
  --area-size 75 `
  --max-points 60 `
  --stone-safety-delta 20 `
  --allow-missing-marker
```

`--allow-missing-marker` допустим, если в игре видно, что мод новый, но detailed info не отдается в telemetry. Если появится нормальная property версии в telemetry, запускать без этого флага.

#### `scan_probe_mine_ore.py`
Оставить как общий helper и fallback-скрипт. `mine_platinum_simple_v11_safe.py` импортирует из него функции настройки, сканирования и расчета AreaOffset. Не удалять.

#### `configure_ore_only.py`
Утилита только для настройки фильтра без добычи. Нужна для проверки UI и terminal controls.

```powershell
cd C:\secontrol

python examples\organized\drill_nano\configure_ore_only.py `
  --grid skynet-baza1 `
  --ore Platinum
```

Ожидаемое состояние:

```text
WorkMode raw: 2
Stone -> False
Platinum -> True
Ore -> True
Stone class -> False
```

#### `stop_drill.py`
Аварийная остановка Nanobot Drill.

```powershell
cd C:\secontrol
python examples\organized\drill_nano\stop_drill.py --grid skynet-baza1
```

#### `set_nanodrill_area.py`
Оставить для диагностики и dry-run расчёта области. Не использовать перед добывающими скриптами, потому что последующая смена `WorkMode` может сбросить offset.

```powershell
cd C:\secontrol
python examples\organized\drill_nano\set_nanodrill_area.py `
  --grid skynet-baza1 `
  --target -56796.387 146498.057 -134204.677 `
  --dry-run
```

#### `check_nanodrill_strict_patch.py`
Диагностика активного мода и terminal properties. Использовать после установки новой сборки мода.

```powershell
cd C:\secontrol
python examples\organized\drill_nano\check_nanodrill_strict_patch.py --grid skynet-baza1
```

### Специальные скрипты вскрытия

#### `clear_until_platinum_visible.py`
#### `sweep_clear_until_ore_visible.py`

Это не обычная добыча. Эти скрипты работают с камнем намеренно, чтобы вскрыть оболочку до появления руды. Использовать только вручную и только если нужно открыть жилу. После вскрытия обязательно перевести бур обратно в безопасный Collect-only режим.

## 3. Скрипты, которые не использовать

### Удалить или перенести в `deprecated/`

- `start_drill.py` — содержит старую неправильную карту raw-режимов: `Collect=1`, `Drill=2`, `Fill=0`. Это опасно.
- `drill_diag.py` — в диагностике выставляет `Drill.WorkMode = 1` после фразы про Collect. Это может запустить Drill-режим.
- `simple_nano_drill.py` — hardcoded `taburet2`, пример старого формата.
- `simple_nano_drill_ice.py` — hardcoded `taburet2`, пример старого формата.
- `mine_platinum_simple_v8_safe.py` — заменить на `mine_platinum_simple_v11_safe.py`.
- `mine_ore_robot.py` — заменить на `mine_ore_robot_safe_live_move.py`.
- `mine_ore_robot_inventory_guard.py` — промежуточная версия, заменить на `mine_ore_robot_safe_live_move.py`.
- `mine_ore_robot_inventory_sticky.py` — промежуточная версия, заменить на `mine_ore_robot_safe_live_move.py`.
- `mine_ore_robot_live_move.py` — заменить на безопасный вариант `mine_ore_robot_safe_live_move.py`.
- `configure_platinum_only.py` — hardcoded `skynet-baza1`, заменить на `configure_ore_only.py`.
- `probe_scan_points_for_ore.py` — старый отдельный поиск по JSON. Использовать только если явно нужен `ore_latest.json`; в обычной добыче его заменяют scan-based скрипты.
- `mine_until.py` — старый target-only сценарий. Можно оставить в архиве, но агенту по умолчанию использовать `mine_ore_robot_safe_live_move.py` или `mine_platinum_simple_v11_safe.py`.

## 4. Проверка перед добычей

Перед запуском добычи агент должен проверить:

```text
Raw DrillPriorityList:
  stone=False
  target_ore=True
  all_other_ores=False

Raw ComponentClassList:
  Ore=True
  Stone=False
  Gravel=False
  Ingot=False

WorkMode raw: 2
ScriptControlled: False
CollectIfIdle: False
TerrainClearingMode: False
```

Если `WorkMode` не `2`, добычу не начинать.

Если `targets` есть, но среди них нет целевой руды, бур выключить и перейти к другой точке только после cooldown/очистки current target.

## 5. Нормальный лог добычи

Хороший лог:

```text
WorkMode=2
Stone +0.0
targets=1
OreTargets=1
current=... Platinum_01 ...
Platinum +...
```

Плохой лог:

```text
WorkMode=1
current=... Stone_05 ...
Stone +...
```

или:

```text
targets=4
OreTargets=0
current=... Stone_05 ...
```

В плохом случае агент обязан сразу вызвать `stop_drill.py` или hard stop внутри текущего скрипта.

## 6. Рекомендуемая структура папки

```text
examples/organized/drill_nano/
  mine_ore_robot_safe_live_move.py
  mine_platinum_simple_v11_safe.py
  scan_probe_mine_ore.py
  configure_ore_only.py
  stop_drill.py
  set_nanodrill_area.py
  check_nanodrill_strict_patch.py
  clear_until_platinum_visible.py
  sweep_clear_until_ore_visible.py
  nanodrill_agent.md

examples/organized/drill_nano/deprecated/
  start_drill.py
  drill_diag.py
  simple_nano_drill.py
  simple_nano_drill_ice.py
  mine_platinum_simple_v8_safe.py
  mine_ore_robot.py
  mine_ore_robot_inventory_guard.py
  mine_ore_robot_inventory_sticky.py
  mine_ore_robot_live_move.py
  configure_platinum_only.py
  probe_scan_points_for_ore.py
  mine_until.py
```

## 7. Команда для первого теста после установки мода

```powershell
cd C:\secontrol

python examples\organized\drill_nano\configure_ore_only.py `
  --grid skynet-baza1 `
  --ore Platinum

python examples\organized\drill_nano\mine_platinum_simple_v11_safe.py `
  --grid skynet-baza1 `
  --amount 1000 `
  --scan-radius 500 `
  --area-size 75 `
  --max-points 60 `
  --stone-safety-delta 20 `
  --allow-missing-marker
```

Если `Stone +0.0` и `Platinum +...`, можно переходить на `mine_ore_robot_safe_live_move.py`.
