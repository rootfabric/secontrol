---
name: se-worker-control
description: Управление долгоживущими Python-программами на воркере (se-worker-controller). Создание, upload, запуск, логирование, остановка программ на гридах Space Engineers. Используй, когда нужно запустить скрипт на гриде (orbit, патруль, добыча, сканирование) и контролировать его выполнение удалённо.
---

# SE Worker Control — единая точка входа

Воркер (`se-worker-controller`) — это контейнер, который **выполняет твои Python-скрипты на указанном гриде**. Executor ищет в залитом файле класс `App` с методами `__init__(params)`, `start()`, `step()` и дёргает `step()` раз в секунду. Всё остальное — твоя забота: где взять грид, как дёрнуть RC, как напечатать в лог.

Этот skill даёт **один CLI** (`worker_cli.py`) и **один scaffold** (`app_scaffold.py`), чтобы не лазить каждый раз в `examples/organized/worker/create_and_run_scout2_orbit.py` и не писать обёртку руками.

---

## 1. CLI — семь команд

```bash
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py programs
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py files --program scout2_orbit
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py logs --program scout2_orbit --follow 5
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py upload --program scout2_orbit file1.py file2.py
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py run --program scout2_orbit --entry scout2_orbit_earth.py --grid skynet-scout2 --params '{"center_distance_km":90,"max_laps":0}'
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py stop --program scout2_orbit
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py create --program my_new_app
```

Ключевые флаги:
- `--instance-uuid` — UUID воркера. Обычно берётся из `SE_WORKER_INSTANCE_UUID` в `.env`.
- `--base-url` — адрес контроллера. По умолчанию `https://www.outenemy.ru/se/worker-controller`.
- `--program` — UUID программы, точное имя, или уникальная подстрока имени (например `scout2_orbit`).
- `--params JSON` — JSON-объект, который попадёт в `WORKER_PARAMS`. Также принимает `@path/to/file.json`.

Exit codes: `0` ok, `1` user error (нет грида/программы, битый JSON), `2` network/remote error, `3` worker error (upload/run reported failure).

---

## 2. Контракт `App` — что воркер реально ждёт

Exector берёт файл, импортирует его как модуль и ищет `class App`. `def main()` игнорируется:

```python
class App:
    def __init__(self, params: dict):
        # params — это то, что ты положил в --params
        # executor ещё добавляет grid_id (числовой) и grid_label (строка)
        ...

    def start(self):
        # вызывается один раз; тут тяжёлая инициализация
        ...

    def step(self):
        # вызывается executor'ом раз в секунду; НЕ делай тут тяжёлую работу
        # (это hot loop)
        ...
```

`step()` — это heartbeat, а не цикл скрипта. Если тебе нужно **долгое действие** (orbit, патруль, добыча), запускай его в `start()` через `subprocess.Popen` и просто пиши `print("[app] still running pid=...")` в `step()`. См. `examples/organized/worker/01_lamp_blink.py` для примера без subprocess и `docs/agent-dev/WORKER_DEPLOYMENT.md` для паттерна с subprocess.

---

## 3. Scaffold — адаптер из твоего скрипта за 30 секунд

У тебя есть свой скрипт (`examples/space_flight/orbit_earth.py`, новый `my_mining.py` и т.п.), который работает через CLI-флаги и `def main()`. Чтобы запустить его на воркере, scaffold сгенерирует готовый App-адаптер:

```bash
python docs/agent-skills/gaming/se-worker-control/scripts/app_scaffold.py \
  examples/space_flight/orbit_earth.py \
  --name orbit_earth_app.py \
  --param grid:str=skynet-scout2 \
  --param center_distance_km:float=90 \
  --flag max_laps:int=0 \
  --flag duration_sec:int=0 \
  --chunk-size 7500 \
  --out tmp/orbit_earth_app.py
```

На выходе:
- `tmp/orbit_earth_app.py` — адаптер (3-4 KB), который сам разбирает `WORKER_PARAMS` в argv.
- `tmp/orbit_earth_app.py_p1.py … _p4.py` — куски исходного скрипта, упакованные в `_part_N = "<repr()>"`. Каждый ≤7.5KB и валиден как `.py` (это требование воркер-контроллера).
- На стороне воркера `assemble()` склеивает куски обратно через `exec()` и записывает итоговый файл в `/app/workspace/`.

