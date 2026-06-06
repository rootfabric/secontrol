# GUI / Визуализация — для человека

Этот документ — карта всех скриптов и приложений проекта, которые что-то **рисуют на экране**:
3D-визуализация вокселей/руд, веб-дашборды, десктопные окна на PySide6. Сгруппировано по
назначению, чтобы человек мог быстро найти «как посмотреть» на состояние игры или работу
скриптов, не копаясь в коде.

> **Не для автоматизации.** Эти инструменты запускаются вручную (или по желанию агента),
> чтобы человек увидел результат. Для headless-пайплайнов они не нужны.

---

## Содержание

- [Веб-дашборд (флот)](#веб-дашборд-флот)
- [3D-визуализация радара (PyVista)](#3d-визуализация-радара-pyvista)
- [Десктопные GUI на PySide6](#десктопные-gui-на-pyside6)
- [Что выбрать](#что-выбрать)

---

## Веб-дашборд (флот)

### `start_fleet_dashboard.bat`
**Запуск:** `start_fleet_dashboard.bat` (двойным кликом или из PowerShell)

Поднимает локальный веб-сервер **SE Fleet Dashboard** на `http://localhost:8081`.
Браузерный интерфейс, читает данные из Redis (телеметрия гридов, игроки, загрузка устройств).

- **Для кого:** оператор, который хочет «открыть в браузере и посмотреть, что происходит».
- **Зависимости:** Redis (REDIS_URL и пр.), Python-окружение с установленным `secontrol`.
- **Где код:** `src/secontrol/fleet_dashboard/` (server.py, redis_reader.py, статика во `static/`).

---

## 3D-визуализация радара (PyVista)

Все скрипты ниже используют **PyVista** — открывают интерактивное 3D-окно с сеткой
вокселей, рудами (цвет по типу), контактами (гриды, игроки) и позицией корабля.

### `radar_voxel_visualization.py` — базовая визуализация
**Запуск:** `python examples/organized/radar/basic/radar_voxel_visualization.py`
**Где:** `examples/organized/radar/basic/radar_voxel_visualization.py:721`

Один скан радара → 3D-окно. Solid-камень показан **только внешней оболочкой** (wire-линии
по граням), внутренние вокселы скрыты — чтобы не «зашумлять» картинку. Руды выводятся
полностью, цветом и подписью по типу. HUD в углу: число точек, типы руд, контакты.

- **Когда использовать:** быстро посмотреть, что радар видит вокруг корабля.
- **Что внутри:** `extract_solid`, `build_occ_grid`, `build_ore_grids`,
  `add_solid_outer_envelope_mesh`, `visualize_colored_ores`.

### `radar_ore_then_voxels.py` — два прохода скана
**Запуск:** `python examples/organized/radar/basic/radar_ore_then_voxels.py`
**Где:** `examples/organized/radar/basic/radar_ore_then_voxels.py:426`

Делает **два прохода** радара:
1. `ore_only=True` — приоритетный сбор руд.
2. `ore_only=False` — полная геометрия (камень + руды).
3. Плюс отдельный **contacts-only** скан, чтобы не потерять игроков.

Результат мёрджится, отображается как solid-оболочка (через проверку 6-соседей) и
цветные руды. Показывает число связных регионов камня (`find_connected_regions`).

- **Когда использовать:** когда надо увидеть **полную** картину месторождений рядом
  с кораблём, а не только то, что попало в один скан.
- **Особенности:** использует `merge_contacts` для дедупликации контактов.

### `radar_path_to_player_visualization.py` — A* путь к игроку
**Запуск:**
```bash
python examples/organized/radar/basic/radar_path_to_player_visualization.py
python examples/organized/radar/basic/radar_path_to_player_visualization.py --grid skynet-baza0
python examples/organized/radar/basic/radar_path_to_player_visualization.py --radius 1000 --cell-size 20
```
**Где:** `examples/organized/radar/basic/radar_path_to_player_visualization.py:360`

Сканирует вокселы, находит первого игрока из контактов, прокладывает **A*-путь**
через свободные ячейки (`secontrol.tools.radar_navigation.PathFinder` с
`PassabilityProfile`) и рисует его красной «трубкой» с жёлтыми точками-вейпоинтами.
Параметры пути: `--ship-radius` (инфляция препятствий), `--radius`, `--cell-size`,
опционально `--bbox-x/y/z`.

- **Когда использовать:** проверить, реально ли корабль долетит до игрока, и где пройдёт
  маршрут. Учесть наклон, ступеньки, обход камней.

### `radar_real_map_and_pathfinding.py` — реальный путь по реальной карте
**Запуск:** `python examples/organized/radar/advanced/radar_real_map_and_pathfinding.py`
**Где:** `examples/organized/radar/advanced/radar_real_map_and_pathfinding.py:1`

Более продвинутый пример: берёт радар, ориентацию грида, считает forward-вектор и
строит **реальный** путь (с учётом ориентации корабля) по реальным сканам.

- **Когда использовать:** когда `radar_path_to_player_visualization.py` мало и надо
  видеть, как корабль будет двигаться с учётом своего «носа».

### `radar_mock_map_and_pathfinding_test.py` — оффлайн-тест пути
**Запуск:** `python examples/organized/radar/advanced/radar_mock_map_and_pathfinding_test.py`
**Где:** `examples/organized/radar/advanced/radar_mock_map_and_pathfinding_test.py:1`

То же самое, что выше, но с захардкоженным набором точек из логов — без подключения к
игре. Удобно для отладки алгоритма `PathFinder`.

- **Когда использовать:** проверить работу A* без боевого радара, на синтетических данных.

### `load_and_visualize_map.py` — загруженная карта из Redis
**Запуск:** `python examples/organized/map/load_and_visualize_map.py`
**Где:** `examples/organized/map/load_and_visualize_map.py:1`

Подключается к гриду, загружает сохранённую карту из Redis через
`SharedMapController.load_region(...)`, даунсэмплит точки до `MAX_SOLID_POINTS = 2000`
и визуализирует через `RadarVisualizer`.

- **Когда использовать:** посмотреть, что накопил `shared_map_sync.py` за время
  патрулирования.

### `radar_visualizer.py` (модуль) — переиспользуемый визуализатор
**Где:** `src/secontrol/tools/radar_visualizer.py:20`

Класс `RadarVisualizer` с методом `visualize(solid, metadata, contacts, own_position, ore_cells)`.
Используется `load_and_visualize_map.py`. Если пишешь свой скрипт и нужен показ радара —
импортируй его, а не копируй код.

---

## Десктопные GUI на PySide6

### `telemetry_reader_gui.py` — монитор телеметрии в реальном времени
**Запуск:** `python -m secontrol.tools.telemetry_reader_gui`
**Где:** `src/secontrol/tools/telemetry_reader_gui.py:1`

Оконное приложение Qt, подписывается на Redis pubsub-каналы (`se.system.status`,
`se.system.load`, `se.telemetry.*`) и рисует структурированное дерево значений.
Вкладки: System Load, System Status, Telemetry. Обновления через дебаунс (100 мс),
чтобы UI не мигал.

- **Переменные окружения:** `REDIS_URL`, `REDIS_PORT`, `REDIS_DB`, `REDIS_USERNAME`,
  `REDIS_PASSWORD`. `.env` подхватывается автоматически.
- **Для кого:** посмотреть «прямо сейчас», что отдаёт плагин телеметрии из игры.

### `device_load_monitor_gui.py` — загрузка CPU устройств по гридам
**Запуск:** `python -m secontrol.tools.device_load_monitor_gui`
**Где:** `src/secontrol/tools/device_load_monitor_gui.py:1`

Окно с деревом (`QTreeWidget`): грид → устройства, сортировка по spentMs.
Показывает avg/peak CPU, отдельно update и commands. Кнопка Refresh. Кто видит
все гриды — определяется наличием `REDIS_ADMIN_USERNAME` / `REDIS_ADMIN_PASSWORD`
(иначе только гриды владельца из `REDIS_USERNAME`).

- **Для кого:** понять, какие устройства «жрут» процессорное время и где бот тупит.

### `gui_telemetry_viewer.py` — выбор грида/устройства + история
**Запуск:** `python examples/organized/basic/intermediate/gui_telemetry_viewer.py`
**Где:** `examples/organized/basic/intermediate/gui_telemetry_viewer.py:1`

PySide6-приложение: выпадающий список гридов → выпадающий список устройств →
подписка на телеметрию. Два поля: текущее состояние (JSON-слепок) и журнал
изменений (что поменялось, с таймстампом). Логи пишутся в `telemetry_gui.log`.
Пауза по `Ctrl+P`.

- **Переменные окружения:** `REDIS_URL`, `REDIS_USERNAME`, `REDIS_PASSWORD`,
  `SE_PLAYER_ID`, опционально `SE_GRID_ID`.
- **Для кого:** детально разобрать телеметрию конкретного устройства, посмотреть
  diff между обновлениями.

---

## Что выбрать

| Хочу… | Запустить |
|---|---|
| Открыть в браузере общий дашборд по флоту | `start_fleet_dashboard.bat` |
| Увидеть, что радар нашёл вокруг корабля (3D) | `python examples/organized/radar/basic/radar_voxel_visualization.py` |
| Увидеть руды + камень (двойной проход) | `python examples/organized/radar/basic/radar_ore_then_voxels.py` |
| Проверить A*-путь до игрока | `python examples/organized/radar/basic/radar_path_to_player_visualization.py` |
| Посмотреть накопленную карту из Redis | `python examples/organized/map/load_and_visualize_map.py` |
| Мониторить телеметрию в реальном времени (Qt-окно) | `python -m secontrol.tools.telemetry_reader_gui` |
| Понять, какие устройства грузят CPU | `python -m secontrol.tools.device_load_monitor_gui` |
| Разобрать телеметрию одного устройства с diff | `python examples/organized/basic/intermediate/gui_telemetry_viewer.py` |

---

## Зависимости

- **PyVista** — для всех 3D-скриптов (`pip install pyvista`).
- **PySide6** — для десктопных GUI.
- **Redis** (с переменными `REDIS_URL` и пр.) — для дашборда и всех GUI,
  читающих телеметрию.
- Сам **Space Engineers** с включённым плагином телеметрии и активным гридом —
  чтобы скан радара возвращал не пустоту.
