# Сбор руды — полный цикл добычи

## Быстрый цикл добычи (одна команда)

```bash
# 0. Проверить известные руды (чтобы не сканировать заново)
python examples/organized/radar/shared_map/shared_map_deposits.py \
    --grid skynet-baza0 --material Nickel --clusters --gps

# Если руда не найдена:
# 1. Сканировать руду
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500
#    Если scanner вернул 0 — использовать прямой scan_and_wait() (см. Шаг 1)

# 2. Долететь до руды (навигатор сам облетит астероид)
python examples/space_flight/space_navigator_v4.py \
    --grid skynet-baza0 \
    --target="X,Y,Z" \
    --arrival 50

# 3. Добыть нужное кол-во (одна команда — mine_until сам наводит бур, включает, мониторит)
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --target X Y Z \
    --amount 10000 \
    --check-interval 5
```

Всё — бурение запустится и остановится автоматически при достижении целевого количества.

**⚠️ ВАЖНО:** Не запускать `set_nanodrill_area.py` отдельно перед `mine_until.py`.
`mine_until.py` сам вычисляет и применяет AreaOffset **в правильном порядке**
(после WorkMode). Если запустить `set_nanodrill_area.py` до `mine_until.py`,
WorkMode внутри `mine_until.py` сбросит эти офсеты.

---

## Пошаговая инструкция для агента

### Шаг 0 — Проверить уже разведанные руды

**Всегда начинать с этого шага.** Не сканировать заново то, что уже известно.

```bash
# Проверить SharedMapController (или JSON-базу как fallback)
python examples/organized/radar/shared_map/shared_map_deposits.py \
    --grid <grid_name> --material Platinum --clusters

# Если нужен полный отчёт по всем рудам
python examples/organized/radar/shared_map/shared_map_report.py --grid <grid_name>
```

**Если руда найдена** — перейти к Шагу 2 (полёт), скан не нужен.

**Если SharedMapController пуст / нет нужной руды** — перейти к Шагу 1 (свежий скан).

**Когда обновлять SharedMapController:** после каждого нового скана через `ore_deposit_scanner.py` данные в SharedMap не попадают автоматически. Запустить `shared_map_scan.py` чтобы сохранить:

```bash
python examples/organized/radar/shared_map/shared_map_scan.py --grid <grid_name>
```

### Шаг 1 — Сканировать руду

**Когда:** руда не найдена на шаге 0.

**⚠️ ВАЖНО:** `ore_deposit_scanner.py` может вернуть 0 ore cells
(stale scan data — навигатор мог уже сканировать эту область без ore_only).
В таком случае — использовать прямой `scan_and_wait()` на `OreDetectorDevice`.

```bash
# Стандартный скан (начинать с 500м — сервер ограничивает до 300м эффективно)
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500

# После скана — сохранить в SharedMapController
python examples/organized/radar/shared_map/shared_map_scan.py --grid skynet-baza0 --radius 500
```

Если `ore_deposit_scanner.py` вернул 0 ценных руд — форсировать свежий скан:

```bash
python -c "
import time
from secontrol import Grid
from secontrol.devices.ore_detector_device import OreDetectorDevice

grid = Grid.from_name('skynet-baza0')
det = grid.find_devices_by_type(OreDetectorDevice)[0]
det.scan_and_wait(radius=500, ore_only=True, timeout=30)
time.sleep(1)
cells = det.ore_cells()
print(f'Найдено ячеек руды: {len(cells)}')
ores = {}
for c in cells:
    t = c['ore']
    ores[t] = ores.get(t, 0) + 1
for t, n in sorted(ores.items(), key=lambda x: -x[1]):
    print(f'  {t}: {n} жил')
    for c in cells:
        if c['ore'] == t:
            print(f'    {c[\"position\"]} content={c[\"content\"]}')
            break
"
```

Результат: мировые координаты ячеек руды. Например:
```
Nickel: 31 deposits
    [-50626.734, 146646.403, -137736.175] content=255
Silicon: 2 deposits
    [-50476.734, 146686.403, -137886.175] content=255
```

**Координаты любой никелевой ячейки можно использовать как `--target` в mine_until.py.**

### Шаг 2 — Долететь до руды (космос)

```bash
python examples/space_flight/space_navigator_v4.py \
    --grid skynet-baza0 \
    --target="X,Y,Z" \
    --arrival 50
```

