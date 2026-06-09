---
name: se-grid-creation
description: Чек-лист и диагностика для "оживления" нового или пристыкованного грида: lock merge → заправка → enable_devices.py → аудит. Плюс обратный путь "detach свежесваренного грида": disable_merge_blocks.py (печатает id нового грида) → connector.disconnect() → Grid.rename() → smooth_undock.py (универсальный хвост отсоединения от базы). Главные грабли из реальной сессии: неполный PASSIVE_TYPES, batteries auto-disabled на обесточенном гриде, merge ≠ power sharing, динамические id при объединении, Connector не имеет enable/disable. Используй, когда оператор говорит "включи всё на новом корабле", "припарковал — а ничего не работает", "батареи не включаются", "грид слипся с фарпостом", "отпаркуй свеже сваренный грид и переименуй".
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

### 1.1. Свежесваренный грид → отсоединить и переименовать

Когда новый грид приварен к базе через Merge block и его нужно отпарковать:

```bash
# 1) На базе выключить все Merge-блоки — это разрывает механический лок.
#    После этого в get_all_grids() появится новый id — СКОПИРУЙ ЕГО.
python docs/agent-skills/gaming/se-grid-creation/scripts/disable_merge_blocks.py skynet-farpost0

# 2) Отсоединить Connector на новом гриде (см. §3.2 — он держит после merge).
#    Без этого грид останется в статусе Connectable и может автопримагнититься.

# 3) Переименовать новый грид (id из шага 1).
python -c "from secontrol.common import prepare_grid; \
           prepare_grid(<NEW_GRID_ID>).rename('skynet-agent3')"

# 4) Стандартная расстыковка (универсальный хвост для любого отсоединения от базы).
python examples/organized/parking/smooth_undock.py skynet-agent3 skynet-farpost0 80
```

См. раздел **3 (Detach нового грида)** для полной версии и граблей.

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

## 3. Detach нового (свежесваренного) грида

Сценарий: оператор только что приварил merge-блоком к базе новый корабль/станцию, теперь нужно его отпарковать и переименовать.

### 3.1. Шаг 1 — disable merge blocks

`MyObjectBuilder_MergeBlock` имеет terminal On/Off: `disable()` через device-wrapper. После disable **механический лок разрывается**, и подсетка физически отделяется как самостоятельный грид — `get_all_grids()` сразу возвращает новый id.

Скрипт: `scripts/disable_merge_blocks.py <source_grid>`

```bash
python docs/agent-skills/gaming/se-grid-creation/scripts/disable_merge_blocks.py skynet-farpost0
```

Что делает:
1. Снапшот `get_all_grids()` ДО disable.
2. `disable()` на каждом enabled merge-блоке исходного грида.
3. Read-after-write 2.5 с + верификация `enabled=False`.
4. Снапшот `get_all_grids()` ПОСЛЕ disable.
5. Если block count упал → печатает id нового грида. **Скопируй его — он понадобится для rename и для отключения connector (шаг 2).**

**Важно:** имя нового грида в этот момент всегда дефолтное (`Static Grid <random>`). Не пытайся искать его "по имени" — у него ещё нет человеческого имени. Используй id, который напечатал скрипт.

### 3.2. Шаг 2 — отсоединить connector (если есть)

После disable merge block грид **механически свободен**, но если на стороне нового грида есть `MyObjectBuilder_ShipConnector` в статусе `Connected` к базе, он продолжает держать — `Connected` → `Connectable` после `disconnect()`. Без этого шага:

- Новый грид останется в радиусе действия коннектора базы (`status=Connectable` в `check_docking_status.py`).
- Может автопримагнититься обратно при любом движении базы.
- `Connector` device **не имеет** `enable()/disable()` (это `ConnectorDevice` → `set_state(locked=)` и `disconnect()`), см. `src/secontrol/devices/connector_device.py`.

Минимальный код (после шага 1):

```python
from secontrol.common import prepare_grid

g = prepare_grid("<NEW_GRID_ID>")
for dev in g.devices.values():
    if getattr(dev, "device_type", "") == "connector":
        if dev.is_enabled():
            dev.disconnect()                 # -> Connected/Connectable -> Unconnected
            dev.set_state(locked=False)      # разлочить на всякий случай
```

Проверка:

```bash
python examples/organized/parking/check_docking_status.py --grid <NEW_GRID_NAME_OR_ID>
# ожидаем: Unconnected, connected_to=None
```

