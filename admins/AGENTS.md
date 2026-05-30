# Admin — Админский функционал игры

> Back to main index: `AGENTS.md`

Админские инструменты для управления сервером Space Engineers через Redis и Python.

---

## Что может делать админ

### Управление гридами

| Действие | Метод / скрипт | Описание |
|---|---|---|
| Спавн грида | `AdminUtilitiesClient.spawn_grid()` | Заспавнить корабль/станцию из XML |
| Удаление грида | `AdminUtilitiesClient.remove_grid()` | Удалить грид с сервера |
| Телепорт грида | `AdminUtilitiesClient.teleport_grid()` | Переместить грид в точку |
| Назначение грида фракции | `admins/ai_factions/admin_assign_or_remove_grid.py` | Привязать грид к AI-фракции |
| Спавн грида для фракции | `admins/ai_factions/admin_spawn_grid_for_faction.py` | Заспавнить грид от имени фракции |

### Управление блоками и вокселями

| Действие | Метод |
|---|---|
| Удалить блок | `AdminUtilitiesClient.remove_block()` |
| Апгрейд блока | `AdminUtilitiesClient.upgrade_block()` |
| Удалить воксель | `AdminUtilitiesClient.remove_voxel()` |
| Заполнить воксель | `AdminUtilitiesClient.fill_voxel()` |

### Коммуникация

| Действие | Метод / скрипт |
|---|---|
| Сообщение в чат | `AdminUtilitiesClient.send_chat_message()` |
| Mission screen | `AdminUtilitiesClient.show_mission_screen()` |
| Рассылка всем | `send_chat_message(msg, broadcast=True)` |
| Сообщение игроку | `send_chat_message(msg, player_id=...)` |

Скрипт: `admins/tools/send_chat_message.py`

### AI-фракции

| Действие | Скрипт |
|---|---|
| Создать фракцию + Redis ACL | `admins/ai_factions/admin_create_ai_faction_and_redis_user.py` |
| Закрыть/открыть вступление | `admins/ai_factions/admin_faction_join_policy.py` |
| Назначить/убрать grid | `admins/ai_factions/admin_assign_or_remove_grid.py` |
| Заспавнить grid для фракции | `admins/ai_factions/admin_spawn_grid_for_faction.py` |

Подробности: `admins/ai_factions/AGENTS.md`

---

## Быстрый старт

```python
from secontrol.admin import AdminUtilitiesClient

admin = AdminUtilitiesClient()
```

### Спавн корабля

```python
with open("ship.xml") as f:
    xml = f.read()

admin.spawn_grid(
    xml,
    position={"x": 1000, "y": 2000, "z": 3000},
    forward={"x": 0, "y": 0, "z": 1},
    up={"x": 0, "y": 1, "z": 0},
)
```

### Удалить грид

```python
admin.remove_grid(grid_id=123456)
```

### Телепортировать грид

```python
admin.teleport_grid(
    grid_id=123456,
    position={"x": 5000, "y": 6000, "z": 7000},
)
```

### Отправить сообщение в чат

```python
admin.send_chat_message("Всем привет!", broadcast=True)
```

---

## Env vars

| Variable | Purpose |
|---|---|
| `REDIS_URL` | Адрес Redis (default: `redis://127.0.0.1:6379/0`) |
| `REDIS_ADMIN_USERNAME` | Имя админ-пользователя Redis |
| `REDIS_ADMIN_PASSWORD` | Пароль админ-пользователя Redis |
| `SE_OWNER_ID` | Owner ID админа в SE |

---

## Архитектура

```
Python скрипты / AdminUtilitiesClient
  ↓ Redis pub/sub (se.commands)
SE Dedicated Server (плагин)
  ↓ Redis pub/sub (se.commands.ack)
Python скрипты (подтверждение)
```

Все админские команды проходят через `se.commands` pub/sub.
Плагин на сервере обрабатывает команды и шлёт ack в `se.commands.ack`.

---

## Ссылки

| Что | Где |
|---|---|
| AI Factions | `admins/ai_factions/AGENTS.md` |
| API Reference (AdminUtilitiesClient) | `docs/API_REFERENCE.md` |
| Workflows (Admin Operations) | `docs/WORKFLOWS.md` |
| Chat скрипт | `admins/tools/send_chat_message.py` |
