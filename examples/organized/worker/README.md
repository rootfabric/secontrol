# WorkerApiClient: запуск программ с параметрами

Этот каталог предназначен для агента или локального скрипта, который управляет программами в web-worker через REST API контроллера.

## Переменные окружения

```bash
export SE_WORKER_BASE_URL="https://www.outenemy.ru/se/worker-controller"
export SE_WORKER_INSTANCE_UUID="28f8784e-dbe4-5f5e-b294-c1c87df4b712"
```

В PowerShell:

```powershell
$env:SE_WORKER_BASE_URL = "https://www.outenemy.ru/se/worker-controller"
$env:SE_WORKER_INSTANCE_UUID = "28f8784e-dbe4-5f5e-b294-c1c87df4b712"
```

## Минимальный запуск из Python

```python
from WorkerApi import WorkerApiClient

client = WorkerApiClient()
program = client.create_program("Drone test")
program_uuid = program["uuid"]

client.upload_files(program_uuid, ["example_app_params.py"])

run_info = client.run_program(
    program_uuid,
    "example_app_params.py",
    grid_id="127551744966766463",
    params={
        "speed": 25,
        "mode": "patrol",
        "target": "GPS:Home:0:0:0:#FF75C9F1:",
    },
)
print(run_info)
print(client.get_program_logs(program_uuid, tail_bytes=5000))
```

## Запуск готовым CLI

```bash
python worker_run_program.py \
  --program "Drone test" \
  --filename example_app_params.py \
  --grid-id 127551744966766463 \
  --params '{"speed": 25, "mode": "patrol"}'
```

Через файл параметров:

```json
{
  "speed": 25,
  "mode": "patrol",
  "target": "GPS:Home:0:0:0:#FF75C9F1:"
}
```

```bash
python worker_run_program.py \
  --program "Drone test" \
  --filename example_app_params.py \
  --grid-id 127551744966766463 \
  --params-file params.json
```

## Как параметры попадают в пользовательский код

При запуске воркер объединяет пользовательские параметры с системными ключами:

```python
{
    "speed": 25,
    "mode": "patrol",
    "grid_id": "127551744966766463",
    "grid_label": "rover"
}
```

Системные `grid_id` и `grid_label` всегда соответствуют выбранному гриду и не могут быть переопределены JSON-параметрами.

Классовый сценарий:

```python
class App:
    def __init__(self, params):
        self.grid_id = params["grid_id"]
        self.speed = float(params.get("speed", 10))

    def start(self):
        print(self.grid_id, self.speed)

    def step(self):
        pass
```

Одноразовый `main()` или простой скрипт:

```python
def main():
    print(params["grid_id"])
    print(params.get("speed", 10))
```

Также полный JSON доступен в окружении `WORKER_PARAMS`.
