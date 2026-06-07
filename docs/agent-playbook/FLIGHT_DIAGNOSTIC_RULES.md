# Flight diagnostic rules — как не делать ложный отказ полёта

Этот playbook обязателен перед любым отчётом вида:

- `fleet paralyzed`;
- `grid cannot fly`;
- `RC cannot be enabled`;
- `player offline hard-block`;
- `thrusters do not work in space`;
- `script will not work, so I will not run it`.

Главное правило: агент не имеет права заменять фактический тест движения рассуждением по одному полю телеметрии.

---

## 0. Do not ask instead of testing

Если проверка безопасна, не заменяй её уточняющим вопросом.

Перед выводом `не полетит` или `не могу запускать` сначала выполни read-only diagnostics и, если безопасно, guarded flight check.

Если пользователь спрашивает `пробовать надо на агенте, а ровер уже на базе?`, это достаточно, чтобы проверить `agent` и `rover` read-only командами. Не останавливайся на вопросе `какой корабль использовать?` до проверки фактов.

---

## 1. Warning signals, not hard blockers

Следующие признаки не доказывают невозможность полёта:

| Признак | Правильная трактовка |
|---|---|
| `Remote Control enabled=false` | Блок может быть выключен, telemetry может быть stale, нужен RC-specific enable и проверка после команды. |
| `Remote Control isFunctional=false` | Это warning. Нужно проверить фактическое управление и движение. |
| `Remote Control isWorking=false` | Это warning. Не является доказательством, что `rc.enable()` не сработает. |
| `autopilotEnabled=false` | Нормальное состояние до включения автопилота. |
| `online=false` / `0 players online` | Не доказывает, что серверный bridge игнорирует команды. |
| `Redis publish result = 1 subscriber` | Означает только наличие подписчика. Это не ACK выполнения команды в игре. |
| generic `block_enable` не поменял RC | Для RC используй RC-specific command path. |
| subtype похож на atmospheric | Subtype не источник истины. Источник истины — движение. |
| нет H2 или мало топлива | Важно, но надо проверить тип тяги, батареи, массу и фактическое движение. |

---

## 2. Allowed hard blockers

Разрешено остановить миссию без flight test только если есть явный риск или физическая невозможность теста:

1. Грид пристыкован или connector status is `Connected`, а команда — не undock.
2. Грид находится внутри voxel/structure и короткий тест приведёт к столкновению.
3. Нет Remote Control и нет другого канонического контроллера движения.
4. Нет командного subscriber: Redis publish вернул `0 subscribers` для всех релевантных команд.
5. Телеметрия грида не обновляется вообще: нет position, speed, blocks или grid id.
6. Пользователь явно запретил двигать грид.

Даже в этих случаях отчёт должен говорить не `grid cannot fly`, а конкретную причину:

```text
Не запускаю flight check, потому что connector уже Connected. Сначала нужен canonical undock.
```

---

## 3. Required guarded flight check

Перед hard-block выполни безопасный короткий тест.

### Step 1. Resolve grid

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent1
python examples/organized/parking/check_docking_status.py --grid agent1
python examples/organized/diagnostics/check_flight_ready.py agent1
```

### Step 2. If docked, do not thrust

Если грид пристыкован:

```bash
python examples/organized/parking/check_docking_status.py --grid agent1
```

Если `Connected`, не делай thrust test. Используй canonical undock только когда mission требует полёта:

```bash
python examples/organized/parking/smooth_undock.py agent1 skynet-farpost0 80
```

### Step 3. Prefer canonical navigator for movement proof

Для короткого безопасного теста используй малую скорость и близкую цель, если есть свободное пространство:

```bash
python examples/space_flight/space_navigator_v5.py --grid agent1 --target="GPS:flight_check:X:Y:Z:" --max-speed 20 --far-speed 20 --medium-speed 10 --close-speed 3 --arrival 20
```

Если в репозитории есть dedicated test script, используй его вместо самописного кода.

### Step 4. Observe actual result

Проверяй:

- position delta;
- speed delta;
- distance to target;
- final drift;
- script output.

Успехом считается не `enabled=true`, а факт движения.

---

## 4. RC-specific command path

Для RC не делай вывод по generic `block_enable`.

Правильная последовательность при ручном API-тесте:

```text
rc.handbrake_off()
rc.thrusters_on()
rc.gyro_control_on()
rc.enable()
rc.goto(...)
```

После каждой важной команды:

```text
send command → wait 1-3s → read telemetry → compare state/speed/position
```

---

## 5. Report template

Если тест успешен:

```text
Flight check passed.
Grid moved X m, max speed Y m/s. RC telemetry was misleading/stale, so mission can proceed.
```

Если тест неуспешен:

```text
Flight check failed.
Commands published: ...
Subscribers: ...
Observed movement: 0 m
Observed speed: 0 m/s
Likely blocker: ...
Next safe step: ...
```

Если тест нельзя выполнить:

```text
Flight check skipped for safety.
Reason: connector Connected / no telemetry / no RC / user forbids movement.
Next safe step: ...
```

---

## 6. Known correction

Не используй старое правило `SmallBlockSmallThrust cannot move in space` как hard-block.

В текущем окружении был успешный тест small-grid scout с `SmallBlockSmallThrust`: 1 км вперёд, 1 км назад, стабильная скорость около 20 м/с, финальный drift около 0.1 м.

Это не доказывает, что любой атмосферный thruster всегда работает, но доказывает, что subtype string не может быть причиной отказа без теста.
