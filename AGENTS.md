# secontrol — Agent Index

Этот файл — главный вход для агента в репозитории `secontrol`.

Сначала выбери трек работы. Затем строго следуй соответствующему playbook. Не придумывай временные скрипты и пайплайны, если в репозитории уже есть готовая команда, mission или diagnostic script.

---

## Critical operating rules

### 1. Observe → command → verify

Любая команда управления гридом считается непроверенной, пока агент не увидел фактический результат в телеметрии.

Redis publish result, например `1 subscriber`, означает только наличие подписчика командного канала. Это не ACK от Space Engineers и не доказательство успешного выполнения команды.

После важных команд всегда делай read-after-write:

1. отправь команду;
2. подожди 1-3 секунды;
3. перечитай телеметрию;
4. проверь изменение состояния, скорости, позиции, inventory или connector status.

### 2. Safe diagnostics before clarification

Не заменяй безопасные read-only проверки уточняющими вопросами.

Если запрос пользователя неполный, но его можно уточнить фактами из игры или репозитория, сначала выполни безопасную диагностику, затем задай один конкретный вопрос только если решение всё ещё невозможно.

Разрешённые safe diagnostics, которые можно запускать без отдельного подтверждения:

- grid report;
- docking status;
- cargo/inventory status;
- device/block availability;
- script `--help`;
- SharedMap report;
- flight readiness report;
- поиск канонической mission/playbook команды в репозитории.

Нельзя останавливаться на фразе `I will ask clarifying questions` до этих проверок, если проверки безопасны.

Правильный паттерн:

```text
I will inspect agent/rover status, cargo capacity, Nanobot Drill availability, docking state, and script support first. Then I will ask only the missing decision if needed.
```

Неправильный паттерн:

```text
I will not run anything and will ask which ship/base to use.
```

Полный playbook: `docs/agent-playbook/SAFE_DIAGNOSTICS_BEFORE_CLARIFICATION.md`.

### 3. Flight diagnosis hard-block rule

Никогда не объявляй `fleet paralyzed`, `grid cannot fly`, `RC is impossible to enable`, `player offline hard-block` или аналогичный отказ только по статической телеметрии.

Эти признаки являются warning signals, но не hard blockers:

- `Remote Control enabled=false`;
- `Remote Control isFunctional=false`;
- `Remote Control isWorking=false`;
- `autopilotEnabled=false`;
- `player online=false`;
- `0 players online`;
- `Redis publish result = 1 subscriber`;
- generic `block_enable` не изменил RC telemetry;
- thruster subtype выглядит как atmospheric или unknown;
- hydrogen/fuel telemetry выглядит неполной или устаревшей.

Перед отчётом о невозможности полёта агент обязан выполнить guarded flight check или явно показать, почему его нельзя выполнить безопасно.

Минимальный guarded flight check:

1. Resolve target grid and Remote Control.
2. Check docking status.
3. If connected, do not thrust; undock only by the canonical parking playbook.
4. Send RC-specific commands, not only generic block enable:
   - `rc.handbrake_off()`;
   - `rc.thrusters_on()`;
   - `rc.gyro_control_on()`;
   - `rc.enable()`;
   - short `rc.goto(...)` or canonical navigator test.
5. Observe position and speed for 5-15 seconds.
6. If position changed or speed increased, the grid can move.
7. Only if command channel is absent or movement/speed stays zero after the guarded test, report a real blocker.

When in doubt, run the test. Do not replace the test with memory, assumptions, subtype guesses, or old failure patterns.

Full playbook: `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md`.

### 4. RC command path rule

For Remote Control blocks prefer the RC-specific device API and navigation scripts.

Do not conclude that RC is broken only because generic `block_enable` did not update `enabled=true`.

Preferred command path:

```text
rc.handbrake_off()
rc.thrusters_on()
rc.gyro_control_on()
rc.enable()
rc.goto(...)
```

or the canonical navigator:

```bash
python examples/space_flight/space_navigator_v5.py --grid agent1 --target="GPS:Name:X:Y:Z:" --max-speed 20 --far-speed 20 --medium-speed 10 --close-speed 3 --arrival 20
```

### 5. Thruster subtype rule

Do not decide that a grid cannot fly only from a thruster subtype string.

Subtype classification is advisory. The source of truth is measured movement:

