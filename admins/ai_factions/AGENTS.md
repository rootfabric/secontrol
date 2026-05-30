# AI Factions — Agent Instructions

> Back to main index: `AGENTS.md`

AI/NPC-фракции в Space Engineers с управлением через Redis и Python.

See also:
- `docs/agent-skills/gaming/game-server-automation/SKILL.md` — Redis monitoring and keyspace notifications
- `docs/agent-skills/gaming/secontrol-space-engineers/SKILL.md` — full secontrol SDK reference

## Архитектура

```
SE Dedicated Server (плагин AiFactionAdminService)
  ↕ Redis pub/sub (se.commands / se.commands.ack)
Redis (ACL-учётки, ключи se:{ownerId}:...)
  ↕
Python скрипты (админ-команды через pub/sub)
```

Каждая AI-фракция получает NPC identity с `ownerIdentityId`.
Все данные фракции хранятся в стандартном secontrol-namespace `se:{ownerIdentityId}:...`.
Redis ACL-учётка даёт доступ только к этому namespace.

## Env vars (обязательные)

| Variable | Purpose |
|---|---|
| `REDIS_URL` | Адрес Redis (default: `redis://127.0.0.1:6379/0`) |
| `REDIS_ADMIN_USERNAME` | Имя админ-пользователя Redis |
| `REDIS_ADMIN_PASSWORD` | Пароль админ-пользователя Redis |

Все скрипты читают `.env` через `dotenv`. Убедитесь, что переменные заданы.

## Скрипты

### 1. Создание фракции + Redis-учётки

`admin_create_ai_faction_and_redis_user.py`

Создаёт AI-фракцию в SE и параллельно создаёт Redis ACL-учётку
с доступом к `se:{ownerIdentityId}:*`.

```bash
python admins/ai_factions/admin_create_ai_faction_and_redis_user.py \
  --tag AIMN \
  --name "AI Miners" \
  --npc-name "AI Miners Core"
```

Параметры:
- `--tag` — тег фракции (по умолчанию AIMN)
- `--name` — отображаемое имя
- `--npc-name` — имя NPC core
- `--description` — описание фракции
- `--redis-username` — имя Redis-пользователя (default: `se_faction_<tag>_<ownerId>`)
- `--redis-password` — пароль Redis (генерируется если не указан)
- `--readonly` — создать read-only учётку

Вывод: JSON с `faction` (включая `ownerIdentityId`) и `redisUser` (включая пароль).

### 2. Назначение/удаление grid фракции

`admin_assign_or_remove_grid.py`

```bash
# Назначить grid фракции
python admins/ai_factions/admin_assign_or_remove_grid.py \
  --action assign --tag AIMN --grid-id 77469258998964669

# Удалить grid из фракции
python admins/ai_factions/admin_assign_or_remove_grid.py \
  --action remove --tag AIMN --grid-id 77469258998964669
```

### 3. Spawn grid из XML

`admin_spawn_grid_for_faction.py`

```bash
python admins/ai_factions/admin_spawn_grid_for_faction.py \
  --tag AIMN \
  --xml-file rover.xml \
  --grid-name "AIMN Rover 01" \
  --position 998506.9,91743.7,1595224.4
```

Позиция: `x,y,z` через запятую.
Опционально: `--forward x,y,z`, `--up x,y,z`.

### 4. Управление политикой вступления

`admin_faction_join_policy.py`

Закрытие AI-фракции от игроков:

```bash
# Закрыть фракцию, очистить заявки
python admins/ai_factions/admin_faction_join_policy.py \
  --tag AIMN --action close --clear-join-requests

# Закрыть + выгнать всех кроме AI owner
python admins/ai_factions/admin_faction_join_policy.py \
  --tag AIMN --action close \
  --clear-join-requests --kick-non-owner-members
```

Открытие:

```bash
# Открыть с ручным приёмом (без авто-принятия)
python admins/ai_factions/admin_faction_join_policy.py \
  --tag AIMN --action open \
  --accept-humans true --auto-accept-members false
```

Тонкая настройка:

```bash
python admins/ai_factions/admin_faction_join_policy.py \
  --tag AIMN --action set \
  --accept-humans false \
  --auto-accept-members false \
  --auto-accept-peace false
```

Действия: `close`, `open`, `set`, `clear-requests`, `kick-non-owner-members`.

## Полный цикл создания AI-фракции

```bash
# Шаг 1: Создать фракцию + Redis-учётку
python admins/ai_factions/admin_create_ai_faction_and_redis_user.py \
  --tag AIMN --name "AI Miners" --npc-name "AI Miners Core"
# → сохранить ownerIdentityId из вывода

# Шаг 2: Закрыть от игроков
python admins/ai_factions/admin_faction_join_policy.py \
  --tag AIMN --action close --clear-join-requests --kick-non-owner-members

# Шаг 3: Заспавнить корабль
python admins/ai_factions/admin_spawn_grid_for_faction.py \
  --tag AIMN --xml-file rover.xml --grid-name "AIMN Rover 01" \
  --position 998506.9,91743.7,1595224.4

# Шаг 4 (опционально): Назначить существующий grid
python admins/ai_factions/admin_assign_or_remove_grid.py \
  --action assign --tag AIMN --grid-id <GRID_ID>
```

## Redis ACL-структура

При создании фракции Redis ACL-учётка получает:

**Ключи:**
- `~se:{ownerId}:*` — все данные фракции
- `~se:{ownerId}:grids` — список гридов
- `~se:system:players:{owner}` — метаигрок
- `~se:system:ai_factions:{tag}` — метафракции

**Каналы:**
- `&se.{owner}.commands` — команды
- `&se.{owner}.commands.ack` — подтверждения
- `&se.commands.ack` — глобальные ack

## Redis команды (плагин)

Все команды отправляются через `se.commands` pub/sub:

| Action | Описание |
|---|---|
| `ai_faction_create` | Создать фракцию + NPC identity |
| `ai_faction_close` | Закрыть от вступления |
| `ai_faction_open` | Открыть вступление |
| `ai_faction_set_join_policy` | Тонкая настройка accept/auto-accept |
| `ai_faction_clear_join_requests` | Очистить заявки |
| `ai_faction_kick_non_owner_members` | Выгнать всех кроме NPC owner |
| `ai_faction_assign_grid` | Назначить grid фракции |
| `ai_faction_remove_grid` | Удалить grid из фракции |
| `ai_faction_spawn_grid` | Заспавнить grid из XML |

Формат команды:

```json
{
  "seq": 1234567890,
  "system": {
    "admin": {
      "action": "ai_faction_create",
      "tag": "AIMN",
      "name": "AI Miners",
      "npcName": "AI Miners Core"
    }
  }
}
```

## Модель безопасности

Два уровня защиты:

**Уровень 1 — SE фракция:**
- `AcceptHumans = false` — запрет вступления людей
- `AutoAcceptMember = false` — отключение авто-принятия
- Pending join requests — очищаются

**Уровень 2 — Redis ACL:**
- Доступ к `se:{ownerId}:*` выдаётся ТОЛЬКО через админскую команду
- Случайный игрок в SE-фракции НЕ получает Redis-доступ
- Каждая фракция — изолированный Redis namespace

## Типичные ошибки

- `REDIS_ADMIN_PASSWORD not set` — задайте переменную в `.env`
- `ConnectionRefusedError` — Redis недоступен, проверьте `REDIS_URL`
- `TimeoutError: No ack` — плагин не установлен на сервере
- `unknown_action` — плагин не поддерживает данную команду

## Зависимости

```
redis
python-dotenv
```

Установка: `pip install redis python-dotenv`
