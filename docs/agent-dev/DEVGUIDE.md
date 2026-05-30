# Agent Developer Guide — Разработка и расширение secontrol

Агент пишет код? Начни здесь. Структура проекта, API, как добавлять устройства и скрипты.

---

## Начало работы

```bash
# Структура проекта и конвенции
agent/REPO_GUIDE.md

# Скиллы и их синхронизация с Hermes
agent/README.md
```

---

## Env переменные

```
REDIS_USERNAME     # from outenemy.ru/se
REDIS_PASSWORD     # from outenemy.ru/se
SE_OWNER_ID        # Space Engineers owner ID
SE_PLAYER_ID       # Player ID (falls back to owner)
```

Файл `.env` в корне проекта.


---

## Архитектура проекта

```
secontrol/
├── src/secontrol/           # Основная библиотека
│   ├── common.py            # prepare_grid(), close(), resolve_owner_id()
│   ├── controllers/         # Бизнес-логика
│   │   ├── radar_controller.py
│   │   ├── shared_map_controller.py
│   │   └── space_navigator_controller.py
│   ├── devices/             # Драйверы устройств SE
│   │   ├── ore_detector_device.py
│   │   ├── remote_control_device.py
│   │   └── ...
│   └── tools/               # Утилиты
│       └── navigation_tools.py
├── examples/organized/      # Готовые скрипты
│   ├── radar/               # Сканеры, обзор, SharedMap
│   ├── parking/             # Парковка, стыковка
│   ├── drill_nano/          # Nanobot Drill
│   └── ...
├── docs/                    # Документация
│   ├── agent-playbook/      # Готовые команды (для операторов)
│   ├── agent-dev/           # Разработка (этот файл)
│   ├── workflows/           # Описания пайплайнов
│   └── agent-skills/        # Скиллы для Hermes
├── tests/                   # Тесты
└── AGENTS.md                # Главный индекс
```

---

## Ключевые файлы

| Файл | Описание |
|---|---|
| `ARCHITECTURE.md` | Архитектура проекта |
| `docs/API_REFERENCE.md` | API библиотеки secontrol |
| `docs/DEVICE_REFERENCE.md` | Справочник устройств (драйверы) |
| `docs/EXAMPLES.md` | Каталог примеров |
| `docs/design-docs/index.md` | Дизайн-решения |
| `docs/exec-plans/tech-debt-tracker.md` | Технический долг |

---

## Как подключиться к гриду

```python
from secontrol.common import prepare_grid, close, resolve_owner_id

grid = prepare_grid("agent1")  # имя грида или ID
print(grid.name, grid.grid_id, grid.owner_id)

# Найти устройство
from secontrol.devices.ore_detector_device import OreDetectorDevice
radar = grid.get_first_device(OreDetectorDevice)

# Найти несколько устройств
devices = grid.find_devices_by_type("cockpit")

close(grid)
```

---

## Как найти устройство

```python
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# Первое устройство типа
radar = grid.get_first_device(OreDetectorDevice)

# Все устройства типа
devices = grid.find_devices_by_type(OreDetectorDevice)
```

---

## Как получить позицию корабля

```python
from secontrol.tools.navigation_tools import get_world_position

for dev_type in ["cockpit", "remote_control"]:
    devices = grid.find_devices_by_type(dev_type)
    if devices:
        devices[0].update()
        pos = get_world_position(devices[0])
        if pos:
            print(f"Position: {pos}")  # (x, y, z)
```

---

## RadarController — сканирование

```python
from secontrol.controllers.radar_controller import RadarController

ore_ctrl = RadarController(
    radar,
    ore_only=True,       # пропустить Stone
    radius=1000,          # радиус скана
    cell_size=10.0,       # размер ячейки
    boundingBoxY=1000,
)

solid, metadata, contacts, ore_cells = ore_ctrl.scan_voxels()
```

---

## SharedMapController — общая память

```python
from secontrol.controllers.shared_map_controller import SharedMapController

sm = SharedMapController(
    owner_id=grid.owner_id,
    chunk_size=100.0,
    storage_backend="redis",
)
sm.load()

# Записать руды
sm.add_ore_cells(ore_cells, save=True)

# Прочитать известные руды
known = sm.get_known_ores(material="Platinum")

# Записать позицию корабля
sm.add_remote_position(remote_device)
```

---

## SpaceNavigatorController — навигация

```python
from secontrol.controllers.space_navigator_controller import SpaceNavigatorController

controller = SpaceNavigatorController(grid_name="agent1")
result = controller.navigate_to((100000.0, 5000.0, -200000.0))
controller.close()
```

---

## Конвенции кода

- **Импорты**: `from secontrol.common import prepare_grid, close`
- **Пути**: абсолютные, от корня проекта
- **Временные файлы**: только в `tmp/`
- **Тесты**: `pytest tests/`
- **Сборка**: `python -m build`

---

## Добавление нового скрипта

1. Разместить в `examples/organized/<категория>/`
2. Использовать `prepare_grid()` / `close()` для подключения
3. Добавить в `docs/agent-playbook/PLAYBOOK.md` если скрипт для операторов
4. Добавить в `AGENTS.md` в соответствующий раздел

---

## Тестирование

```bash
# Все тесты
pytest tests/

# Конкретный тест
pytest tests/test_radar_controller.py

# С логированиом
pytest tests/ -v --log-cli-level=INFO
```

---

## Env переменные

```
REDIS_USERNAME     # from outenemy.ru/se
REDIS_PASSWORD     # from outenemy.ru/se
SE_OWNER_ID        # Space Engineers owner ID
SE_PLAYER_ID       # Player ID (falls back to owner)
```

Файл `.env` в корне проекта.
