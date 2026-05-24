# Nanobot Drill — Complete Mining Workflow

Tested and verified on skynet-baza0 (large grid, Mars orbit/asteroid field).
**Последняя верификация: 2026-05-24** — добыто 10 279 ед. никеля за ~4 мин.

## Полный пайплайн (одна команда)

```bash
# 0. Проверить известные месторождения
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-baza0 --material Nickel --clusters --gps

# Если руда найдена — перейти к шагу 2 (скан не нужен)

# 1. Сканировать руду (если shared map пуст)
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500

#    Если scanner вернул 0 ore cells — использовать прямой scan_and_wait():
python -c "
from secontrol import Grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
grid = Grid.from_name('skynet-baza0')
det = grid.find_devices_by_type(OreDetectorDevice)[0]
det.scan_and_wait(radius=500, ore_only=True, timeout=30)
cells = det.ore_cells()
nickel = [c for c in cells if c['ore'] == 'Nickel']
print(f'Nickel cells: {len(nickel)}')
for c in nickel[:3]:
    print(f'  {c[\"position\"]} content={c[\"content\"]}')
"

# 2. Долететь до руды
python examples/space_flight/space_navigator_v4.py \
    --grid skynet-baza0 \
    --target="-50626.7,146646.4,-137736.2" \
    --arrival 50

# 3. Добыть 10 000 единиц (mine_until.py сам наводит AreaOffset, включает, мониторит)
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --target -50626.734 146646.403 -137736.175 \
    --amount 10000 \
    --check-interval 5
```

---

## Пошаговая инструкция для агента

### Шаг 0 — Проверить уже разведанные руды (SharedMap)

```bash
python examples/organized/radar/shared_map/shared_map_deposits.py \
    --grid skynet-baza0 --material Nickel --clusters --gps
```

Если данные есть — перейти к Шагу 2 (полёт), скан не нужен.

### Шаг 1 — Сканировать руду

⚠️ **ВАЖНО**: `ore_deposit_scanner.py` может вернуть 0 ore cells (stale scan data).
В этом случае использовать прямой `scan_and_wait()` на OreDetectorDevice.

```bash
# Быстрый скан через scanner
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500

# Если scanner вернул 0 ценных руд — прямой скан через device API:
python -c "
import time
from secontrol import Grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
grid = Grid.from_name('skynet-baza0')
det = grid.find_devices_by_type(OreDetectorDevice)[0]
det.scan_and_wait(radius=500, ore_only=True, timeout=30)
time.sleep(1)
cells = det.ore_cells()
ores = {}
for c in cells:
    t = c['ore']
    ores[t] = ores.get(t, 0) + 1
for t, n in sorted(ores.items(), key=lambda x: -x[1]):
    print(f'{t}: {n}')
"
```

Результат — мировые координаты ячеек руды.

### Шаг 2 — Долететь до руды

Использовать `space_navigator_v4.py`. Навигатор обходит астероид и
останавливается на безопасном расстоянии.

```bash
python examples/space_flight/space_navigator_v4.py \
    --grid skynet-baza0 \
    --target="-50626.7,146646.4,-137736.2" \
    --arrival 50
```

- `--arrival 50` — остановиться в 50м от запрошенной точки
- Навигатор сам найдёт путь вокруг астероида
- Не пытаться лететь вплотную к руде — краш в астероид

### Шаг 3 — Добыть руду (mine_until.py — одна команда)

**Это единственная команда, которая реально нужна.** Она делает всё:

1. Выключает бур
2. Настраивает фильтры (Collect, Ore, Nickel)
3. **Вычисляет и применяет AreaOffset ПОСЛЕ WorkMode** (критично!)
4. Включает бур (ждёт ~10с для авто-старта)
5. Мониторит контейнеры каждые N секунд
6. Показывает rate (ед/сек) и ETA
7. Останавливает бур при достижении целевого количества

```bash
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --target -50626.734 146646.403 -137736.175 \
    --amount 10000 \
    --check-interval 5
```