Поддерживаются:
- `--param NAME:TYPE=DEFAULT` — значение по умолчанию передаётся в argv, если в `WORKER_PARAMS` нет ключа `NAME`.
- `--flag NAME:TYPE=DEFAULT` — то же самое, но для value-флагов (например `--max-laps 0`).
- `--chunk-size N` — если скрипт больше `N` байт, разрезать на куски. По умолчанию — не резать (подходит для скриптов ≤10KB).

Scaffold покрывает ~80% случаев. Для остального — открой сгенерированный `App` и поправь `build_argv()` руками.

---

## 4. Полный pipeline (от скрипта до полёта scout2)

```bash
# 1. Сгенерировать адаптер + chunks
python docs/agent-skills/gaming/se-worker-control/scripts/app_scaffold.py \
  examples/space_flight/orbit_earth.py \
  --name orbit_earth_app.py \
  --param grid:str=skynet-scout2 \
  --param center_distance_km:float=90 \
  --param marker_step_km:float=5 \
  --flag max_laps:int=0 \
  --flag duration_sec:int=0 \
  --chunk-size 7500 \
  --out tmp/orbit_earth_app.py

# 2. Поднять или найти программу
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py \
  create --program scout2_orbit_earth_app   # один раз

# 3. Залить адаптер + chunks
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py \
  upload --program scout2_orbit \
  tmp/orbit_earth_app.py tmp/orbit_earth_app.py_p1.py tmp/orbit_earth_app.py_p2.py \
  tmp/orbit_earth_app.py_p3.py tmp/orbit_earth_app.py_p4.py

# 4. Запустить
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py \
  run --program scout2_orbit \
  --entry orbit_earth_app.py \
  --grid skynet-scout2 \
  --params '{"grid":"skynet-scout2","center_distance_km":90,"marker_step_km":5,"max_laps":0,"duration_sec":0}'

# 5. Смотреть логи
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py \
  logs --program scout2_orbit --follow 10 --interval 3

# 6. Остановить
python docs/agent-skills/gaming/se-worker-control/scripts/worker_cli.py \
  stop --program scout2_orbit
```

Реальный пример, который **только что отлетал scout2 по орбите 90 км вокруг EarthLike** в этом сеансе:
- Program: `scout2_orbit_earth_app` (uuid `ccdac6ec...`).
- Run: `57a237528e7242378c3ced80636f99dd`, status=running.
- Движение подтверждено: pos `(87807,−19743)` → `(89060,−9824)`, speed 0 → 145 м/с, `laps=0.014…0.076`, radius error всего −0.5 km от цели.

---

## 5. Главные грабли (без них ничего не взлетит)

1. **`App` обязателен.** Если в entry-файле только `def main()`, executor пишет `[executor] one-time execution completed, stopping` и тихо завершается. Никакого traceback.
2. **`print(..., flush=True)` на каждом логе.** Executor собирает stdout построчно. Без flush часть логов пропадёт.
3. **`stdout=sys.stdout` в `Popen`**, иначе вывод subprocess не попадёт в лог воркера.
4. **Скрипт ≤10KB → заливай одним файлом.** Больше — режь scaffold'ом с `--chunk-size 7500`. Без этого воркер-контроллер может оборвать multipart upload и сохранить файл нулевой длины.
5. **Передавай `params["grid"]` явно**, если хочешь запустить на гриде, отличном от worker binding. Executor дописывает `grid_id`/`grid_label` автоматически из binding, но App должен отдавать приоритет `params["grid"]` > `params["grid_label"]` (это уже зашито в scaffold).
6. **`grid_id` воркера ≠ grid_id грида.** В логах executor'а это `grid_label` (например `skynet-scout2`). Не перепутай.
7. **Воркер не может `git clone github.com`** (TLS / no network). Скрипт должен использовать уже установленный `secontrol`, а не тащить код из репы.
8. **`os.path.dirname(__file__)/../..` указывает в `/`** (файлы лежат в `/app/workspace`). Используй абсолютные пути или `cwd=/app/workspace` в subprocess, не строй `sys.path` через relative parents.
9. **`subprocess` лучше, чем `runpy.run_path`** — последний ломает `__file__` и `sys.path`, см. таблицу симптомов в `docs/agent-dev/WORKER_DEPLOYMENT.md:230`.
10. **`isFunctional=false` у RC ≠ нельзя летать.** Это сигнал, но не hard-blocker. Запускай guarded flight check (см. `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md`) перед отчётом о невозможности полёта.

