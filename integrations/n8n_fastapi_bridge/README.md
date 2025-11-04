# FastAPI мост для n8n и Space Engineers

Этот пример показывает, как развернуть небольшое FastAPI‑приложение, которое использует библиотеку `secontrol` и делает гриды Space Engineers доступными через удобные HTTP‑эндпоинты. n8n получает список гридов и устройств, читает телеметрию, а также отправляет команды на грид или конкретное устройство. Поверх этого подготовлены готовые схемы n8n, включая сценарий мигания лампочкой с одновременным выводом телеметрии.

## Возможности

- Авторизация пользователей и выдача Bearer‑токенов (можно аутентифицироваться JSON‑телом или Basic‑заголовком).
- Список всех гридов владельца: `GET /grids`.
- Список устройств грида: `GET /grids/{gridId}/devices` или общий список `GET /devices`.
- Детали и телеметрия устройства: `GET /grids/{gridId}/devices/{deviceId}` и `GET /grids/{gridId}/devices/{deviceId}/telemetry`.
- Отправка команд на грид и устройство: `POST /grids/{gridId}/command`, `POST /grids/{gridId}/devices/{deviceId}/command`.
- Готовые JSON‑схемы для n8n в каталоге [`n8n_workflows`](./n8n_workflows).

## Требования

```bash
pip install "fastapi>=0.111" "uvicorn[standard]>=0.23"
```

Библиотека `secontrol` уже находится в репозитории, поэтому дополнительных действий не требуется.

## Настройка пользователей

1. Скопируйте файл [`users.example.json`](./users.example.json) в `users.json` (это сделано по умолчанию) и пропишите собственные данные подключения.
2. Пароли указываются в виде SHA‑256 хэша. Получить его можно так:
   ```bash
   python - <<'PY'
   from integrations.n8n_fastapi_bridge.auth import hash_password
   print(hash_password("my-secret"))
   PY
   ```
3. Поля `owner_id` и `player_id` — это идентификаторы владельца/игрока Space Engineers. Если `player_id` не указан, используется `owner_id`.
4. Поля `redis_url`, `redis_username`, `redis_password` переопределяют параметры подключения к Redis (если не заданы, используются переменные окружения `REDIS_URL`, `REDIS_USERNAME`, `REDIS_PASSWORD`).

## Запуск сервиса

```bash
uvicorn integrations.n8n_fastapi_bridge.app:app --reload
```

После запуска проверяем здоровье сервиса:

```bash
curl http://localhost:8000/health
```

Получение токена (через JSON‑тело):

```bash
curl -X POST http://localhost:8000/login \
     -H 'Content-Type: application/json' \
     -d '{"username": "admin", "password": "adminpass"}'
```

Либо через Basic‑авторизацию (удобно для нод n8n):

```bash
curl -X POST http://localhost:8000/login \
     -H 'Authorization: Basic YWRtaW46YWRtaW5wYXNz'
```

## Эндпоинты

| Метод | Путь                                               | Описание |
| ----- | -------------------------------------------------- | -------- |
| `POST` | `/login`                                           | Выдача токена. Можно передать JSON или использовать Basic‑авторизацию. |
| `GET`  | `/me`                                              | Информация о текущем пользователе. |
| `GET`  | `/grids`                                           | Список гридов владельца. |
| `GET`  | `/grids/{gridId}/devices`                          | Устройства выбранного грида. |
| `GET`  | `/devices?grid_id=...`                             | Устройства конкретного грида или всех гридов. |
| `GET`  | `/grids/{gridId}/devices/{deviceId}`               | Краткая информация об устройстве. |
| `GET`  | `/grids/{gridId}/devices/{deviceId}/telemetry`     | Текущая телеметрия устройства. |
| `POST` | `/grids/{gridId}/command`                          | Отправка команды на уровень грида. |
| `POST` | `/grids/{gridId}/devices/{deviceId}/command`       | Отправка команды конкретному устройству. |

Все запросы (кроме `/health` и `/login`) требуют заголовка `Authorization: Bearer <token>`.

## Интеграция с n8n

В каталоге [`n8n_workflows`](./n8n_workflows) лежат три готовых сценария:

