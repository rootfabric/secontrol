# Worker Deployment Guide — запуск своих скриптов на se-worker

Эта инструкция — для разработчиков, которые хотят **запустить свой Python-скрипт** на воркере через `WorkerApiClient` для конкретного грида.

Готовый пример, на котором всё отлажено: запуск `examples/space_flight/orbit_earth.py` для `skynet-scout2` — артефакты в `tmp/orbit_earth_app.py`, `tmp/orbit_earth_p1..p4.py`, `tmp/run_orbit_earth_app.py`.

---

## 1. Архитектура воркера

```
[твой runner] --(WorkerApiClient)--> [se-worker-controller]
                                              |
                                              v
                                       [executor в контейнере]
                                       ├── подтягивает WORKER_PARAMS
                                       ├── создаёт App(**params)
                                       ├── вызывает app.start()
                                       └── в цикле вызывает app.step()
```

- `WorkerApiClient` — тонкая обёртка над REST API воркер-контроллера (`WorkerApi.py`).
- **executor воркера** — фиксированный раннер: он НЕ запускает `python filename.py`, а импортирует файл как модуль и работает только с классом `App`.
- Все файлы программы попадают в `/app/workspace/` контейнера.
- В этом же контейнере **уже установлен пакет `secontrol`** (`pip install secontrol`). Используй `from secontrol...` напрямую.
- Сетевые ресурсы воркера ограничены: `git clone github.com` падает с `server certificate not trusted` / `Empty reply from server` — рассчитывай на предустановленный `secontrol`, а не на git pull.

---

## 2. Минимальный App-адаптер

Exector ищет в залитом файле **класс `App` с методами `__init__(params)`, `start()`, `step()`**. `def main()` не подхватывается.

```python
# /app/workspace/orbit_earth_app.py
from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any, Dict


class App:
    def __init__(self, params: Dict[str, Any]):
        self.params = dict(params)
        print(f"[app] params: {json.dumps(self.params, ensure_ascii=False)}", flush=True)
        # ... сюда кладём всю тяжёлую подготовку ...
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        # запускаем long-running процесс
        with self._lock:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", "/app/workspace/your_script.py", *self._argv()],
                cwd="/app/workspace",
                stdout=sys.stdout,        # важно: чтобы вывод шёл в лог воркера
                stderr=subprocess.STDOUT,
            )

    def step(self) -> None:
        # вызывается executor'ом периодически (по умолчанию раз в секунду)
        with self._lock:
            proc = self._proc
        if proc is None:
            print("[app] step() before start()", flush=True)
            return
        rc = proc.poll()
        if rc is None:
            print(f"[app] still running pid={proc.pid}", flush=True)
        else:
            print(f"[app] exited rc={rc}", flush=True)
```

**Что важно:**
- `flush=True` на каждом `print` — executor собирает stdout построчно.
- `stdout=sys.stdout` в `Popen` — иначе вывод дочернего процесса не попадёт в лог.
- `subprocess` лучше, чем `runpy.run_path` — `__file__` будет правильный, `sys.path` не сломается.
- Если скрипт короткий (несколько секунд) и не требует loop — `start()` может сам всё сделать, `step()` просто логирует.

---

## 3. Pipeline: create → upload → run

```python
from WorkerApi import WorkerApiClient

client = WorkerApiClient(timeout=120.0, max_retries=3, retry_delay=2.0)

# 1) Создать или найти программу
PROGRAM_NAME = "my_grid_my_task"
programs = client.get_programs() or {}
program_uuid = next(
    (p.get("uuid") for p in programs.get("items", [])
     if p.get("name") == PROGRAM_NAME),
    None,
)
if not program_uuid:
    created = client.create_program(PROGRAM_NAME)
    program_uuid = created["uuid"]

# 2) Залить файлы (важно: см. раздел 4 про лимиты)
for path in files:
    upload_with_retry(client, program_uuid, path)

# 3) Запустить
run = client.run_program(
    program_uuid=program_uuid,
    filename="entry.py",                # имя entry-файла в воркере
    grid_id="skynet-mygrid",            # label или числовой ID
    params={
        "grid": "skynet-mygrid",        # для App: явное имя грида
        # ... остальные параметры скрипта ...
    },
)

# 4) Подождать и прочитать логи
import time; time.sleep(10)
logs = client.get_program_logs(program_uuid, tail_bytes=20000)
print(logs)
```