- `--target` — координаты рудного кластера или ячейки из шага 1
- `--arrival 50` — остановиться в 50m от цели (навигатор сам облетит астероид)
- В результате корабль оказывается ~100-200м от руды

### Шаг 3 — Добыть руду (одна команда)

**⚠️ ВАЖНО:** Не использовать `set_nanodrill_area.py` + ручной конфиг бура отдельно.
`mine_until.py` сам делает всё в правильном порядке:

```bash
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --target X Y Z \
    --amount 10000 \
    --check-interval 5
```

- `--target` — мировые координаты руды (X Y Z через пробел, из шага 1)
- `--amount` — сколько добыть (delta от текущего)
- `--check-interval` — как часто проверять (сек)
- `--ore` — тип руды (Nickel, Gold, Platinum, Silicon, Uranium, Iron и т.д.)

**Что делает mine_until.py внутри (правильный порядок):**

```
1. Выключает бур
2. ScriptControlled=True
3. CollectFilter = ["Ore"]
4. OreFilter = [Nickel]
5. WorkMode = Collect    ← СБРАСЫВАЕТ AreaOffset!
6. ScriptControlled = False
7. WorkMode = Collect    ← ещё раз, для надёжности
8. AreaOffset = FB=+161.3, UD=+21.8, LR=-14.3   ← ПОСЛЕ WorkMode!
9. ShowArea = True
10. OnOff = True (ждёт ~10с для авто-старта)
11. Мониторит контейнеры каждые N секунд
12. Показывает rate (ед/сек) и ETA
13. Останавливает при достижении цели
```

**Почему нельзя запускать set_nanodrill_area.py перед mine_until.py:**
- `set_nanodrill_area.py` ставит AreaOffset (шаг 8)
- `mine_until.py` при запуске ставит WorkMode (шаг 5,7) — **это сбрасывает AreaOffset в 0!**
- В результате offsets теряются, бур не видит цели

**Решение:** `mine_until.py` вычисляет AreaOffset сам и применяет его ПОСЛЕ WorkMode.

### Шаг 5 — Проверить результат

```python
grid.get_all_grid_items()  # все предметы на гриде
# или фильтр:
grid.find_items_by_subtype("Platinum")
```

---

## Ключевые скрипты

| Скрипт | Назначение |
|--------|------------|
| `ore_deposit_scanner.py` | Сканировать руду на астероиде, автоматически пишет в БД |
| `set_nanodrill_area.py` | Навести зону бура на координаты |
| `mine_until.py` | Добыть нужное кол-во и остановиться |

---

## База руд

При каждом скане `ore_deposit_scanner.py` автоматически дописывает результат в `ore_database.jsonl`:

```
~/hermeswebui/se-data/ore_database.jsonl
```

Формат — JSONL (одна строка = один скан). Содержит:
- `asteroid` — название, центр, distance, radius
- `ore_summary` — Nickel: X dep, Silicon: Y dep...
- `clusters` — координаты кластеров с GPS
- `ship_position` — позиция корабля на момент скана

**Агенту не нужно ничего делать вручную** — запустил скан, данные уже в БД.

---

## Важно

- **WorkMode сбрасывает AreaOffset!** AreaOffset нужно ставить ПОСЛЕ WorkMode.
  `mine_until.py` делает это правильно. `set_nanodrill_area.py` — нет.
- **Nanobot Drill radius: 1000m** — не подлетай близко! Останавливайся в 100-200m.
- **Сканер может вернуть 0** — `ore_deposit_scanner.py` использует stale data.
  Используй `det.scan_and_wait()` для свежего скана.
- **Drill reach:** 75×75×75м со сдвигом до ±1000м по каждой оси. 163м от бура — работает.
- **Корабль на месте:** Зона добычи сдвигается через AreaOffset, не через полёт.
- **Остановка бура:** `mine_until.py` сам останавливает бур при достижении цели.

## Troubleshooting

| Симптом | Причина | Фикс |
|---------|---------|------|
| targets=0 | WorkMode сбросил AreaOffset | Использовать mine_until.py (ставит Offset после WorkMode) |
| 0 ore cells в scanner | Stale scan data | Использовать `det.scan_and_wait()` напрямую |
| Нет Nickel в контейнерах | Корабль не на астероиде | Проверить surfaceDistance=0 |
| Фильтр не работает | Вызван start_drilling() после Collect | Не вызывать start_drilling() |
| Drill state corruption | Много изменений конфига | Полный reset (off→WorkMode→AreaOffset→on) |
