# parking — Модуль автоматической парковки

Комплексное решение для автоматической парковки и стыковки дронов/кораблей с базой.

## 📁 Структура

```
parking/
├── __init__.py       # Публичный API реэкспорта
├── helpers.py        # Математика, вектора, статус коннекторов
├── docking.py        # Основная логика стыковки (final_approach_and_dock)
├── parking.py        # Управление режимом парковки грида
├── calc_point.py     # Вычисление точки парковки по forward коннектора
├── final_park.py     # CLI: полный цикл парковки
└── README.md         # Этот файл
```

## 🚀 Быстрый старт

### Автоматическая парковка (CLI)

```bash
cd C:\secontrol
python parking/final_park.py
```

### Из кода

```python
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from parking import (
    DockingConfig,
    calculate_connector_forward_point_by_name,
    prepare_for_parking,
    final_approach_and_dock,
)

client = RedisEventClient()
base = Grid.from_name("DroneBase 2", redis_client=client)
drone = Grid.from_name("taburet3", redis_client=client)

# 1. Подготовка
prepare_for_parking(drone)

# 2. Полёт на 10м по forward коннектора базы
point = calculate_connector_forward_point_by_name("DroneBase 2", distance=10.0, redis_client=client)
# ... отправить дрон к точке ...

# 3. Векторное снижение и стыковка
rc = drone.find_devices_by_type("remote_control")[0]
ship_conn = drone.find_devices_by_type("connector")[0]
base_conn = base.find_devices_by_type("connector")[0]

config = DockingConfig(base_grid=base, ship_grid=drone)
result = final_approach_and_dock(rc, ship_conn, base_conn, config)

# 4. Парковка (только коннекторы, трастеры работают!)
if result.success:
    drone.park(enabled=True, brake_wheels=True, shutdown_thrusters=False, lock_connectors=True)
```

## 📐 Алгоритм парковки

### Шаг 1: Полёт на 10м по forward коннектора базы
```
target = base_conn_position + base_conn_forward * 10
```

### Шаг 2: Векторное снижение к коннектору
- Пошаговое сближение ship_conn → base_conn
- Проверка соосности (dot product forward векторов)
- Callback: прерывание при `Connectable` статусе
- Адаптивная скорость: 3м/с далеко → 0.5м/с близко

### Шаг 3: Стыковка
- Ожидание статуса `Connectable` или `Connected`
- Вызов `ship_conn.connect()`
- Включение парковки (коннекторы заблокированы, трастеры работают)

## 🔧 Константы

| Параметр | Значение | Описание |
|----------|----------|----------|
| `ARRIVAL_DISTANCE` | 0.20 м | Точность прилёта RC к цели |
| `RC_STOP_TOLERANCE` | 0.7 м | Допуск остановки АП |
| `MAX_FLIGHT_TIME` | 240 с | Максимальное время полёта |
| `MAX_DOCK_STEPS` | 30 | Максимум итераций снижения |
| `DOCK_SUCCESS_TOLERANCE` | 0.6 м | Допуск успешной стыковки |

## 📊 Статусы коннектора

| Статус | Описание | Действие |
|--------|----------|----------|
| `Unconnected` | Не подключён | Готов к стыковке |
| `Connectable` | Готов к блокировке | Вызвать `connect()` |
| `Connected` | Состыкован | Включить парковку |

## 🧩 API

### helpers.py
- `_parse_vector()` — парсинг вектора из GPS/dict/list
- `_normalize()`, `_cross()`, `_add()`, `_sub()`, `_scale()`, `_dist()` — математика
- `Basis` — класс для forward/up/right ориентации
- `get_connector_status()` — получить статус коннектора
- `is_already_docked()` — проверять, состыкован ли
- `is_parking_possible()` — можно ли парковаться

### docking.py
- `DockingConfig` — конфигурация стыковки
- `DockingResult` — результат операции
- `final_approach_and_dock()` — плавное снижение + стыковка с проверкой соосности

### parking.py
- `park_grid()`, `unpark_grid()` — режим парковки
- `prepare_for_parking()` — подготовка корабля к парковке
- `finalize_parking()` — финализация после стыковки
- `undock_ship()` — отстыковать корабль

### calc_point.py
- `calculate_connector_forward_point()` — точка по forward коннектора (Grid)
- `calculate_connector_forward_point_by_name()` — точка по имени базы (CLI)

## 📂 Примеры скриптов

В `examples/organized/parking/`:
- `park_drone_auto.py` — автоматическая парковка
- `fly_forward_10m.py` — полёт на 10м по forward
- `final_dock.py` — финальная стыковка
- `return_drone_to_base.py` — возврат дрона на базу
- `undock_drone.py` — отстыковка
- `analyze_park.py` — анализ точки парковки

В `examples/organized/diagnostics/`:
- `check_grids.py` — список всех гридов
- `check_dronebase.py` — состав DroneBase
- `check_generator*.py` — диагностика генератора
- `diag_connector.py` — диагностика коннекторов
- `diag_control.py` — диагностика управления
- `find_*.py` — поиск гридов/дронов

В `examples/organized/utils/`:
- `build_generator.py` — достройка генератора
- `fix_control.py` — починка ручного управления
- `list_all_grids.py` — список всех гридов
- `rename_*.py` — переименование гридов
- `repair_rc.py` — ремонт RemoteControl
- `weld_generator.py` — сварка генератора