---

## 6. Контроль исполнения

| Что смотреть | Команда |
|---|---|
| Какие программы залиты | `worker_cli.py programs` |
| Какая программа сейчас крутится | `worker_cli.py programs -r` |
| Содержимое программы (файлы) | `worker_cli.py files --program NAME` |
| Логи последнего/текущего запуска | `worker_cli.py logs --program NAME --tail-bytes 8000` |
| Лонг-рид логов | `worker_cli.py logs --program NAME --follow 10 --interval 3` |
| Остановить программу | `worker_cli.py stop --program NAME` |
| Создать новую программу | `worker_cli.py create --program NAME` |

`--follow N` опрашивает логи N раз с интервалом `--interval` (по умолчанию 2 секунды). Каждый раз печатается только новый хвост, не весь лог.

**Не доверяй факту успешного вызова.** `run` вернёт `{"status":"running","pid":...}` даже если скрипт упал в первую секунду. Всегда читай `logs` через 5-15 секунд и проверяй, что в логе появились ожидаемые сообщения (`[ORBIT] t=... laps=...`).

**Не доверяй `[executor] one-time execution completed, stopping`.** Это значит, что executor не нашёл `class App` в entry-файле. Проверь, что файл действительно залит (через `worker_cli.py files`) и содержит `class App`.

---

## 7. Шпаргалка по параметрам `orbit_earth.py`

Когда запускаешь через CLI scaffold:

| Параметр | Тип | Смысл |
|---|---|---|
| `grid` | str | label грида (например `skynet-scout2`) |
| `center_distance_km` | float | радиус орбиты от центра планеты (по умолчанию 90) |
| `marker_step_km` | float | шаг обновления GPS-маркера (по умолчанию 5) |
| `arc_km` | float | lead distance перед кораблём (по умолчанию 10) |
| `max_speed` | float | макс скорость autopilot (по умолчанию 500) |
| `max_laps` | int | `0` = unlimited (по умолчанию 0) |
| `duration_sec` | int | `0` = unlimited (по умолчанию 0) |
| `direction` | str | `ccw` или `cw` |
| `orbit_normal` | str | `x`, `y`, `z` |

`max_laps=0, duration_sec=0` = бесконечная орбита. Это уже дефолты — если их не передавать, orbit всё равно будет infinite.

---

## 8. Когда НЕ использовать этот skill

- **Краткая разовая команда** (parking, undock, mine once) → используй прямые вызовы через `secontrol.common.prepare_grid(...)` из обычного Python-скрипта. Воркер — это для **долгоживущих** задач.
- **Без интернета до воркер-контроллера** → всё, конечно, упадёт. Проверь `curl $SE_WORKER_BASE_URL`.
- **Скрипт требует git pull** → воркер не достанет до github. Положи зависимости рядом в `examples/...` и залей файлами.

---

## 9. Связанные файлы в репозитории

| Что | Где |
|---|---|
| Контракт воркера (полная спецификация) | `docs/agent-dev/WORKER_DEPLOYMENT.md` |
| Worker API клиент (Python SDK) | `examples/organized/worker/WorkerApi.py` |
| Готовые обёртки под конкретные скрипты | `examples/organized/worker/create_and_run_scout2_orbit.py`, `examples/organized/worker/run_orbit_earth_app.py` |
| Минимальный App-адаптер | `examples/organized/worker/example_app_params.py` |
| Реальный App c `step()` loop | `examples/organized/worker/01_lamp_blink.py` |
| `orbit_earth.py` (то, что крутится на scout2) | `examples/space_flight/orbit_earth.py` |
| Правила полёта без ложных hard-block | `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md` |