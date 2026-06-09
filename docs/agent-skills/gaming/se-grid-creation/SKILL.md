---
name: se-grid-creation
description: Чек-лист и диагностика для "оживления" нового или пристыкованного грида: lock merge → заправка → enable_devices.py → аудит. Главные грабли из реальной сессии: неполный PASSIVE_TYPES, batteries auto-disabled на обесточенном гриде, merge ≠ power sharing, динамические id при объединении. Используй, когда оператор говорит "включи всё на новом корабле", "припарковал — а ничего не работает", "батареи не включаются", "грид слипся с фарпостом".
---

# SE Grid — чек-лист оживления нового/припаркованного грида

Этот скилл — **диагностическая надстройка** над `se-grid-enable-devices`. Содержит набор граблей, найденных в реальной сессии, и минимальный workflow, чтобы не залипнуть на "battery still OFF after verify".

---

## 1. TL;DR

```bash
# 1) Убедиться, что грид пристыкован / замержен / подключён
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py <grid>

# 2) Если грид новый и не слипся с базой — найти его
python docs/agent-skills/gaming/se-grid-find-by-name/scripts/find_grid.py <подстрока>

# 3) Запустить массовое включение
python docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py <grid>

# 4) Аудит: какие остались OFF и почему
python tmp/audit_post_enable.py   # one-off, не в репо — скопировать при необходимости
```

Если после шага 3 что-то осталось OFF — переходи к **разделу 4 (диагностика)**, не повторяй шаг 3 в цикле.

---

## 2. Workflow "оживления нового грида"

```text
0. Найти грид                       find_grid.py / grid_report.py
1. Проверить docking / merge        grid_report.py (ищет merge blocks и connectors)
2. Заблокировать merge blocks       игроком или через merge_block.enable() (если есть)
3. Заблокировать connectors         коннектор должен быть Connected
4. Заправить                         reactor: uranium, hydrogen tank: H2
5. enable_devices.py <grid>          массовый enable
6. Аудит                            см. ниже
7. Если есть OFF → раздел 4
```

Пункты 2-4 **обязательны**: `enable()` на батарее в обесточенном гриде вернёт `1` (ACK), но игра сама выключит её через 1-2 тика. Скрипт не сможет это распознать, если просто смотрит на `enabled`.

---

## 3. Главные грабли (из реальной сессии)

### 3.1. `enable_devices.py` не знает про некоторые типы

В `PASSIVE_TYPES` по умолчанию (`docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py:37`) **обязательно** должны быть:

| Тип | Что это | Источник |
|---|---|---|
| `battery` | Battery (все размеры) | `MyObjectBuilder_BatteryBlock` |
| `gas_tank` | H₂ tank, O₂ tank, OxygenFarm output | `MyObjectBuilder_OxygenTank` / `hydrogen_tank` |
| `solarpanel` | Solar panel | raw type из телеметрии (нет в normalize map) |
| `hydrogenengine` | H₂ engine | raw type из телеметрии (нет в normalize map) |
| `connector` | Connector (все) | `MyObjectBuilder_ShipConnector` |

**Что было сломано:** до этого сеанса `gas_tank`, `solarpanel`, `hydrogenengine` отсутствовали в `PASSIVE_TYPES`. Скрипт молча их пропускал → оператор думал, что "включил всё", а H₂-tank оставался OFF. Симптом: `enable_devices.py` отрапортовал "All ON", но `grid_report.py` показал OFF tank или солнечную панель.

**Признак в коде:** если блок не отнесён к PASSIVE/ACTIVE, он попадёт в раздел "Devices seen" с пометкой `?` и не тронется. Тип блока можно посмотреть через `dev.device_type` или `block.subtype`.

### 3.2. `OxygenTank` нормализуется в `gas_tank`, но не всегда

В `src/secontrol/base_device.py:1288` `oxygentank` → `gas_tank`. **Но** в момент сессии (исторический баг) некоторые `OxygenTank` блоки приходили с raw-типом `oxygentank` ДО нормализации, и `dev.device_type` был `oxygentank`, а не `gas_tank`. Поэтому в скрипте **добавлены оба** (`oxygentank` и `gas_tank`) — безопасно, ничего не ломает.

