# parking — Автоматическая парковка и стыковка дронов

Комплексное решение для автоматической парковки и стыковки дронов/кораблей с базой.

## 📁 Структура

```
examples/organized/parking/
├── lib/                        # Библиотека (Python-пакет)
│   ├── __init__.py             # Публичный API
│   ├── helpers.py              # Математика, вектора, статус коннекторов
│   ├── docking.py              # Логика стыковки (final_approach_and_dock)
│   ├── parking.py              # Управление режимом парковки грида
│   └── calc_point.py           # Вычисление точки парковки по forward
├── final_park.py               # CLI: полный цикл парковки (3 шага)
├── park_drone_auto.py          # Автопарковка через dock_procedure()
├── park_drone.py               # Ручная парковка с мониторингом
├── park_mode.py                # Вкл/выкл режима парковки
├── fly_forward_10m.py          # Полёт на 10м по forward коннектора
├── lift_drone.py               # Подъём дрона вверх
├── return_drone_to_base.py     # Возврат дрона на базу
├── undock_drone.py             # Отстыковка
├── undock_and_fix.py           # Отстыковка + починка
└── analyze_park.py             # Анализ точки парковки
```

## 🚀 Быстрый старт

### Полный цикл парковки (CLI)

```bash
cd /path/to/secontrol
python examples/organized/parking/final_park.py
```

### Из кода

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "examples/organized/parking"))

from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from lib import (
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

# 3. Векторное снижение и стыковка
rc = drone.find_devices_by_type("remote_control")[0]
ship_conn = drone.find_devices_by_type("connector")[0]
base_conn = base.find_devices_by_type("connector")[0]

config = DockingConfig(base_grid=base, ship_grid=drone)
result = final_approach_and_dock(rc, ship_conn, base_conn, config)
```

## 🚀 Docking in Space — `dock.py`

**For ALL docking operations in space (connector-to-connector), use `dock.py`:**

```bash
python examples/organized/parking/dock.py <ship> <target> [approach_distance]
```

**Examples:**
```bash
python examples/organized/parking/dock.py skynet-worker2 farpost0
python examples/organized/parking/dock.py skynet-baza2 skynet-farpost0 80
```

**3-Phase algorithm:**
1. **Phase 1**: Fly to approach point (100m in front of target connector)
2. **Phase 2**: Rotate ship so connector faces target connector (gyro P-controller)
3. **Phase 3**: Approach along connector axis + auto-lock (`connectorStatus == "Connectable"` → `connect()`)

**⚠️ Collision avoidance MUST be OFF for docking.** The base sits on an asteroid — SE's built-in CA detects voxels and stops the ship prematurely.

## 📐 Алгоритм парковки (3 шага)

1. **Подлёт** — RC летит на 10м по forward коннектора базы
2. **Снижение** — пошаговое сближение ship_conn → base_conn с проверкой соосности
3. **Стыковка** — connect() при статусе Connectable, включение парковки

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
