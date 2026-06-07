# Safe diagnostics before clarification

Этот playbook запрещает агенту останавливаться на уточняющих вопросах, если можно сначала выполнить безопасные read-only проверки.

Цель: агент должен уменьшать неопределённость фактами из игры и репозитория, а не уходить в бесконечное `нужно уточнить`.

---

## 1. Главное правило

Если запрос пользователя неполный, но безопасные проверки могут дать недостающие факты, сначала выполни эти проверки.

Безопасная проверка — это действие, которое не двигает грид, не меняет inventory, не включает destructive mining, не отстыковывает connector, не удаляет блоки и не телепортирует объекты.

Спрашивай пользователя только после safe diagnostics, если всё ещё осталось реальное решение, которое нельзя принять по default rules.

---

## 2. Разрешённые проверки без уточнения

Эти команды можно запускать до вопросов:

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py rover
python examples/organized/parking/check_docking_status.py --grid agent
python examples/organized/parking/check_docking_status.py --grid rover
python examples/organized/diagnostics/check_flight_ready.py agent
python examples/organized/diagnostics/check_flight_ready.py rover
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --help
python examples/organized/radar/shared_map/shared_map_report.py --grid agent
python examples/organized/radar/shared_map/shared_map_deposits.py --grid agent --material Stone --clusters --gps --limit 3
```

Если exact grid name неизвестен, сначала получи список гридов:

```bash
python examples/organized/grid/basic/list_grids.py
```

или:

```bash
python -c "from secontrol.common import get_all_grids; [print(f'{name} (ID: {gid})') for gid, name in get_all_grids()]"
```

---

## 3. Что нельзя делать без уточнения

Не запускай без подтверждения, если пользователь не дал достаточно контекста или default mission не подходит:

- добычу большого объёма;
- движение грида на существенную дистанцию;
- undock/dock;
- transfer cargo;
- admin teleport;
- delete/spawn;
- изменение блоков;
- conveyor drain/pull/push;
- длительную миссию, которая может оставить корабль далеко от базы.

Но запрет на destructive action не запрещает read-only diagnostics.

---

## 4. Ambiguous mining request rule

Для запросов вида `добыть 100 тонн камня`, `попробуй добыть Stone`, `надо добыть ресурс`, `ровер уже на базе?`:

1. Не запускай добычу сразу.
2. Не задавай вопросы сразу.
3. Сначала выполни safe diagnostics:
   - resolve candidate grids from wording;
   - check `agent`, `rover`, `skynet-agent*`, `skynet-farpost0` if they are relevant;
   - check docking status;
   - check cargo capacity/current inventory;
   - check Nanobot Drill / drill system availability;
   - check whether mining script supports requested material through `--help` or code inspection;
   - check base default from mission docs.
4. Затем дай короткий факт-отчёт.
5. Если всё ещё нужен выбор — задай один конкретный вопрос.

Пример правильного поведения:

```text
Понял: пробуем добычу камня на agent, rover считаю стоящим на базе. Перед стартом 100 т не запускаю вслепую: сначала проверю agent/rover, cargo capacity, Nanobot Drill, docking и поддержку --ore Stone.
```

Пример неправильного поведения:

```text
Я не буду запускать ничего и задам уточняющие вопросы: какой корабль и какая база?
```

---

## 5. Default assumptions for secontrol missions

Если пользователь не указал явно иное, используй эти defaults как рабочую гипотезу для диагностики, не для destructive action:

| Context | Default for diagnostics |
|---|---|
| `agent` | проверить все гриды с именем `agent`, затем выбрать наиболее подходящий по cargo/devices/status |
| `rover` | проверить грид с именем `rover` или ближайшее совпадение |
| base | `skynet-farpost0` |
| ore collection base GPS | взять из `docs/agents-missions/se-ore-collection-mission.md` |
| mining script | `examples/organized/drill_nano/mine_ore_robot_safe_live_move.py` |
| status report | `docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py` |

Не превращай diagnostics defaults в молчаливое разрешение на добычу или полёт. Для destructive action нужен уверенный mission context или подтверждение пользователя.

---

## 6. Required report format after diagnostics

После safe diagnostics ответ должен содержать:

```text
Checked:
- grids: ...
- docking: ...
- cargo: ...
- mining devices: ...
- script support: ...
- blockers/warnings: ...

Decision:
- can start safely / cannot start yet / need one user decision

Question if needed:
- one concrete question
```

Не задавай 3-5 вопросов списком, если можно выбрать один следующий decision point.

---

## 7. Anti-patterns

Запрещённые формулировки до safe diagnostics:

```text
Стоит уточнить, какой корабль использовать.
Я не буду запускать ничего и спрошу.
Нужно понять, есть ли drill.
Нужно проверить cargo.
```

Разрешённая формулировка:

```text
Сначала проверю безопасно: grid status, docking, cargo, drill availability и script --help. После этого решу, нужен ли вопрос.
```
