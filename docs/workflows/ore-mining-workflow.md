# Сбор руды — полный цикл добычи

## Быстрый цикл добычи (одна команда)

```bash
# 1. Сканировать руду
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500

# 2. Добыть нужное кол-во
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --amount 5000 \
    --check-interval 5
```

Всё — бурение запустится и остановится автоматически при достижении целевого количества.

---

## Пошаговая инструкция для агента

### Шаг 1 — Сканировать руду

```bash
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500
```

Результат: GPS координаты рудных кластеров. Например:
```
Nickel: 37 deposits, closest: 93m
GPS:Nickel_1:-50626.3:146646.9:-137739.8:#FF8800:
Silicon: 3 deposits, closest: 298m
GPS:Silicon_3:-50473.4:146686.4:-137884.5:#FF8800:
```

### Шаг 2 — Навести зону бура на руду

```bash
python examples/organized/drill_nano/set_nanodrill_area.py \
    --grid skynet-baza0 \
    --target X Y Z \
    --reset-area
```

- `--target` — координаты из шага 1 (GPS cluster center)
- `--reset-area` — сбросить offsets перед наведением

Скрипт вычисляет `AreaOffsetFrontBack`, `AreaOffsetUpDown`, `AreaOffsetLeftRight` и применяет.

### Шаг 3 — Добыть нужное количество

```bash
python examples/organized/drill_nano/mine_until.py \
    --grid skynet-baza0 \
    --ore Nickel \
    --amount 5000 \
    --check-interval 5
```

- `--amount` — сколько добыть (delta от текущего)
- `--check-interval` — как часто проверять (сек)
- `--ore` — тип руды (Nickel, Gold, Silicon, Uranium, Iron и т.д.)

Скрипт:
1. Фиксирует baseline
2. Запускает бурение с фильтром на нужную руду
3. Мониторит контейнеры каждые N секунд
4. Останавливает при достижении цели
5. Показывает rate (ед/сек) и ETA

### Шаг 4 — Проверить результат

```python
grid.get_all_grid_items()  # все предметы на гриде
# или фильтр:
grid.find_items_by_subtype("Nickel")
```

---

## Ключевые скрипты

| Скрипт | Назначение |
|--------|------------|
| `ore_deposit_scanner.py` | Сканировать руду на астероиде |
| `set_nanodrill_area.py` | Навести зону бура на координаты |
| `mine_until.py` | Добыть нужное кол-во и остановиться |

---

## Важно

- **Ore фильтр:** `mine_until.py` фильтрует камень автоматически — только запрошенная руда
- **Drill area reach:** Цель должна быть ≤~110m от drill. Если дальше — нужен полёт ближе
- **Корабль на месте:** Зона добычи сдвигается через AreaOffset, не через полёт
- **Остановка бура:** `drill.stop_drilling()` + `drill.turn_off()`

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| targets=0 после наведения | Sweep offsets ±50m; или цель вне зоны reach (>110m от drill) |
| Нет Nickel в контейнерах | Проверить `surfaceDistance=0` — корабль должен быть на астероиде |
| Фильтр не работает | `start_drilling_ore(["Nickel"])` — фильтрует камень |
| Drill state corruption | Полный reset: stop→off→offsets=0→WorkMode=Collect→on→start |