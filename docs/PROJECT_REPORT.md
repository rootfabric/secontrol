# secontrol — Project Report

**Сгенерировано:** 2026-05-14
**Рабочая директория:** /workspace

---

## 1. Что это за проект

**secontrol** — это Python-библиотека для взаимодействия с сервером игры **Space Engineers** через Redis-шлюз (gateway).

> Space Engineers — космическая «песочница» от Keen Software House. На сервере запущен шлюз, который публикует телеметрию игры (состояние сеток, блоков, устройств) в Redis и принимает команды обратно. `secontrol` — высокоуровневый клиент поверх этого шлюза.

### Репозиторий
- **GitHub:** https://github.com/rootfabric/secontrol
- **PyPI:** `pip install secontrol`
- **Лицензия:** MIT
- **Версия:** 0.3.0
- **Python:** ≥ 3.9

---

## 2. Архитектура

```
Space Engineers game server
        │
        │ Redis pub/sub  (каналы se.<owner>.<channel>)
        ▼
RedisEventClient           ← низкоуровневый: publish, subscribe, keyspace notifications
        │
        ├── Grids           ← мониторит se:<owner>:grids → список сеток
        │     └── Grid     ← мониторит se:<owner>:grid:<id>:gridinfo → одна сетка
        │           └── BaseDevice (подклассы по типу блока)
        │
        ├── AdminUtilitiesClient  ← административные команды
        └── common.py helpers     ← prepare_grid(), resolve_*()
```

### Структура кода

| Модуль | Назначение |
|---|---|
| `redis_client.py` | Соединение, pub/sub, keyspace-уведомления, retry |
| `grids.py` | `Grids` (список сеток), `Grid` (состояние + устройства), `GridState`, `DamageEvent` |
| `base_device.py` | Базовый класс `BaseDevice`, `BlockInfo`, `DamageDetails`, реестр устройств |
| `devices/` | **30+** конкретных классов устройств (лампа, реактор, буст, дрон, турель…) |
| `controllers/` | Высокоуровневые контроллеры (Radar, Surface Flight, Shared Map) |
| `common.py` | `prepare_grid()`, `Grid.from_name()`, `close()` |
| `admin.py` | `AdminUtilitiesClient` — публикация admin-команд |
| `inventory.py` | `InventoryItem`, `InventorySnapshot` — типизированный инвентарь |
| `item_types.py` | `ItemType`, `ItemCategory` — enum-типы предметов |
| `tools/` | CLI/GUI утилиты (телеметрия, радар-визуализатор, редактор blueprint…) |
| `dashboard/` | FastAPI веб-панель мониторинга |

### Redis-каналы

| Паттерн | Назначение |
|---|---|
| `se:<owner>:grids` | Список сеток |
| `se:<owner>:grid:<id>:gridinfo` | Телеметрия одной сетки (keyspace notification) |
| `se:<owner>:grid:<id>:damage` | События урона |
| `se.<player>.commands.grid.<id>` | Исходящие команды на сетку |
| `se.commands.ack` | Acknowledge административных команд |

---

## 3. Устройства (30+ типов)

| Категория | Устройства |
|---|---|
| **Ходовые** | Thruster, Gyro, Wheel, Rover |
| **Оружейные** | Weapon, LargeTurret, Artillery, ShipGrinder, ShipWelder, ShipTool |
| **Двигательные** | ShipDrill, NanobotDrillSystem |
| **Энергия** | Reactor, Battery |
| **Ресурсы** | Refinery, Assembler, OreDetector, GasGenerator, ConveyorSorter |
| **Интерфейс** | Lamp, Display, Cockpit, RemoteControl, Projector |
| **Дocking** | Connector |
| **AI** | AIDevice |
| **Хранение** | Container, BuildAndRepair |
| **Радар** | RadarController (в controllers/) |

---

## 4. Установка и зависимости

Для последней опубликованной версии установите `secontrol` из PyPI:

```bash
pip install secontrol
```

Если нужны изменения, которые уже есть в Git-репозитории, но ещё не опубликованы в PyPI, установите библиотеку напрямую из GitHub:

```bash
pip install git+https://github.com/rootfabric/secontrol.git
```

Для локальной разработки склонируйте репозиторий и установите библиотеку в editable-режиме, чтобы локальные изменения кода применялись сразу:

```bash
git clone https://github.com/rootfabric/secontrol.git
cd secontrol
pip install -e .
```

Дополнительные варианты для разработки и веб-панели:

```bash
# Для разработки с dev-зависимостями
pip install -e ".[dev]"

# Для веб-панели
pip install -e ".[dashboard]"
```

**Основные зависимости:**
- `redis>=4.5` — клиент Redis
- `python-dotenv>=1.0` — чтение `.env`
- `numpy>=1.26`
- `tenacity>=8.0` — retry-логика
- `requests>=2.25`

**Опциональные:**
- `pytest>=7` (dev)
- `fastapi`, `uvicorn` (dashboard)

---

## 5. Примеры (examples/organized/)

Более 113 готовых скриптов, организованных по типу устройства и уровню сложности:

```
examples/organized/
├── basic/        — базовые операции
├── lamp/         — управление светом (3 уровня)
├── container/    — контейнеры и инвентарь
├── assembler/    — производственные линии
├── refinery/     — переработка руды
├── rover/        — управление роверами
├── display/      — экраны и текст
├── grid/         — сетки и ресурсы
├── ai/           — AI автоматизация
├── radar/        — радар и обнаружение
├── inventory/    — инвентарь
└── (и другие)
```

---

## 6. Переменные окружения

| Переменная | Назначение |
|---|---|
| `REDIS_USERNAME` | Имя пользователя для авторизации в Redis |
| `REDIS_PASSWORD` | Пароль для авторизации |
| `SE_OWNER_ID` | Owner ID (автоопределяется, если не задан) |
| `SE_PLAYER_ID` | Player ID (fallback = owner ID) |

> Значения берутся из личного кабинета: https://www.outenemy.ru/se/

---

## 7. Parking-подпроект

В репозитории есть модуль автопарковки (docking/parking) в `examples/organized/parking/lib/`:
- `parking.py`, `docking.py`, `final_park.py`, `calc_point.py`, `helpers.py`
- Судя по всему, реализует логику автоматической парковки/стыковки кораблей в Space Engineers

---

## 8. Тесты

```
tests/
├── test_basic.py
├── test_grid_blocks.py
├── test_grid_creation_time.py
├── test_inventory_interfaces.py
├── test_nanobot_drill_system_device.py
├── test_radar_controller.py
├── test_redis_performance.py
└── test_weapon_device.py
```

Запуск: `pytest tests/`

---

## 9. Резюме

| Аспект | Оценка |
|---|---|
| Назначение | Python SDK для Space Engineers (телеметрия + команды через Redis) |
| Стабильность | Alpha (v0.3.0), но покрыт тестами и примерами |
| Документация | README, ARCHITECTURE, AGENTS, wiki, 113+ примеров |
| Расширяемость | Entry points для плагинов, DEVICE_TYPE_MAP, controllers |
| Веб-панель | FastAPI dashboard (опционально) |
| Parking-модуль | Отдельная подсистема автопарковки |

**Итог:** `secontrol` — зрелая, хорошо структурированная библиотека с развитой экосистемой устройств, примерами и автоматизацией для Space Engineers.