### 3.3. Шаг 3 — переименовать

```python
from secontrol.common import prepare_grid
prepare_grid(<NEW_GRID_ID>).rename("skynet-agent3")
```

Verify:

```bash
python -c "from secontrol.common import get_all_grids; [print(f'{n} (ID: {g})') for g, n in get_all_grids()]"
# skynet-agent3 должен быть в списке, "Static Grid <...>" — нет.
```

### 3.4. Шаг 4 (опционально) — отогнать от базы

Если нужно, чтобы новый грид не висел в радиусе коннектора:

```bash
python examples/space_flight/space_navigator_v5.py --grid skynet-agent3 \
    --target="X,Y,Z" --max-speed 20 --far-speed 20 --medium-speed 10 --close-speed 3 --arrival 50
```

Перед этим проверить `check_docking_status.py` — `Unconnected`, иначе navigator не сможет двигать.

### 3.5. Стандартная расстыковка через `smooth_undock.py`

Это **универсальный хвост любого отсоединения от базы** (используется и для обычных кораблей, и для свежесваренных). `smooth_undock.py` — SAFE NOSE-THRUSTER UNDOCK: разрывает коннектор, даёт короткую тягу на носовые/отстыковочные движки без автопилота, отводит корабль от базы на заданную дистанцию. **Не зависит от того, как именно был отсоединён коннектор** (merge-block disable, manual `disconnect()`, или просто вручную в GUI).

```bash
python examples/organized/parking/smooth_undock.py <ship_id_or_name> <base_id_or_name> <distance>
```

Пример для типового detach-цикла:

```bash
python examples/organized/parking/smooth_undock.py skynet-agent3 skynet-farpost0 80
```

Аргументы:

| Позиция | Что | Пример |
|---|---|---|
| 1 | ship (id или имя) | `skynet-agent3` |
| 2 | base (id или имя) | `skynet-farpost0` |
| 3 | distance (м) — на сколько отвести | `80` |

ENV-переопределения (см. шапку скрипта):

- `SE_UNDOCK_PUSH_OVERRIDE=35` — нормальная тяга при отталкивании
- `SE_UNDOCK_EMERGENCY_OVERRIDE=70` — аварийная тяга, если корабль не сдвинулся
- `SE_UNDOCK_FORCE_NOSE=1` — принудительно использовать носовую группу движков
- `SE_UNDOCK_THRUSTER_IDS=id1,id2` — явный список id движков

**Когда использовать:** ВСЕГДА в конце detach-процедуры, после `connector.disconnect()` / `connector.set_state(locked=False)`. Это страховка от того, что новый грид останется висеть в радиусе коннектора базы и автопримагнитится обратно.

### 3.6. Граблей

- **block_id merge-блока исчезает из `grid.blocks` после detach** — это нормально, он перешёл в новый грид. Не ищи его по старому id.
- **`Connector` device нельзя выключить через `disable()`** — будет `NotImplementedError: ConnectorDevice does not expose a terminal On/Off switch`. Использовать `disconnect()` + `set_state(locked=False)`.
- **block count падает на ~100+** при отделении большого подсетка — это и есть сигнал, что detach произошёл. Если не упал — merge-блок либо не был enabled, либо не имел пары.
- **Connector со стороны базы можно не трогать** — он не держит грид сам по себе, держит только paired connector. После disconnect с одной стороны связь рвётся.
- **Connector on the BASE side может удерживать skynet-agent0** — не отключай "все коннекторы на farpost", это отстыкует и старый агент. Отключай только на стороне нового грида.

---

## 4. Главные грабли (из реальной сессии)

### 4.1. `enable_devices.py` не знает про некоторые типы

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

### 4.2. `OxygenTank` нормализуется в `gas_tank`, но не всегда

В `src/secontrol/base_device.py:1288` `oxygentank` → `gas_tank`. **Но** в момент сессии (исторический баг) некоторые `OxygenTank` блоки приходили с raw-типом `oxygentank` ДО нормализации, и `dev.device_type` был `oxygentank`, а не `gas_tank`. Поэтому в скрипте **добавлены оба** (`oxygentank` и `gas_tank`) — безопасно, ничего не ломает.

Сейчас код нормализует корректно (`gas_tank` достаточно), но `oxygentank` оставлен для совместимости.