Сейчас код нормализует корректно (`gas_tank` достаточно), но `oxygentank` оставлен для совместимости.

### 3.3. Battery "включился" — игра не согласна

Сигнатура "на самом деле выключенной" батареи на обесточенном гриде:

```python
dev.telemetry == {
    "enabled": False,        # game re-disabled
    "functional": True,
    "isCharging": False,
    "currentInputMW": 0,     # нет притока мощности
    "currentOutputMW": 0,    # нет оттока (потому что выключена)
    "currentStoredPower": 0.9,   # MWh, в данной сессии 0.9 из 3
    "maxStoredPower": 3.0,
    "semiAuto": True,        # <-- не сбрасывается set_mode('auto')!
}
```

`Bridge.enable()` возвращает `1` (ACK успешно доставлен), но **игра выключает батарею обратно через 1-2 тика**, если на гриде нет излишка мощности. Скрипт `enable_devices.py` читает `enabled` через 2 секунды — иногда успевает, иногда нет. **Verify-таймер ненадёжен для batteries.**

**Корневая причина:** `semiAuto=True` (или "Auto" в GUI) — батарея не разряжается, но и не заряжается, если нет сети. Игра отдаёт приоритет питанию других блоков и выключает батарею, чтобы не было "петли" (battery feeds battery).

**Что делать:**

1. Проверить power grid: `grid_report.py` → `Power` / `Reactors` / `Batteries` / `Solars`.
2. Если реактор пустой → `reactor.inventory.amount(uranium) == 0` → **загрузить уран вручную или через `inventory_set`** (см. `src/secontrol/devices/reactor_device.py`).
3. Если солнечные панели не вырабатывают → грид не в зоне солнца / повреждены.
4. Если hydrogen tank пустой → 2.95% H₂, water ice не перерабатывается → заправить.
5. Если merge block разблокирован или коннектор не Connected → **грид питается автономно** от собственного пустого реактора.

**Только после этого** повторно запускать `enable_devices.py`.

### 3.4. `BatteryDevice.set_mode('auto')` НЕ сбрасывает `semiAuto`

```python
dev.set_mode('auto')  # returns 1, ничего не делает на самом деле
# dev.telemetry['semiAuto'] всё ещё True
```

Это известный баг/особенность: `semiAuto` — отдельный флаг, нет setter'а в bridge. Если грид запитан, батареи включатся и без этого.

### 3.5. Merge block ≠ power sharing

Два грида, **соединённые merge block + merge block** (locked), — это **один грид для физики**, но **может быть две независимые power-сети**, если между ними нет прямой линии электропитания или коннектора. Merge — механическое соединение, не электрическое.

**Симптом в сессии:** оператор заблокировал merge block'и, новый грид слипся с фарпостом (`Static Grid 1074` исчез из `get_all_grids()`), но батареи на новом гриде всё равно не заряжаются. Причина: между ними не было залоченного коннектора или прямой кабель-линии питания.

**Проверка:** для каждой пары merge-block ↔ merge-block проверить, что есть **и** merge lock, **и** connector Connected. В `grid_report.py` смотри секцию `Power` и `Mechanical Connections`.

### 3.6. Динамические id при объединении гридов

**Наблюдение из сессии:** батарея, которая была `id=81859832315928339` (`Battery 3`) на `skynet-farpost0`, после приварки и слияния оказалась `id=92705717168404175` (`Battery 3`) на `skynet-farpost0`. **id сменился без переименования.**

**Последствие:** любой код, который хардкодит id батарей/танков в `tmp/`-скриптах, **перестаёт работать** после merge. Всегда ищи по `name` или пересчитывай id через `grid.devices`.

```python
# Плохо (сломается после merge):
dev = grid.devices.get("81859832315928339")

# Хорошо (стабильно):
for did, dev in grid.devices.items():
    if dev.name == "Battery 3":
        ...
```

### 3.7. Reactor: `enabled=None, working=False, inventory=0`

У реактора **нет `enable()`**: `enabled` всегда `None` в телеметрии (это не toggle-устройство). Включается наличием урана в инвентаре.

```python
reactor = grid.devices[rid]  # device_type = "reactor"
print(reactor.telemetry.get("inventory"))  # -> [{type: "Uranium", amount: 0}]
```

