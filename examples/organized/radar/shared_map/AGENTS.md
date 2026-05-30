# SharedMapController — Agent Instructions

Быстрый доступ к сохранённым рудам через SharedMapController (Redis/SQLite).

## Когда использовать

Любой запрос "найди руду", "покажи месторождения", "где платина", "что насканировано" — сначала проверять SharedMapController. Если данных нет — запускать `ore_scanner.py`.

## Скрипты

### 1. `ore_scanner.py` — универсальный сканер (ФАЙЛ + REDIS) ⭐

**Основной скрипт для сканирования руд.** Сохраняет одновременно в JSON-файл и SharedMap (Redis/SQLite).

```bash
python examples/organized/radar/ore_scanner.py --grid agent1
python examples/organized/radar/ore_scanner.py --grid agent1 --radius 500
python examples/organized/radar/ore_scanner.py --grid agent1 --no-redis    # только файл
python examples/organized/radar/ore_scanner.py --grid agent1 --storage sqlite
python examples/organized/radar/ore_scanner.py --find Platinum              # поиск в последнем скане
```

Параметры:
- `--grid` — имя грида (по умолч. skynet-baza0)
- `--radius` — радиус скана в метрах (по умолч. 1000)
- `--no-redis` — пропустить SharedMap, сохранить только в файл
- `--storage sqlite` — использовать SQLite вместо Redis
- `--full_scan` — дополнительно сделать полный воксельный скан
- `--find ORE` — найти ближайшее месторождение ORE в последнем скане
- `--output` — свой путь для JSON-файла

Результат сохраняется в:
- `~/hermeswebui/se-data/scans/ore_scan_<timestamp>.json` — конкретный скан
- `~/hermeswebui/se-data/scans/ore_latest.json` — последний скан
- `~/hermeswebui/se-data/ore_database.jsonl` — база всех сканов
- SharedMap (Redis) — для доступа других гридов/агентов

### 2. `shared_map_sync.py` — синхронизация локальных данных в Redis

Загружает данные из локальных JSON-файлов в SharedMap. Когда уже есть сканы от `ore_scanner.py`, но нужно обновить Redis для других агентов.

```bash
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1                    # из ore_latest.json
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --source jsonl     # из ore_database.jsonl (все сканы)
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --source all       # latest + jsonl
python examples/organized/radar/shared_map/shared_map_sync.py --grid agent1 --dry-run          # без сохранения
```

Параметры:
- `--source latest` — только последний скан (ore_latest.json)
- `--source jsonl` — все сканы из ore_database.jsonl (дедупликация)
- `--source all` — оба источника
- `--dry-run` — показать что будет загружено, без сохранения
- `--storage sqlite` — SQLite вместо Redis

### 3. `shared_map_deposits.py` — найти руду по расстоянию

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

### 4. `shared_map_report.py` — полный отчёт

Агрегированная статистика по всем известным рудам, кластерам и чанкам.

```bash
python examples/organized/radar/shared_map/shared_map_report.py
python examples/organized/radar/shared_map/shared_map_report.py --material Platinum
python examples/organized/radar/shared_map/shared_map_report.py --grid skynet-baza0
```

### 5. `shared_map_memory.py` — пример работы с SharedMapController

Демонстрация: скан → запись → регион вокруг корабля → индекс. Для изучения API.

```bash
python examples/organized/radar/shared_map/shared_map_memory.py --grid skynet-baza0
```

### 6. `clear_ore_data.py` — очистка данных руд после рестарта

Удаляет все ore-чанки из Redis и чистит индекс. Нужно после рестарта сервера, когда координаты руд устарели.

```bash
python examples/organized/radar/shared_map/clear_ore_data.py                # dry-run — показать что будет удалено
python examples/organized/radar/shared_map/clear_ore_data.py --apply         # удалить все ore-данные
python examples/organized/radar/shared_map/clear_ore_data.py --apply --keep-index  # удалить ключи, но оставить индекс
```

Параметры:
- `--apply` — реально удалить (по умолчанию dry-run)
- `--keep-index` — не очищать список ore-чанков из индекса
- `--owner-id` — Owner ID (по умолчанию из .env)

## Типовой пайплайн для агента

```
0. После рестарта сервера — очистить устаревшие данные:
→ clear_ore_data.py --apply
→ ore_scanner.py --grid <grid>   # свежий скан (файл + Redis)

1. Запрос: "найди платину"
→ shared_map_deposits.py --grid <grid> --material Platinum --clusters

2. Если пусто:
→ ore_scanner.py --grid <grid> --radius 300
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
| `ore_scanner.py` | Новый скан → сохраняет в файл + SharedMap |
| `shared_map_sync.py` | Локальные файлы → загрузка в SharedMap |
| `shared_map_report.py` | SharedMap (Redis/SQLite) |
| `shared_map_deposits.py --clusters` | SharedMap → fallback `ore_database.jsonl` |
| `shared_map_deposits.py` (без --clusters) | SharedMap → fallback `ore_latest.json` + `all_deposits` |
| `clear_ore_data.py` | Удалить все ore-данные из Redis (после рестарта) |