Exector добавляет в `params` два поля автоматически:
- `grid_id` — числовой ID грида (`77390311078309731`), подставляется из binding воркера.
- `grid_label` — строковый label (`skynet-scout2`).

Если хочешь, чтобы скрипт работал на гриде, отличном от binding воркера, **передавай явный `params["grid"]` или `params["grid_label"]`**, а в App читай его с приоритетом:

```python
grid = (
    params.get("grid")
    or params.get("grid_label")
    or "skynet-default"
)
```

---

## 4. Upload: лимиты и workaround'ы

Воркер-контроллер **обрывает multipart upload ~10KB+** (RemoteDisconnected) и сохраняет файл 0 байт. Retry через `WorkerApiClient.upload_files` не помогает — файл уже записан, второй раз не пишется. Сервер также:
- Принимает **только `.py` файлы** (`Only .py files are allowed` для `.gz`/`.txt`).
- Принимает **только POST** на `/programs/{uuid}/files` (нет PUT/raw-body endpoint).
- Поддерживает **только один файл на POST** (multipart с одним полем `files`).

Надёжный workaround, проверенный на `examples/space_flight/orbit_earth.py` (29.5KB):

```python
import requests

def upload_with_retry(client: WorkerApiClient, program_uuid: str, name: str, content: bytes) -> bool:
    url = f"{client.api_url}/programs/{program_uuid}/files"
    files = {"files": (name, content, "text/x-python")}
    headers = {"Connection": "close"}
    for attempt in range(5):
        try:
            with requests.Session() as s:        # <-- НЕ переиспользуем сессию
                r = s.post(url, files=files, headers=headers, timeout=180)
            if 200 <= r.status_code < 300:
                return True
            print(f"  attempt {attempt+1}: HTTP {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            print(f"  attempt {attempt+1}: {type(exc).__name__}: {exc}")
        time.sleep(2.0)
    return False
```

**Три правила, без которых ничего не зальётся:**
1. **`Connection: close`** в headers — иначе воркер закрывает keep-alive и второй upload падает.
2. **Новая `requests.Session()` на каждый файл** — переиспользование сессии между файлами ведёт к RemoteDisconnected.
3. **Retry с задержкой 2 сек** — некоторые файлы проходят с 2-3 попытки, даже если 7.5KB.

**Скрипты больше ~10KB** надо резать на куски. Сделай так:
- В `App.__init__` собери куски обратно в один файл через `Path.write_text()`.
- Каждый кусок залей как отдельный `.py` (например, `script_p1.py`, `script_p2.py`).

```python
PARTS = ["script_p1.py", "script_p2.py", "script_p3.py"]

def assemble() -> str:
    chunks = [
        Path("/app/workspace", p).read_text(encoding="utf-8")
        for p in PARTS
    ]
    target = "/app/workspace/script.py"
    Path(target).write_text("".join(chunks), encoding="utf-8")
    return target
```

Готовый split'ер: `tmp/split_orbit.py` (режет по строкам, выравнивает по `\n`).

---

## 5. Параметры воркера и env

Exector передаёт в `App.__init__` JSON из `WORKER_PARAMS`. Туда попадает:
- Всё, что ты положил в `params=...` в `run_program(...)`.
- Плюс автодобавленные `grid_id` (числовой) и `grid_label` (строка) из binding воркера.

Проверить, какие параметры реально дошли, можно в `App.__init__`:
```python
print(f"[app] WORKER_PARAMS: {json.dumps(self.params, ensure_ascii=False)}", flush=True)
```

`App.step()` вызывается executor'ом с интервалом `--interval` (по умолчанию 1.0 сек). Не делай в нём тяжёлую работу — это hot loop.

---

## 6. Чек-лист перед запуском

- [ ] У грида есть **Remote Control** с активным управлением (иначе `orbit_earth.py` и другие flight-скрипты упадут на `prepare_grid`).
- [ ] Воркер имеет binding к нужному гриду (`/api/programs/running` покажет `grid_label`). Если нет — передавай `grid_id` явно через `params["grid_id"]`.
- [ ] Скрипт ≤ 10KB → заливай одним файлом. > 10KB → режь на куски по 7-8KB.
- [ ] `print(..., flush=True)` во всех логах.
- [ ] В `App.__init__` поднят `secontrol` (через `import secontrol`) — иначе будет `ModuleNotFoundError`.
- [ ] Скрипт **не делает `git clone`** — воркер не может достучаться до github.com.
- [ ] Скрипт не пишет в `sys.path` через `os.path.dirname(__file__)/../..` — он окажется в `/app/workspace`, родитель = `/`. Используй `subprocess.Popen` с `cwd=/app/workspace` вместо `runpy.run_path`.
- [ ] Проверь `get_program_logs` через 10-15 сек после `run_program`. Если только `[executor] one-time execution completed, stopping` — App-класс не подхватился, проверь `class App` в файле.