**Координаты `--target`** — мировые координаты рудной ячейки (X Y Z через пробел).
Их можно взять из вывода скана (любая никелевая ячейка из ore_cells).

---

## Критические правила добычи

### 🔴 WorkMode сбрасывает AreaOffset — порядок важен!

**WorkMode (Collect/Drill/Fill) сбрасывает AreaOffset на 0.**

Правильный порядок операций:
```
1. Выключить бур
2. ScriptControlled=True
3. Установить фильтры (CollectFilter, OreFilter)
4. Установить WorkMode (Collect/Drill/Fill)  ← сбрасывает AreaOffset
5. ScriptControlled=False
6. Установить WorkMode ещё раз (для надёжности)
7. Установить AreaOffset  ← ПОСЛЕ WorkMode!
8. Включить бур
```

**`mine_until.py` делает это в правильном порядке.**
**`set_nanodrill_area.py` НЕ учитывает это** — если после него вызвать WorkMode,
офсеты сбросятся.

### 🔴 Сканер может возвращать 0 руды (stale data)

`ore_deposit_scanner.py` использует `RadarController`, который читает из общей
сканированной области. Если скан уже был сделан (например, навигатором), данные
могут быть устаревшими без рудных ячеек.

**Решение:** прямой вызов `OreDetectorDevice.scan_and_wait()` форсирует свежий скан.

### ✅ Одна команда вместо трёх

Вместо:
```bash
set_nanodrill_area.py ...     # может не сработать из-за порядка
# потом drill config...
# потом start...
```

Делать:
```bash
mine_until.py --grid ... --ore ... --target X Y Z --amount ...
```

### Расстояние до руды

Nanobot Drill имеет зону 75×75×75м со сдвигом до ±1000м по каждой оси.
Останавливаться на расстоянии **100-200м** от руды — безопасно и эффективно.

| Ситуация | Расстояние |
|---|---|
| Nanobot Drill | 100-1000м (100-200м оптимально) |
| Обычный drill | <50м |
| Приказ остановиться | `--arrival 50` в навигаторе |

---

## Результат тестового запуска (2026-05-24)

| Параметр | Значение |
|---|---|
| Корабль | skynet-baza0 |
| Руда | Nickel |
| Координаты | -50626.734, 146646.403, -137736.175 |
| Расстояние от бура | 163м |
| Офсеты | FB=+161.3, UD=+21.8, LR=-14.3 |
| Целей найдено | 45 всего, 3 Nickel |
| Добыто | 10 279 ед. (10.28 тонн) |
| Время | 3 мин 50 сек |
| Скорость | ~45 ед/с |
| Фильтр | Collect + Ore + Nickel |
| ScriptControlled | False |

### Что было сделано (точная последовательность)

```
1. shared_map_deposits.py — найдено 2 кластера никеля (214м, 278м)
2. ore_deposit_scanner.py — вернул 0 ore cells (stale data)
3. det.scan_and_wait() — нашёл 31 ячейку никеля
4. space_navigator_v4.py --arrival 50 — перелёт к руде
5. mine_until.py --amount 10000 — добыча (сам всё настроил)
```

## Troubleshooting

| Симптом | Причина | Фикс |
|---|---|---|
| targets=0 после конфига | WorkMode сбросил AreaOffset | Ставить AreaOffset ПОСЛЕ WorkMode |
| 0 ore cells в scanner | Stale scan data | Использовать `det.scan_and_wait()` напрямую |
| targets=0 | Корабль не на астероиде | Проверить surfaceDistance=0 |
| targets=0 после многих изменений | Drill state corruption | Полный reset (off → WorkMode → AreaOffset → on) |
| targets>0 но не добывает | ScriptControlled=True | Установить ScriptControlled=False |
| Руда поступает в Container | Нормально | Проверять grid.get_all_grid_items(), а не drill |
| Корабль врезался в астероид | Слишком близко к руде | Не лететь ближе 50м от руды |