### 4.3. Battery "включился" — игра не согласна

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

### 4.4. `BatteryDevice.set_mode('auto')` НЕ сбрасывает `semiAuto`

```python
dev.set_mode('auto')  # returns 1, ничего не делает на самом деле
# dev.telemetry['semiAuto'] всё ещё True
```

Это известный баг/особенность: `semiAuto` — отдельный флаг, нет setter'а в bridge. Если грид запитан, батареи включатся и без этого.

### 4.5. Merge block ≠ power sharing

Два грида, **соединённые merge block + merge block** (locked), — это **один грид для физики**, но **может быть две независимые power-сети**, если между ними нет прямой линии электропитания или коннектора. Merge — механическое соединение, не электрическое.

**Симптом в сессии:** оператор заблокировал merge block'и, новый грид слипся с фарпостом (`Static Grid 1074` исчез из `get_all_grids()`), но батареи на новом гриде всё равно не заряжаются. Причина: между ними не было залоченного коннектора или прямой кабель-линии питания.

**Проверка:** для каждой пары merge-block ↔ merge-block проверить, что есть **и** merge lock, **и** connector Connected. В `grid_report.py` смотри секцию `Power` и `Mechanical Connections`.

### 4.6. Динамические id при объединении гридов

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

### 4.7. Reactor: `enabled=None, working=False, inventory=0`

У реактора **нет `enable()`**: `enabled` всегда `None` в телеметрии (это не toggle-устройство). Включается наличием урана в инвентаре.

```python
reactor = grid.devices[rid]  # device_type = "reactor"
print(reactor.telemetry.get("inventory"))  # -> [{type: "Uranium", amount: 0}]
```

**Что делать:** грузить уран вручную (игроком) или скриптом через `inventory_set`. `enable_devices.py` запускает `enable()` на реакторе — это no-op, но безвредно.

### 4.8. Duplicate device names

**Из сессии:** два блока с именем `Hydrogen Tank 2` на одном гриде (id 85941648201469532 и 126072844386138032). Возникло, видимо, при blueprint-проекции или ручном копировании. Поиск по `dev.name == "Hydrogen Tank 2"` возвращает оба.

**Что делать:** в `tmp/`-скриптах — итерировать `grid.devices.items()` с фильтром по типу и `filledRatio`/id, не по имени. В production-скриптах — добавить `id` в отчёт.

### 4.9. `maxOutputMW=0` = батарея электрически изолирована

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

## 5. Диагностика "что осталось OFF после enable_devices.py"

### 5.1. Минимальный скрипт-аудит

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

### 5.2. Дерево решений

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

### 5.3. Чек-лист оператора

- [ ] Грид **запитан**? `grid_report.py` → power sources > 0 W total.
- [ ] Reactor имеет уран? `reactor.inventory` (см. `reactor_device.py`).
- [ ] Solar panels видят солнце? `solarpanel` device, `output` > 0.
- [ ] H₂ tank > 5%? `gas_tank.device`, `filledRatio`.
- [ ] Merge block **locked** (не `isConnected`, а именно `Locked`)?
- [ ] Connector **Connected** к базе?
- [ ] Если всё выше — да — и всё ещё OFF после 3-5 сек → баг в скрипте, см. раздел 3.1 (тип не в PASSIVE_TYPES).

---

## 6. Сводка: что добавилось в `enable_devices.py` за эту сессию

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

## 7. TODO: оформить как миссию

Когда появится задача автоматизировать "оживление" под ключ — вынести в `docs/agents-missions/se-grid-wakeup-mission.md`:

1. **Auto-fuel** — найти uranium / ice в cargo базы, загрузить в reactor / hydrogen engine.
2. **Auto-connect** — залочить merge blocks, подключить connectors между гридами и базой.
3. **Retry-with-power-check** — `enable_devices.py` в цикле, но с проверкой `currentInputMW > 0` или `currentStoredPower` растёт, а не просто `enabled`.
4. **Audit-and-report** — `audit_post_enable.py` как полноценный skill (`docs/agent-skills/gaming/se-grid-audit/`).
5. **Rename duplicates** — детектить `dev.name` с count > 1, предлагать переименование.

Сейчас всё это делается руками + `tmp/`-скриптами. Не автоматизировать, пока оператор не попросит — миссия из 5 шагов поверх ad-hoc workflow не нужна.

---

## 8. См. также

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