**Что делать:** грузить уран вручную (игроком) или скриптом через `inventory_set`. `enable_devices.py` запускает `enable()` на реакторе — это no-op, но безвредно.

### 3.8. Duplicate device names

**Из сессии:** два блока с именем `Hydrogen Tank 2` на одном гриде (id 85941648201469532 и 126072844386138032). Возникло, видимо, при blueprint-проекции или ручном копировании. Поиск по `dev.name == "Hydrogen Tank 2"` возвращает оба.

**Что делать:** в `tmp/`-скриптах — итерировать `grid.devices.items()` с фильтром по типу и `filledRatio`/id, не по имени. В production-скриптах — добавить `id` в отчёт.

### 3.9. `maxOutputMW=0` = батарея электрически изолирована

**Сигнатура:**

```json
{
  "enabled": false,
  "currentInputMW": 0, "currentOutputMW": 0,
  "maxInputMW": 12, "maxOutputMW": 0,   // <-- ключевой признак
  "currentStoredPower": 0.9, "maxStoredPower": 3,
  "semiAuto": true, "isFunctional": true
}
```

`maxOutputMW=0` означает, что игра считает, что батарея **не может отдать мощность в сеть**, и поэтому `enable()` всегда откатывается через 1-2 тика. Соседняя батарея на той же сетке обычно показывает `maxOutputMW=12` (или равно `maxInputMW` для батарей этого размера).

**Корневая причина:** батарея находится на части грида, которая **механически слита** с основным гридом (через Merge Blocks / Projector), но **электрически изолирована** — нет power conveyor tube и нет залоченного коннектора между ними. В Space Engineers merge ≠ power sharing: физика объединяется, power network — нет.

**Что делать (in-game, скрипт не поможет):**

1. Найти физически, где стоит батарея (`grid.devices[bid].name` + in-game GPS).
2. Проверить, есть ли power conveyor tube (small/medium/large power tube), соединяющий эту часть с основной сеткой (там, где реакторы и работающие батареи).
3. Если нет — добавить power tube или коннектор + залочить оба.
4. Альтернативы: перенести батарею в основную сетку через инвентарь, или построить мини-реактор на изолированной части.

**Диагностика через bridge:**

- `grid.devices[bid].telemetry.get('maxOutputMW')` — если 0, изоляция.
- `grid.devices[bid].telemetry.get('gridId')` — **бесполезен**: bridge не различает subgrids, у всех блоков один `gridId` для механически слитого грида. Реальная развязка живёт в power network модели, которую bridge не экспортирует.
- `Connector` device telemetry **не содержит** `isConnected` / `isLocked` / `isConnectable` — нельзя через bridge узнать, какие коннекторы залочены и какие пары соединены. Можно только вслепую вызывать `connector.set_state(locked=True)` / `connector.connect()` и смотреть, изменился ли `maxOutputMW` у ближайших батарей.

**Подтверждение фикса:** после добавления power tube / лока коннектора в игре повторно прочитать `maxOutputMW` — должен измениться с `0` на `12` (или другое ненулевое значение, зависящее от размера батареи). Сразу после этого `enable()` будет держаться (см. раздел 3.3 — verify перестанет врать).

---

## 4. Диагностика "что осталось OFF после enable_devices.py"

### 4.1. Минимальный скрипт-аудит

Одноразовый скрипт `tmp/audit_post_enable.py` (уже есть в tmp/):

```python
from secontrol.common import prepare_grid
import time

grid = prepare_grid("skynet-farpost0")
time.sleep(2.0)

for did, dev in grid.devices.items():
    t = dev.telemetry or {}
    if t.get("enabled") is False and getattr(dev, "supports_enabled", True):
        print(f"  OFF: [{dev.device_type}] {dev.name} (id={did})")
        for k in ("functional", "isCharging", "currentInputMW",
                  "currentOutputMW", "semiAuto", "filledRatio"):
            if k in t:
                print(f"      {k} = {t[k]}")
```

### 4.2. Дерево решений

