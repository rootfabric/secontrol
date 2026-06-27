---
name: se-grid-build-pipeline
description: End-to-end pipeline для постройки нового грида через проектор на базе: 1) поставить проекцию (prefab или blueprint) с правильными флагами для межгридной сварки; 2) включить сварку и сбросить WeldOptionFunctionalOnly (иначе merge блоки не сварятся); 3) дождаться завершения сварки; 4) включить merge блоки и коннекторы на новом гриде; 5) подготовить к отпарковке — разомкнуть merge блоки, отсоединить коннекторы, переименовать грид; 6) по команде оператора — отпарковать manual_thrust_undock. Использовать, когда оператор говорит "построй новый грид на базе", "запусти сборку через проектор", "свари новый корабль и отпаркуй", "новый корабль готов — отведи его".
---

# SE Grid Build Pipeline — постройка нового грида через проектор и его отпарковка

Этот скилл — **полный конвейер** от "поставить проекцию на проектор" до "новый грид уплыл от базы на безопасное расстояние". Каждый шаг — отдельный скрипт с пред-/пост-проверками. Шаги можно запускать по одному, не целиком.

Реальный кейс сессии, на котором отлажен конвейер: на `skynet-farpost0` стоит Projector, оператор грузит prefab маленького scout-корабля, дрон-Nanobot с ShipWelder сваривает его merge-блоками к базе; затем грид отвязывают и отгоняют на 30 м.

---

## 1. Pipeline (6 шагов)

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. setup_projection.py <grid> --prefab ... │ --blueprint-xml ...         │
│    Поставить проекцию, safe flags для межгридной сварки                  │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ 2. configure_welding.py <grid>                                            │
│    Включить ShipWelder'ы, WeldOptionFunctionalOnly=False                 │
│    (иначе merge блоки и структурные блоки не сварятся — тихая поломка)    │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ 3. wait_for_weld_complete.py <grid> [--timeout 600]                      │
│    Ждать, пока projectedGridName.remainingBlocks → 0                     │
│    Это занимает минуты — дрон сваривает медленно                          │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ 4. enable_merge_blocks.py <grid>  (из se-grid-creation)                  │
│    enable_connectors.py  <grid>  (из se-grid-creation)                    │
│    Включить merge блоки + коннекторы на новом гриде                      │
│    → ток потечёт через connected connector к новой подсетке               │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ 5. disable_merge_blocks.py <grid>  (из se-grid-creation)                 │
│    rename_new_grid.py --auto-new <new_name>                              │
│    connector.disconnect() + set_state(locked=False) на новом гриде        │
│    → новый грид теперь отдельный, со своим именем                        │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓
         (оператор подтверждает, что пора отходить)
                                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ 6. undock_new_grid.py <new_grid> [--distance 30] [--override 18]         │
│    manual_thrust_undock.py внутри: pre-check (battery/thrusters enabled),│
│    disconnect connector, импульсы тяги в reverse до дистанции             │
└──────────────────────────────────────────────────────────────────────────┘
```

Шаги 4–6 разделены намеренно: после шага 5 грид можно оставить висеть у базы (ещё не время уходить), а шаг 6 — только по явной команде оператора "отпаркуй".

---

## 2. Шаг 1 — `setup_projection.py`

Поставить blueprint или prefab на проектор с флагами, безопасными для сварки через границу гридов.

```bash
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/setup_projection.py \
    skynet-farpost0 \
    --prefab LargeGrid/StarterMiner
```

или с локальным blueprint:

```bash
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/setup_projection.py \
    skynet-farpost0 \
    --blueprint-xml blueprints/scout_v3.sbc \
    --scale 0.5 --offset 1 0 -2 --rotation 0 90 0
```

Что скрипт делает:
- Находит Projector (по `--projector-name`, иначе первый).
- Включает проектор (`set_enabled(True)`).
- Загружает источник проекции (`load_prefab` или `load_blueprint_xml`).
- Выставляет safe inter-grid флаги через `ProjectorDevice.set_flags`:
  - `instantBuild = False` — сварка идёт постепенно, merge-блоки спавнятся как реальные блоки.
  - `showOnlyBuildable = False` — оператор видит весь силуэт, включая блоки, требующие компонентов.
  - `keepProjection = True` — проекция не сбрасывается при load.
  - `projectionLocked = True` — проекция не ездит во время сварки.
  - `alignGrids = True` — выравнивание при кросс-грид сварке.
  - `useAdaptiveOffsets = True`, `useAdaptiveRotation = True`.
- Применяет опциональные `--scale / --offset / --rotation`.

Если забыть `instantBuild=False` или `alignGrids=True`, в некоторых конфигурациях merge-блоки "проваливаются" мимо merge-партнёра и сетка не слинкуется.

---

## 3. Шаг 2 — `configure_welding.py`

```bash
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/configure_welding.py skynet-farpost0
```

Что скрипт делает:
- Включает все `MyObjectBuilder_ShipWelder` (и `SurvivalKit` с built-in welder), которые выключены.
- На каждом вызывает `set_weld_functional_only(False)` — иначе в SE `WeldOptionFunctionalOnly` по умолчанию **True**, и сварщик **пропускает структурные блоки, включая Merge Blocks**.
- Verify через 2 с, печатает welders, требующие внимания.

Грабля из сессии: дрон-Nanobot сваривает 90 % проекции и уходит в idle, merge-блоки так и не появляются. Лечение — `WeldOptionFunctionalOnly=False`.

---

## 4. Шаг 3 — `wait_for_weld_complete.py`

```bash
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/wait_for_weld_complete.py \
    skynet-farpost0 --timeout 600 --poll-interval 5
