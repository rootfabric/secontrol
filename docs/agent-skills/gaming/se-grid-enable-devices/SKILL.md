---
name: se-grid-enable-devices
description: Включить все (или только пассивные) устройства на указанном гриде. По умолчанию — батареи, коннекторы, солнечные/LCD-панели, двигатели, гироскопы, сенсоры, антенны, маяки, реакторы, лампы, оре-детекторы, AI-блоки. Сквады, нанобуры, оружие, туррели, верфи, ассемблеры, газогенераторы, колёса и проекторы по умолчанию пропускаются. Используй, когда нужно "оживить" корабль/базу после рестарта или ручного выключения.
---

# SE Grid — массовое включение устройств

Один проход `enable()` по всем подходящим устройствам грида + read-after-write проверка.

## 1. Самый быстрый путь — CLI

```bash
# Только пассивные устройства на гриде (по умолчанию)
python docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py skynet-agent0

# Сначала посмотреть, что будет сделано, без отправки команд
python docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py skynet-agent0 --dry-run

# Добавить к пассивным ещё и реакторы/туррели (явно)
python docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py skynet-agent0 --include-types reactor,large_turret

# Включить вообще всё, кроме оружия и буров
python docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py skynet-agent0 --all --exclude-types weapon,ship_drill

# Не делать read-after-write (быстрее, но без проверки)
python docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py skynet-agent0 --no-verify
```

Скрипт печатает таблицу устройств, шлёт `enable()` только тем, у кого сейчас `enabled=false`, ждёт `--verify-delay` секунд и перечитывает телеметрию. Если хоть одно устройство осталось OFF — exit code 1.

## 2. Что считается «пассивным»

`PASSIVE_TYPES` в `scripts/enable_devices.py`:

```
battery, connector, thruster, gyro, sensor, antenna, beacon,
reactor, lamp, textpanel, ore_detector, parachute,
ai_behavior, ai_recorder, ai_flight_autopilot
```

`ACTIVE_TYPES` (всегда пропускаются без явного `--include-types`):

```
ship_drill, ship_welder, ship_grinder, ship_tool,
nanobot_build_and_repair, nanobot_drill_system,
refinery, assembler, gas_generator, conveyor_sorter,
weapon, large_turret, interior_turret, artillery,
projector, wheel,
ai_offensive, ai_defensive, ai_move_ground,
remote_control, cockpit, container
```

`remote_control`, `cockpit`, `container` — `supports_enabled=False`, они в любом случае игнорируются скриптом.

## 3. Из Python — функция

```python
from secontrol.common import prepare_grid
from secontrol.base_device import BaseDevice

grid = prepare_grid("skynet-agent0")

for did, dev in grid.devices.items():
    if not getattr(dev, "supports_enabled", True):
        continue
    if dev.device_type in {"ship_drill", "weapon", "large_turret"}:
        continue
    if not dev.is_enabled():
        dev.enable()
```

Но удобнее через CLI — он сам фильтрует, шлёт пачками и верифицирует.

## 4. Как это работает

- Источник списка устройств: `grid.devices` — `Dict[str, BaseDevice]`, типизированный через `DEVICE_TYPE_MAP` в `src/secontrol/base_device.py:1240+`.
- `enable()` шлёт `{"cmd": "enable"}` в Redis-канал `se:{REDIS_USERNAME}:grid:{grid_id}:control`, см. `BaseDevice.set_enabled` в `src/secontrol/base_device.py:807`.
- После команды скрипт ждёт `verify-delay` (по умолчанию 2 с) и перечитывает `dev.is_enabled()` — это **read-after-write** по правилу из `AGENTS.md`. Redis publish `1 subscriber` НЕ считается доказательством: ждём подтверждения от телеметрии.
- Темп отправки команд — `--command-pace` (по умолчанию 20 мс между устройствами), чтобы не забивать Redis-канал.

## 5. Главные грабли

1. **Default = пассивные, не все.** Если нужен «включить вообще всё» (включая оружие и буры) — добавь `--all` и/или явные `--include-types`. Это сделано специально, чтобы случайно не подстрелить своих и не включить неисправный бур.
2. **`supports_enabled=False` блоки пропускаются молча.** RC, кокпит, контейнер не имеют терминального On/Off — для них есть отдельные device-API (`rc.handbrake_off()` и т.п.), см. `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md`.
3. **`enabled` иногда неизвестен** (телеметрия ещё не пришла). Такие устройства помечаются `?` и **не** трогаются. Это безопасный default: лучше пропустить, чем включить чужой блок.
4. **Verify может показать, что блок всё ещё OFF.** Это значит, что либо онлайн-блок повреждён (`is_damaged=True`), либо мост не успел отдать ACK. Перезапусти скрипт через 3-5 с или проверь грид через `grid_report.py`.
5. **Команда идёт пачкой.** Если у тебя 100+ устройств и задержка 2 с — общее время ≈ 100×0.02 + 2 = ~4 с. Это нормально, но не пытайся параллелить — `BaseDevice.send_command` использует общий Redis-канал.

## 6. Чек-лист оператора

- [ ] Не знаю точного имени грида → `python docs/agent-skills/gaming/se-grid-find-by-name/scripts/find_grid.py <подстрока>`.
- [ ] Хочу предварительно посмотреть, что включится → `--dry-run`.
- [ ] Хочу добавить конкретные типы к пассивному набору → `--include-types thruster,reactor`.
- [ ] Хочу вообще всё, кроме опасного → `--all --exclude-types weapon,large_turret,interior_turret,artillery,ship_drill,nanobot_drill_system`.
- [ ] Скрипт ругнулся `still OFF after verify` → проверь `grid_report.py`, возможно, повреждение или мост отвалился.
- [ ] Включаю оружие/туррели → `AGENTS.md: safe diagnostics before clarification`. Сначала убедись, что рядом нет своих.