---

## 7. Диагностика: что смотреть

| Симптом | Причина | Что делать |
|---|---|---|
| `[executor] one-time execution completed, stopping` | Нет класса `App` в entry-файле | Переименуй `main()` → `class App` с `__init__/start/step` |
| `[executor] secontrol already installed, skipping upgrade` — и сразу `one-time execution completed` | `App.__init__` бросил exception | Смотри traceback в `get_program_logs` (он попадает в лог через stderr) |
| `orbit_earth finished` в каждом `step()` | `runpy.run_path` сразу завершился (сломал sys.path) | Замени на `subprocess.Popen` с `cwd=/app/workspace` |
| `RemoteDisconnected` на upload | Много файлов в одной сессии или большой файл | `Connection: close` + новая `Session()` на файл + retry |
| Файл 0 байт после upload | Multipart отвалился на середине, retry не помог | Разрежь скрипт на куски по 7-8KB, заливай по одному |
| `400: программа не найдена` на `run_program` | Старая программа ещё `running` или файл не залит нормально | `client.stop_program(uuid)`, проверь `list_program_files` |
| `400: Only .py files are allowed` | Заливаешь `.gz`/`.txt`/`.json` | Переименуй в `.py` или встрой как строку в `.py` |
| Корабль стоит, `laps=0`, `err` растёт | RC autopilot не активирован или thrusters off | В скрипте вызови `rc.handbrake_off(); rc.thrusters_on(); rc.gyro_control_on(); rc.set_mode("oneway"); rc.autopilot_enable()` |
| `grid_label: skynet-scout1` вместо `skynet-scout2` | Воркер имеет binding к другому гриду | Передавай `params["grid"]` явно, в скрипте читай с приоритетом `params["grid"]` > `params["grid_label"]` |

---

## 8. Шаблон «запустить мой скрипт на гриде»

Скопируй `tmp/orbit_earth_app.py` и `tmp/run_orbit_earth_app.py` и замени:

```python
# в orbit_earth_app.py (App-адаптер):
PARTS = ["my_script_p1.py", "my_script_p2.py"]   # если режешь
SCRIPT_NAME = "my_script.py"
# build_argv() — какие аргументы передать скрипту
# start() — что запускать (subprocess или прямой код)
```

```python
# в run_orbit_earth_app.py (runner):
PROGRAM_NAME = "mygrid_my_task"
ENTRY_FILE = "my_script_app.py"
PARTS = ["my_script_p1.py", "my_script_p2.py"]
ENTRY_SOURCE = WORKSPACE / "tmp" / ENTRY_FILE
PART_SOURCES = [WORKSPACE / "tmp" / p for p in PARTS]
TARGET_GRID_LABEL = "skynet-mygrid"
RUN_PARAMS = {
    "grid": TARGET_GRID_LABEL,
    # ... параметры ...
}
```

Готовые враппы из `examples/organized/worker/` (Blink, lamp_blink_rover, dock_to_dronebase) используют тот же `App` контракт — посмотри их, если нужен другой шаблон (например, `step()` не через subprocess, а через постоянное обновление состояния).

---

## 9. Связанные файлы

- `examples/organized/worker/WorkerApi.py` — клиент REST API воркера
- `examples/organized/worker/example_app_params.py` — минимальный App-адаптер
- `examples/organized/worker/01_lamp_blink.py` — реальный `App` с `step()` loop
- `examples/organized/worker/scout2_orbit_earth.py` — старый `def main()` адаптер (НЕ совместим с executor'ом, см. раздел 2)
- `tmp/orbit_earth_app.py` — рабочий App-адаптер для `orbit_earth.py` со сборкой из частей
- `tmp/run_orbit_earth_app.py` — полный pipeline runner
- `tmp/upload_via_requests.py` — пример `upload_with_retry` с `Connection: close`
- `docs/API_REFERENCE.md` — API `secontrol` (для `App.start`/step)
- `docs/agent-dev/DEVGUIDE.md` — общая архитектура и подключение к гриду