1. **`01-login-and-list-grids.json`** — минимальный пример. Ноды:
   - *HTTP Request* → `/login` (Basic credential `SE Grid Auth`).
   - *HTTP Request* → `/grids` (автоматически подставляет Bearer‑токен).
   - *Set* → формирует выпадающий список гридов через выражение `{{$node["Get Grids"].json.map(...)}}`.

2. **`02-list-devices.json`** — продолжение первого воркфлоу. После выбора грида запрашивает список устройств и фильтрует только лампы по `deviceType`. Внутри используется выражение `{{$json["gridId"]}}`, поэтому для смены грида достаточно выбрать новое значение в Set‑ноде.

3. **`03-blink-lamp-with-telemetry.json`** — полноценная схема мигания лампочки:
   - *Manual Trigger* / *Webhook* — запуск.
   - *HTTP Request* → `/login` (берёт логин/пароль из сохранённых Credential).
   - *HTTP Request* → `/grids` → выбор грида.
   - *HTTP Request* → `/grids/{gridId}/devices` → фильтр по лампам.
   - Цикл из двух HTTP‑нод: `/command` с `{"cmd": "enable"}` и `{"cmd": "disable"}` + *Wait* 500 мс.
   - После каждой команды — запрос `/telemetry`, выводящий текущее состояние лампы (в ноде *Function* данные логируются в execution data).

Импорт схемы:

1. В n8n нажмите `Import from File` и выберите нужный JSON.
2. Создайте Credential типа **HTTP Basic Auth** с именем `SE Grid Auth`, сохраните логин/пароль пользователя (например, `admin` / `adminpass`).
3. В ноде `Login to FastAPI` выберите созданный Credential — токен будет подставляться автоматически во все последующие HTTP‑запросы через выражение `={{'Bearer ' + $node['Login to FastAPI'].json['access_token']}}`.

## Мигание лампочки и телеметрия

Workflow `03-blink-lamp-with-telemetry.json` выполняет следующие шаги:

1. Запрашивает список устройств выбранного грида и находит лампу по `deviceType == "lamp"`.
2. В блоке `Split In Batches` выполняет цикл из N (по умолчанию 5) итераций:
   1. `POST /grids/{gridId}/devices/{deviceId}/command` с телом `{ "cmd": "enable" }`.
   2. `HTTP Request` → `GET /grids/{gridId}/devices/{deviceId}/telemetry` — сохраняет яркость, цвет и флаг `enabled`.
   3. `Wait` 500 мс.
   4. `POST .../command` с `{ "cmd": "disable" }`.
   5. Повторный запрос `/telemetry`.
3. На выходе воркфлоу в execution data появляются записи с последовательностью состояний лампы (можно отправить, например, в Telegram или написать в лог).

## Замечания

- Телеметрия парсится из ключей вида `se:<owner>:grid:<grid>:<device_type>:<device_id>:telemetry`. Если в момент запроса данных нет, сервис пытается прочитать ключ напрямую через `RedisEventClient.get_json`.
- При отправке команд поле `payload` из тела запроса автоматически прокидывается в сообщение Redis. Для устройств любые дополнительные поля также попадают в команду (через `command.command_dict()`).
- Авторизация выполнена как пример и хранит токены в памяти процесса. Для продакшена замените `TokenStore` на устойчивое хранилище (Redis, БД).
- Включена CORS‑политика `allow_origins=['*']`, чтобы ноды n8n могли обращаться к API из любого окружения.

## Проверка

Простейшая последовательность ручной проверки:

```bash
# 1. Получить токен
TOKEN=$(curl -s -X POST http://localhost:8000/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "adminpass"}' | jq -r '.access_token')

# 2. Список гридов
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/grids

# 3. Список устройств конкретного грида
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/grids/<gridId>/devices

# 4. Команда на лампу (пример)
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"cmd": "enable"}' \
  http://localhost:8000/grids/<gridId>/devices/<deviceId>/command
```

Эти команды удобно повторно использовать в Postman или в нодах n8n.

---

Если нужен дополнительный функционал (вебхуки для телеметрии, кеш токенов и т. п.), возьмите текущую структуру в качестве основы и расширяйте по своим требованиям.
