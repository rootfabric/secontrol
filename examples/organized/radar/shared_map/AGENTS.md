# SharedMapController — Agent Instructions

Быстрый доступ к сохранённым рудам через SharedMapController (Redis/SQLite).

## Когда использовать

Любой запрос "найди руду", "покажи месторождения", "где платина", "что насканировано" — сначала проверять SharedMapController. Если данных нет — запускать `shared_map_scan.py`.

## Скрипты

### 1. `shared_map_scan.py` — сканировать и сохранить

Один вызов: сканирует руды в радиусе 1 км (ore-only), сохраняет в SharedMap.

```bash
python examples/organized/radar/shared_map/shared_map_scan.py --grid skynet-baza0
python examples/organized/radar/shared_map/shared_map_scan.py --grid skynet-baza0 --radius 300 --no-save
```

Параметры:
- `--grid` — имя грида (по умолч. skynet-baza0)
- `--radius` — радиус скана в метрах (по умолч. 1000)
- `--no-save` — сухой прогон без сохранения
- `--storage sqlite` — использовать SQLite вместо Redis

### 2. `shared_map_deposits.py` — найти руду по расстоянию

Показывает месторождения отфильтрованные по типу, сортированные по дистанции от корабля.

```bash
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-baza0 --material Platinum --clusters --gps
```

Параметры:
- `--material` — фильтр по типу руды (Platinum, Gold, Iron...)
- `--clusters` — группировать в кластеры (рекомендуется)
- `--order nearest/farthest` — сортировка
- `--gps` — показать GPS-маркеры для SE
- `--limit N` — ограничить количество

Если в SharedMap пусто — автоматически ищет в `ore_database.jsonl` / `ore_latest.json`.

### 3. `shared_map_report.py` — полный отчёт

Агрегированная статистика по всем известным рудам, кластерам и чанкам.

```bash
python examples/organized/radar/shared_map/shared_map_report.py
python examples/organized/radar/shared_map/shared_map_report.py --material Platinum
python examples/organized/radar/shared_map/shared_map_report.py --grid skynet-baza0
```

### 4. `shared_map_memory.py` — пример работы с SharedMapController

Демонстрация: скан → запись → регион вокруг корабля → индекс. Для изучения API.

```bash
python examples/organized/radar/shared_map/shared_map_memory.py --grid skynet-baza0
```

## Типовой пайплайн для агента

```
1. Запрос: "найди платину"
→ shared_map_deposits.py --grid <grid> --material Platinum --clusters

2. Если пусто:
→ shared_map_scan.py --grid <grid> --radius 300
→ shared_map_deposits.py --grid <grid> --material Platinum --clusters

3. Если пусто даже после скана → ответить "Платина не найдена в радиусе скана, нужно лететь к другому астероиду"
```

## Импорт в других скриптах

```python
from examples.organized.radar.shared_map.shared_map_deposits import get_deposits_sorted

deps = get_deposits_sorted(material="Platinum", order="nearest")
for d in deps:
    print(f"{d['material']} @ {d['position']} — {d['distance_m']}m")
```

## Структура данных SharedMapController

| Команда | Что смотрит |
|---|---|
| `shared_map_report.py` | SharedMap (Redis/SQLite) |
| `shared_map_deposits.py --clusters` | SharedMap → fallback `ore_database.jsonl` |
| `shared_map_deposits.py` (без --clusters) | SharedMap → fallback `ore_latest.json` + `all_deposits` |
| `shared_map_scan.py` | Новый скан → сохраняет в SharedMap |