```

Скрипт полит `remainingBlocks` у проектора и завершается на 0. По умолчанию таймаут 10 минут, опрос каждые 5 с.

Когда сварка завершена:
- `remainingBlocks = 0`
- `buildableBlocks = 0` (или совпадает с total)
- в `get_all_grids()` пока **не появится** новый id — merge ещё не залочен, новая подсетка пока часть проекции.

**Не путать завершение weld с готовностью к отвязке.** После завершения сварки проекция физически принадлежит базе, новые блоки ещё не merge-залочены. Переходи к шагу 4.

---

## 5. Шаг 4 — enable merge + connector на новом гриде

Merge блоки и коннекторы по умолчанию **выключены** после проекции — даже если они сварены. Без этого ток от базы не пойдёт и физического замыкания не будет.

```bash
# Merge блоки (по умолчанию --size small, чтобы не трогать LargeShipMergeBlock)
python docs/agent-skills/gaming/se-grid-creation/scripts/enable_merge_blocks.py skynet-farpost0 --size small

# Коннекторы (по умолчанию --size small)
python docs/agent-skills/gaming/se-grid-creation/scripts/enable_connectors.py skynet-farpost0 --size small
```

Оба скрипта в `se-grid-creation/scripts/`:
- `enable_merge_blocks.py` — симметричный к `disable_merge_blocks.py`.
- `enable_connectors.py` — симметричный, поддерживает `--size small|large|all`.

После выполнения **малые** merge блоки и коннекторы `enabled=True`. На большой сетке не трогаем — там могли быть свои, припаркованные корабли.

**Важно (merge ≠ power sharing):** даже если merge включён, ток пойдёт только при наличии **Connected connector** или прямой power-conveyor линии. Поэтому оба шага обязательны.

---

## 6. Шаг 5 — Detach: disable merge, disconnect connector, rename

```bash
# 1) Разомкнуть merge блоки → новая подсетка становится отдельным гридом,
#    скрипт печатает NEW GRID DETECTED с id.
python docs/agent-skills/gaming/se-grid-creation/scripts/disable_merge_blocks.py skynet-farpost0
# >>> Capture this id for rename: <NEW_GRID_ID>

# 2) Переименовать (по id или через --auto-new, который ловит "Static Grid 8052")
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/rename_new_grid.py \
    --auto-new skynet-scout6

# 3) Отсоединить коннектор на новом гриде — иначе он примагнитится обратно.
#    rename_new_grid уже отсоединяет в undock_new_grid.py, но если шаг 6 отложен,
#    сделай это явно:
python -c "
from secontrol.common import prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
g = prepare_grid('skynet-scout6')
for d in g.find_devices_by_type(ConnectorDevice):
    d.disconnect()
    d.set_state(locked=False)
print('connector disconnected')
"
```

После шага 5 грид — отдельный, со своим именем, и **висит вплотную к базе**. Это безопасно: merge уже разомкнут, коннектор разлочен. Но чтобы новый scout не путался под ногами у farpost0, шаг 6 отгоняет его.

---

## 7. Шаг 6 — `undock_new_grid.py` (по команде оператора)

```bash
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/undock_new_grid.py skynet-scout6
# или с другими параметрами:
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/undock_new_grid.py \
    skynet-scout6 --distance 50 --override 25