- position delta;
- speed delta;
- successful navigator output;
- actual return-to-start or arrival result.

Known correction: small-grid `SmallBlockSmallThrust` may move a small grid in the current environment even when old memory says atmospheric thrust does not work in space.

### 6. Mission-first rule

If the user asks for a known operation, use the canonical mission or playbook first:

- ore collection: `docs/agents-missions/se-ore-collection-mission.md`;
- flight and navigation: `docs/agent-playbook/PLAYBOOK.md`;
- parking/docking: `examples/organized/parking/` commands;
- grid status: `docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py`;
- flight readiness: `examples/organized/diagnostics/check_flight_ready.py`.

Temporary scripts are allowed only when no canonical command exists or when the user explicitly asks for a new script.

---

## Ты оператор? (работаешь в игре)

Готовые команды. Копируй и запускай. Никакого кодирования без крайней необходимости для стандартных задач.

**→ `docs/agent-playbook/PLAYBOOK.md`**

- Навигация: обзор астероидов, полёты, парковка.
- Безопасная диагностика до уточняющих вопросов: `docs/agent-playbook/SAFE_DIAGNOSTICS_BEFORE_CLARIFICATION.md`.
- Диагностика полёта без ложного hard-block: `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md`.
- Добыча: скан руд, бурение, поиск месторождений.
- Строительство, производство, инвентарь.
- Мониторинг, управление устройствами.
- Стандартные пайплайны: разведка, добыча, рестарт.

---

## Ты админ? (управляешь сервером)

Спавн гридов, удаление, телепорт, чат, AI-фракции, управление блоками и вокселями.

**→ `admins/AGENTS.md`**

- Спавн/удаление/телепорт гридов.
- Управление блоками и вокселями.
- Сообщения в чат, mission screen.
- AI-фракции: создание, политика вступления, назначение гридов.
- AdminUtilitiesClient API.

Admin-доступ не должен использоваться как замена нормальной диагностики полёта или добычи, если пользователь не просил именно admin-операцию.

---

## Ты разработчик? (пишешь/правишь код)

Структура проекта, API, как добавлять устройства и скрипты.

**→ `docs/agent-dev/DEVGUIDE.md`**

- Архитектура проекта.
- Как подключиться к гриду.
- RadarController, SharedMapController, SpaceNavigatorController.
- Конвенции кода, тестирование.
- Справочники: API, устройства, примеры.

При правке scripts сохраняй принцип: command result is not execution proof. Навигационные скрипты должны проверять движение через position/speed delta. Миссионные скрипты должны отделять read-only diagnostics от destructive actions.

---

## Хочешь посмотреть? (GUI / визуализация)

Отдельный трек — для человека. 3D-визуализация радара, веб-дашборд флота, десктопные окна мониторинга телеметрии.

**→ `docs/agent-playbook/GUI_VISUALIZATION.md`**

- Веб-дашборд (`start_fleet_dashboard.bat`).
- 3D-визуализация радара: PyVista, вокселы, руды, A* пути.
- Десктопные GUI на PySide6: телеметрия, загрузка CPU.

---

## Временные файлы

Все временные файлы: сканы, бэкапы, промежуточные данные — в `tmp/` в корне проекта.

Не сохраняй mission-critical результат только в `/workspace/tmp`, если он нужен пользователю дальше. Дублируй важную инструкцию в репозиторный файл или явно сообщай путь.

---

## Ссылки

| Что | Где |
|---|---|
| Playbook операторов | `docs/agent-playbook/PLAYBOOK.md` |
| Safe diagnostics before clarification | `docs/agent-playbook/SAFE_DIAGNOSTICS_BEFORE_CLARIFICATION.md` |
| Flight diagnostic rules | `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md` |
| GUI / визуализация | `docs/agent-playbook/GUI_VISUALIZATION.md` |
| Admin | `admins/AGENTS.md` |
| Dev Guide | `docs/agent-dev/DEVGUIDE.md` |
| Missions | `docs/agents-missions/` |
| Workflows | `docs/workflows/` |
| API Reference | `docs/API_REFERENCE.md` |
| Device Reference | `docs/DEVICE_REFERENCE.md` |
| Examples | `docs/EXAMPLES.md` |
| Architecture | `ARCHITECTURE.md` |
| REPO Guide | `agent/REPO_GUIDE.md` |
