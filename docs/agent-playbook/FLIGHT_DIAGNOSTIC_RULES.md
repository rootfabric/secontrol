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
```

Проверь:

- точное имя грида;
- grid id;
- позицию;
- скорость;
- массу/груз, если есть;
- Remote Control;
- thrust/battery/fuel summary.

### Step 2. Check docking status

```bash
python examples/organized/parking/check_docking_status.py --grid agent1
```

Если есть `Connected`, не делай thrust test. Сначала используй canonical undock:

```bash
python examples/organized/parking/smooth_undock.py agent1 skynet-farpost0 80
```

### Step 3. Run readiness check, but do not treat it as final proof

```bash
python examples/organized/diagnostics/check_flight_ready.py agent1
```

`NOT READY FOR FLIGHT` из этого скрипта — diagnostic signal. Перед финальным отказом всё равно нужна фактическая проверка движения, если она безопасна.

### Step 4. Prefer canonical navigator for movement proof

Для короткой проверки используй небольшую скорость и маленькую дистанцию. Цель должна быть свободной точкой, а не астероидом/базой.

```bash
python examples/space_flight/space_navigator_v5.py --grid agent1 --target="GPS:flight_check:X:Y:Z:#FF75C9F1:" --max-speed 20 --far-speed 20 --medium-speed 10 --close-speed 3 --arrival 20
```

Если готового скрипта теста в репозитории нет, допустим короткий RC-specific test через существующий API, но только как diagnostic script в `tmp/` или как уже утверждённый пример.

### Step 5. Verify movement

Считать грид способным двигаться, если выполнено хотя бы одно условие:

- position delta больше 2 м;
- speed больше 0.5 м/с;
- navigator явно сообщил прогресс к цели;
- грид вернулся к стартовой точке после теста.

Считать hard-block подтверждённым только если:

- команды были отправлены;
- subscriber был найден;
- прошло 5-15 секунд наблюдения;
- position delta меньше 2 м;
- max speed меньше 0.5 м/с;
- нет другого безопасного способа управления.

---

## 4. Correct reasoning template

Правильный отчёт:

```text
RC telemetry сейчас подозрительная: enabled=false, isFunctional=false.
Это warning, а не hard-block.
Проверил docking: не подключён.
Запустил guarded flight check через RC-specific commands / navigator.
За 10 секунд speed вырос до 20 м/с, position изменилась на 120 м.
Вывод: грид способен лететь. Старую telemetry не использовать как отказ.
```

Неправильный отчёт:

```text
RC enabled=false, online=false, publish=1 subscriber.
Это точная сигнатура player offline.
Fleet paralyzed. Скрипт не запускаю.
```

---

## 5. RC command path

Для Remote Control не делай вывод только по generic block enable.

Предпочтительный порядок:

```text
rc.handbrake_off()
rc.thrusters_on()
rc.gyro_control_on()
rc.enable()
rc.goto(...)
```

После каждой критической команды перечитывай телеметрию. Но финальный критерий — не поле `enabled`, а движение.

---

## 6. Thruster classification rule

Не называй двигатель нерабочим только по subtype.

Особенно запрещено:

```text
SmallBlockSmallThrust выглядит как atmospheric, значит в космосе не полетит.
```

Разрешено:

```text
Subtype выглядит подозрительно. Запускаю guarded movement test. Если speed/position изменились, считаю тягу рабочей в текущем окружении.
```

---

## 7. Final stop wording

Если после теста грид реально не двигается, пиши конкретно:

```text
Команды отправлены, subscriber есть, но за 15 секунд position delta=0.3 м и max speed=0.0 м/с. Грид не подтвердил движение. Следующий безопасный шаг: проверить питание/RC/массу/тягу или ручной bootstrap.
```

Не пиши:

```text
Игрок offline, значит ничего не работает.
```

Если flight check не запускался, обязательно напиши почему:

```text
Flight check не запускал: корабль пристыкован к базе, connector Connected. Сначала нужен smooth_undock.
```