```

Что делает скрипт:
1. Pre-check: connector не `Connected`; иначе сам делает `disconnect()` + `set_state(locked=False)`.
2. Если батарея выключена (`auto-disabled после отстыковки`) — включает.
3. Если thrusters выключены — включает.
4. Запускает `examples/organized/parking/manual_thrust_undock.py <grid> <distance> <override>`.

Внутри `manual_thrust_undock.py`:
- Берёт `forward` коннектора → reverse.
- Серия `manual_thrust` импульсов (0.8 с × N, max 45 с) с `--override %`.
- Останавливается по дистанции или таймауту.
- `clear_thrust` + `dampeners_on`.

Реальная сессия: `skynet-scout6` 26 блоков, батарея auto-disabled, thrusters off → после auto-enable и одного импульса 0.8 с отошёл на **68.6 м** (запрошено 30).

---

## 8. Граблей (из реальной сессии)

### 8.1. `WeldOptionFunctionalOnly=True` — merge блоки не сварятся

`ShipWelder` по умолчанию варит **только functional** блоки. Merge Block, обычные cube-блоки, конвейеры — это **structural**, и они молча пропускаются. После полной проекции видишь "силуэт без merge-блоков" → нечего лочить → detach через `disable_merge_blocks.py` ничего не даёт.

**Лечение:** `set_weld_functional_only(False)` (см. `configure_welding.py`).

### 8.2. Battery auto-disabled после отстыковки

Когда merge разомкнут и новая сетка становится отдельным гридом, батарея на ней **авто-выключается** через 1-2 тика (игра видит, что нет power network, и отключает, чтобы не было петли). Thrusters без питания не дают тягу.

**Лечение:** `undock_new_grid.py` авто-enable батарею перед thrust. Если делаешь undock руками — не забудь.

### 8.3. Thrusters `SmallBlockSmallThrust` работают в космосе

Старая memory "atmospheric thrust не работает в space" — **неверна** в текущей среде. Source of truth — measured movement. По `FLIGHT_DIAGNOSTIC_RULES.md`:
> "small-grid `SmallBlockSmallThrust` may move a small grid in the current environment even when old memory says atmospheric thrust does not work in space."

### 8.4. Merge ≠ power sharing

Merge блок — это **механическое** замыкание, не electrical. Два слипшихся грида могут иметь две независимые power сети. Чтобы ток пошёл от farpost0 к новой сетке, нужен **Connected** connector или прямая cable-линия.

### 8.5. Redis publish result ≠ ACK

Любая команда возвращает `1 subscriber` от Redis — это **не доказательство**, что SE применил команду. Verify всегда через read-after-write: `time.sleep(2.5); prepare_grid(...); block.state.enabled`. Особенно критично для:
- `enable()` на battery — игра может re-disable через 1-2 тика.
- `connector.lock()` — состояние может прийти через несколько секунд.
- `grid.rename()` — telemetry лаг.

### 8.6. Динамические id после merge

Если ищешь блок по старому id после merge, его может не быть в `grid.blocks` — он перешёл в новую подсетку. Используй `name` или пересчитывай через `grid.devices`.

---

## 9. Минимальный скрипт-обёртка "всё в одном"

Если оператор хочет end-to-end одной командой:

```bash
GRID=skynet-farpost0
PREFAB=LargeGrid/StarterMiner
NEW_NAME=skynet-scout6

python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/setup_projection.py $GRID --prefab $PREFAB
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/configure_welding.py $GRID
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/wait_for_weld_complete.py $GRID --timeout 600
python docs/agent-skills/gaming/se-grid-creation/scripts/enable_merge_blocks.py $GRID --size small
python docs/agent-skills/gaming/se-grid-creation/scripts/enable_connectors.py $GRID --size small

# Дальше — только когда оператор скажет "готово, отвязывай":
python docs/agent-skills/gaming/se-grid-creation/scripts/disable_merge_blocks.py $GRID
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/rename_new_grid.py --auto-new $NEW_NAME

# Дальше — только когда оператор скажет "уведи его":
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/undock_new_grid.py $NEW_NAME
```

---

## 10. См. также

- `docs/agent-skills/gaming/se-grid-creation/SKILL.md` — диагностика "оживления" нового грида, источник `disable_merge_blocks.py`, `enable_merge_blocks.py`, `enable_connectors.py`.
- `docs/agent-skills/gaming/se-grid-status-report/SKILL.md` — `grid_report.py` для pre-flight / post-flight проверок.
- `docs/agents-missions/se-projector-clone-mission.md` — выравнивание проекции по merge↔connector (для сценариев, где проектор не на базе).
- `examples/organized/parking/manual_thrust_undock.py` — фактический undock-движок, используется `undock_new_grid.py`.
- `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md` — hard-block правила: `enabled=false` не равно "не летит".
- `docs/agent-playbook/PLAYBOOK.md` — общий операторский playbook.
- `src/secontrol/devices/projector_device.py` — `ProjectorDevice` API.
- `src/secontrol/devices/connector_device.py` — `ConnectorDevice` API.
- `src/secontrol/devices/merge_block_device.py` — `MergeBlockDevice` API.
- `src/secontrol/devices/ship_welder_device.py` — `ShipWelderDevice` API.