```
OFF после enable_devices.py
│
├─ functional=False → блок повреждён. Починить игроком.
│
├─ device_type=battery и currentInputMW=0
│  ├─ reactor.inventory=uranium=0 → загрузить уран
│  ├─ solar panels output=0 → нет солнца / грид в тени астероида
│  ├─ hydrogen tank filledRatio < 5% → заправить
│  ├─ merge block unlocked → залочить
│  └─ connector не Connected → подключить
│
├─ device_type=hydrogen_tank / oxygentank / gas_tank и filledRatio=0
│  └─ бак пустой → заправить (игра выключает пустые танки, экономит цикл обновления)
│
├─ device_type=reactor → это нормально (нет enable())
│
└─ functional=True, всё работает, но OFF через 2с после enable()
   └─ игра переопределяет. Проверить power grid ещё раз.
```

### 4.3. Чек-лист оператора

- [ ] Грид **запитан**? `grid_report.py` → power sources > 0 W total.
- [ ] Reactor имеет уран? `reactor.inventory` (см. `reactor_device.py`).
- [ ] Solar panels видят солнце? `solarpanel` device, `output` > 0.
- [ ] H₂ tank > 5%? `gas_tank.device`, `filledRatio`.
- [ ] Merge block **locked** (не `isConnected`, а именно `Locked`)?
- [ ] Connector **Connected** к базе?
- [ ] Если всё выше — да — и всё ещё OFF после 3-5 сек → баг в скрипте, см. раздел 3.1 (тип не в PASSIVE_TYPES).

---

## 5. Сводка: что добавилось в `enable_devices.py` за эту сессию

Diff в `docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py`:

```diff
 PASSIVE_TYPES: set[str] = {
     "battery",
     "connector",
     "thruster",
     "gyro",
     "sensor",
     "antenna",
     "beacon",
     "reactor",
     "lamp",
     "textpanel",
     "ore_detector",
     "parachute",
     "ai_behavior",
     "ai_recorder",
     "ai_flight_autopilot",
+    "oxygentank",
+    "gas_tank",
+    "solarpanel",
+    "hydrogenengine",
 }
```

Все четыре добавлены **без `--include-types`**, чтобы `python enable_devices.py <grid>` покрывал типовой случай "оживить всё на базе".

---

## 6. TODO: оформить как миссию

Когда появится задача автоматизировать "оживление" под ключ — вынести в `docs/agents-missions/se-grid-wakeup-mission.md`:

1. **Auto-fuel** — найти uranium / ice в cargo базы, загрузить в reactor / hydrogen engine.
2. **Auto-connect** — залочить merge blocks, подключить connectors между гридами и базой.
3. **Retry-with-power-check** — `enable_devices.py` в цикле, но с проверкой `currentInputMW > 0` или `currentStoredPower` растёт, а не просто `enabled`.
4. **Audit-and-report** — `audit_post_enable.py` как полноценный skill (`docs/agent-skills/gaming/se-grid-audit/`).
5. **Rename duplicates** — детектить `dev.name` с count > 1, предлагать переименование.

Сейчас всё это делается руками + `tmp/`-скриптами. Не автоматизировать, пока оператор не попросит — миссия из 5 шагов поверх ad-hoc workflow не нужна.

---

## 7. См. также

- `docs/agent-skills/gaming/se-grid-enable-devices/SKILL.md` — основной скрипт включения.
- `docs/agent-skills/gaming/se-grid-enable-devices/scripts/enable_devices.py:37` — `PASSIVE_TYPES` (здесь источник истины, что включается по умолчанию).
- `src/secontrol/base_device.py:807` — `set_enabled` Redis-канал и payload.
- `src/secontrol/devices/battery_device.py` — `BatteryDevice.set_mode`, signature методов.
- `src/secontrol/devices/reactor_device.py` — `ReactorDevice`, `inventory`.
- `src/secontrol/base_device.py:1240-1330` — `DEVICE_REGISTRY` (raw → normalized type mapping).
- `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md` — hard-block правила для полёта, не grid wakeup.
- `AGENTS.md:3` — "Flight diagnosis hard-block rule": `enabled=false` не означает "не летит", только warning.
- `tmp/investigate_h2_tank_v3.py` — реальный debug-скрипт из сессии (device_type=oxygentank).
- `tmp/investigate_static_grid.py` — реальный debug-скрипт Static Grid 1074.
- `tmp/audit_post_enable.py` — реальный debug-скрипт аудита после enable.
