[← Parent skill: secontrol-space-engineers](../SKILL.md)

# Основные паттерны API secontrol

Подробные паттерны использования core API библиотеки secontrol для Space Engineers.

> **Краткая справка**: в [SKILL.md](../SKILL.md) есть версия быстрого старта. Нише — полные примеры кода и пояснения.

## Список всех сеток

```python
from secontrol.common import get_all_grids, resolve_owner_id
owner = resolve_owner_id()
grids = get_all_grids()  # returns list of (grid_id, grid_name)
```

## Чтение инвентаря контейнера

```python
# Containers use get_inventory() → InventorySnapshot (items are objects with attributes)
for did, dev in grid.devices.items():
    if dev.device_type == 'container':
        inv = dev.get_inventory()
        for item in inv.items:
            print(f'{item.display_name}: {item.amount}')
```

## Чтение инвентаря нефтепереработчика/сборщика

```python
# Refinery/assembler use telemetry dicts (items are plain dicts with string keys!)
t = refinery.telemetry or {}
inp = t.get('inputInventory', {})
for item in inp.get('items', []):
    print(f'{item["displayName"]}: {item["amount"]}')
```

**Полные детали + подводные камни → [references/inventory-patterns.md](inventory-patterns.md)**

## Подключение к конкретной сетке

```python
from secontrol.common import prepare_grid
grid = prepare_grid('GridName_or_GridID')  # by name or ID, auto-wakes
```

## Проверка здоровья сетки (повреждения, нерабочие, отключённые)

```python
# Quick health check across all grids
from secontrol.common import get_all_grids, prepare_grid
import time

for gid, gname in get_all_grids():
    grid = prepare_grid(str(gid))  # ALWAYS str, never int
    time.sleep(1)
    damaged = [b for b in grid.blocks.values() if getattr(b, 'is_damaged', False)]
    non_func = [b for b in grid.blocks.values() if (b.state or {}).get('functional') == False]
    disabled = [b for b in grid.blocks.values() if (b.state or {}).get('enabled') == False]
```

**Подводный камень: блоки брони всегда `functional=False`** — это нормальное поведение SE, а не повреждение. Фильтруйте нерабочие отчёты, исключая `MyObjectBuilder_CubeBlock` (броня), чтобы избежать ложных тревог. Реальное повреждение = `is_damaged=True` на функциональных блоках (SolarPanel, Conveyor, Refinery и т.д.).

**Подводный камень: песочница `execute_code` НЕ имеет установленного secontrol.** Всегда используйте `terminal` (или инструмент `bash`) для скриптов secontrol.

## Перечисление устройств на сетке

Имена типов устройств — **строчные в единственном числе** (например `'projector'`, `'ship_welder'`, `'survivalkit'`, `'solarpanel'`, `'beacon'`). Используйте `find_devices_by_type()` или `get_device_any()`:

```python
# All enabled devices
for dev in grid.find_enabled_devices():
    print(f"  {dev.device_type}: {dev.name or 'unnamed'} (id={dev.device_id})")

# Find by type (lowercase!)
for p in grid.find_devices_by_type("projector"):
    print(f"  projector: {p.name}, id={p.device_id}")
    # Access telemetry
    print(f"    isProjecting: {p.telemetry.get('isProjecting')}")
    print(f"    remainingBlocks: {p.telemetry.get('remainingBlocks')}")
    print(f"    totalBlocks: {p.telemetry.get('totalBlocks')}")

# Fuzzy find by name substring
welder = grid.get_device_any("welder")
assembler = grid.get_device_any("assembler")
```

**Особенности имён типов устройств**: `ShipWelderDevice` → `ship_welder` (подчёркивание). Survival Kit → `survivalkit` (без пробела). Solar → `solarpanel`. Ore detector → `ore_detector` (подчёркивание, НЕ `oredetector`). Если не уверены, итерируйте `find_enabled_devices()` и печатайте `dev.device_type` для всех.

## Просмотр ВСЕХ блоков (уровень блоков, без класса устройства)

Полезно при проверке блоков, у которых нет обёртки устройства (например броня, конвейер, незарегистрированные блоки):

```python
# g.blocks is a dict: block_id → BlockInfo
print(f"Total blocks: {len(grid.blocks)}")
for block_id, block in sorted(grid.blocks.items(), key=lambda x: x[1].block_type or ''):
    functional = "✓" if block.state.get('functional') else "✗"
    enabled = "ON" if block.state.get('enabled') else "OFF"
    print(f"  [{block.block_type}] '{block.subtype}' | {functional} {enabled}")
```

## Поиск конкретного блока по типу или подтипу

Когда пользователь спрашивает о конкретном блоке (например "Connector", "Refinery", "Battery"), ищите в `grid.blocks` по `block_type` или `subtype`:

```python
# Find connector blocks
for block in grid.iter_blocks():
    if 'connector' in (block.subtype or '').lower() or 'connector' in (block.block_type or '').lower():
        print(f"  Connector: block_id={block.block_id}, subtype={block.subtype}, "
              f"pos={block.local_position}, enabled={block.state.get('enabled')}")

# Find any block by SE block_type string
target_type = 'MyObjectBuilder_ShipConnector'
for bid, block in grid.blocks.items():
    if block.block_type == target_type:
        print(f"  Found: {bid} → {block.subtype} at {block.local_position}")
```

**Ключевое**: `block.block_id` — это атрибут ID (НЕ `block.id`). `block.block_type` — это строка SE типа (НЕ `block.type`). `block.subtype` работает как есть.

## Получение координат блока (данные позиции)

**Телеметрия устройства НЕ содержит данных о позиции.** Координаты берутся из `grid.blocks` → `BlockInfo`:

```python
# Find a block by type and get its position
for block_id, block in grid.blocks.items():
    if block.block_type == 'MyObjectBuilder_Refinery':
        # local_position: tuple (x, y, z) in METERS relative to grid center
        # bounding_box: dict with 'min'/'max' tuples in WORLD coordinates
        print(f"  Name: {block.name or block.subtype}")
        print(f"  Local position (meters): {block.local_position}")
        print(f"  World bbox min: {block.bounding_box['min']}")
        print(f"  World bbox max: {block.bounding_box['max']}")
        # Convert local meters to grid-local block units (large grid: 1 block = 2.5m)
        block_pos = tuple(round(v / 2.5) for v in block.local_position)
        print(f"  Grid-local block coords: {block_pos}")
```

Атрибуты `BlockInfo`: `block_id`, `block_type`, `subtype`, `name`, `local_position`, `relative_to_grid_center`, `bounding_box`, `mass`, `state`, `is_damaged`.

**Общий паттерн — поиск блока по имени пользователя (может быть локализовано):**
```python
# User says "базовый очиститель" → Basic Refinery in Russian SE
# Match by block_type or subtype, not localized display name
target_types = {
    'MyObjectBuilder_Refinery',       # Refinery / Basic Refinery (Blast Furnace)
    'MyObjectBuilder_Assembler',      # Assembler / Basic Assembler
    'MyObjectBuilder_Projector',      # Projector
    'MyObjectBuilder_ShipWelder',     # Ship Welder / Nanobot BARS
    'MyObjectBuilder_Drill',          # Drill / Nanobot Drill
}
for bid, block in grid.blocks.items():
    if block.block_type in target_types:
        print(f"  {block.block_type} ({block.subtype}) at {block.local_position}")
```

## Соответствие русских и английских названий блоков

Пользователь общается по-русски. Русская локализация SE отображает распространённые названия блоков:

| Русский (локализация SE) | Английский | block_type |
|---|---|---|
| Базовый очиститель | Basic Refinery (Blast Furnace) | MyObjectBuilder_Refinery |
| Очиститель | Refinery | MyObjectBuilder_Refinery |
| Базовый сборщик | Basic Assembler | MyObjectBuilder_Assembler |
| Сборщик | Assembler | MyObjectBuilder_Assembler |
| Проектор | Projector | MyObjectBuilder_Projector |
| Сварщик | Ship Welder | MyObjectBuilder_ShipWelder |
| Дробилка / Измельчитель | Ship Grinder | MyObjectBuilder_ShipGrinder |
| Буровая установка | Ship Drill | MyObjectBuilder_Drill |
| Батарея | Battery | MyObjectBuilder_BatteryBlock |
| Солнечная панель | Solar Panel | MyObjectBuilder_SolarPanel |
| Реактор | Reactor | MyObjectBuilder_Reactor |
| Генератор кислорода | Oxygen Generator | MyObjectBuilder_OxygenGenerator |
| Гравитационный генератор | Gravity Generator | MyObjectBuilder_GravityGenerator |
| Детектор руды | Ore Detector | MyObjectBuilder_OreDetector |
| Тягач / Двигатель | Thruster | MyObjectBuilder_Thrust |
| Шлюз | Air Vent | MyObjectBuilder_AirVent |
| Текстовая панель | Text Panel | MyObjectBuilder_TextPanel |
| Радар (Nanobot) | Ore Detector (mod) | MyObjectBuilder_OreDetector |
| Система постройки и ремонта | Nanobot Build and Repair | MyObjectBuilder_ShipWelder (subtype: SELtdLargeNanobotBuildAndRepairSystem) |
| Буровая система (Nanobot) | Nanobot Drill System | MyObjectBuilder_Drill (subtype: SELtdLargeNanobotDrillSystem) |
| Соединитель / Коннектор | Ship Connector | MyObjectBuilder_ShipConnector (subtype: Connector) |
| Соединительный блок / Мердж блок / Merge блок | Merge Block | MyObjectBuilder_MergeBlock (subtype: LargeShipMergeBlock) |

**Когда пользователь называет блок по-русски**, ищите в `grid.blocks` по `block_type` и/или `subtype`, а не пытайтесь сопоставить локализованное отображаемое имя.

Типы блоков, не входящие в DEVICE_TYPE_MAP, попадают в `GenericDevice` — всегда проверяйте `dev.device_type` (строка SE), а не только `type(dev).__name__`.

## Проверка регистрации типов устройств

```python
from secontrol.base_device import DEVICE_TYPE_MAP
# 31 registered types: reactor, battery, thruster, connector, projector, assembler, etc.
# Unknown types fall to GenericDevice — check dev.device_type for the real SE type string
```

## Чтение инвентарей

```python
from secontrol import Grid, RedisEventClient
from secontrol.common import resolve_owner_id, resolve_player_id

# Use explicit grid_id from get_all_grids() — Grid.from_name() does fuzzy search
# and may return the WRONG grid (e.g. "DroneBase" → "DroneBase 2" as first match)
redis = RedisEventClient()
owner_id = resolve_owner_id()
player_id = resolve_player_id(owner_id)

grid = Grid(redis, owner_id, grid_id, player_id, grid_name, auto_wake=True)

# Correct pattern: find containers first, then call inventories()
containers = grid.find_devices_containers()
for dev in containers:
    for inv in dev.inventories():
        if inv.items:
            print(f"[{dev.name or dev.device_type}] ({inv.name})")
            for item in inv.items:
                label = item.display_name or item.subtype or "?"
                print(f"  {item.amount:.3f} × {label}")
```

**Полные детали → [inventory-patterns.md](inventory-patterns.md)**

## Проектор / Операции с чертежами

```python
projector = grid.devices['<projector_block_id>']  # use exact block_id from grid.devices dict
projector.load_prefab('LargeAssembler')         # built-in SE prefab
projector.load_blueprint_xml(xml_string)        # custom XML blueprint
projector.request_grid_blueprint()              # export current grid to XML
projector.remaining_blocks()                    # blocks left to build
projector.total_blocks                          # total in projection (from telemetry)
projector.is_enabled                            # projection active?
```

**Поиск устройства проектора**: `grid.devices` — это dict `{block_id: device}`. Найдите проектор итерацией:
```python
proj = next(d for d in grid.devices.values() if d.device_type == 'projector')
# or by known block_id:
proj = grid.devices['144018214373629345']
```
НЕ используйте `grid.get_device("projector")` — он ищет по block_id, а не по имени типа.

## Экспорт и загрузка чертежей

```python
import time

# Export
proj.request_grid_blueprint(include_connected=False)  # False = only this grid
time.sleep(5)  # wait for SE to respond
bp = proj.blueprint_snapshot()  # dict with keys: xml, gridName, gridCount, ...
xml = bp['xml']

# Load (may not work — see pitfall below)
proj.load_blueprint_xml(xml, keep=False)  # keep=False replaces current projection
```

**`load_blueprint_xml` работает — но требует минимального XML.** Если `isProjecting` остаётся `False`
и `totalBlocks=0` после загрузки, причина почти всегда **раздувание XML** (данные ComponentContainer
раздувают XML), а не отсутствие поддержки плагина. Очистите несущественные теги (смотрите раздел
Выравнивание проекции) и повторите. Подтверждено на нескольких сетках (DroneBase, Core1).

**Диагностика**: если минимальный XML всё равно не загружается, проверьте с тривиальным 1-блочным чертежом:
```python
test_xml = '''<?xml version="1.0" encoding="utf-16"?>
<MyObjectBuilder_ShipBlueprintDefinition xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Id Type="MyObjectBuilder_ShipBlueprintDefinition" Subtype="Test" />
  <DisplayName>Test</DisplayName>
  <CubeGrids><CubeGrid><GridSizeEnum>Large</GridSizeEnum>
    <CubeBlocks>
      <MyObjectBuilder_CubeBlock xsi:type="MyObjectBuilder_Cockpit">
        <SubtypeName>LargeBlockCockpit</SubtypeName>
        <Min x="0" y="0" z="0" />
      </MyObjectBuilder_CubeBlock>
    </CubeBlocks>
  </CubeGrid></CubeGrids>
</MyObjectBuilder_ShipBlueprintDefinition>'''
proj.load_blueprint_xml(test_xml)
time.sleep(5)
proj.update()
# If totalBlocks=1 → import works, problem is your XML content
# If totalBlocks=0 → projector plugin issue, restart SE server
```

**Кодировка XML**: заголовок `encoding="utf-16"` в экспортированном XML — это нормально, игра принимает
оба объявления (utf-8 и utf-16) независимо от фактической байтовой кодировки. **Однако** Python
`xml.etree.ElementTree.parse()` строгий — он вызовет `ParseError`. Исправление:
`xml = xml.replace('encoding="utf-16"', 'encoding="utf-8"')`.

**Структура XML чертежа** (ShipBlueprintDefinition):
- `<CubeGrids><CubeGrid>` → `<PositionAndOrientation>` (мировая позиция/ориентация сетки)
- `<CubeBlocks>` → список XML-элементов блоков, каждый с:
  - `xsi:type` — класс блока SE (например `MyObjectBuilder_Assembler`)
  - `<SubtypeName>` — вариант блока (например `LargeAssembler`)
  - `<Min x="" y="" z=""/> — координата блока в локальной сетке (целые числа)
  - `<BlockOrientation Forward="" Up=""/> — строки ориентации ("Right","Up","Forward" и т.д.)
  - `<ColorMaskHSV x="" y="" z=""/> — цвет покраски

**Позиция блока в XML**: `<Min>` в **локальных целочисленных координатах сетки** (блок-единицы).
`local_position` устройства из телеметрии в **метрах** (1 большой блок = 2.5м). Конвертация:
```python
block_pos = tuple(round(v / 2.5) for v in device.local_position)
```

## Выравнивание проекции (КРИТИЧНО)

При загрузке чертежа в проектор проекция должна **точно перекрывать** существующую сетку.
Если выравнивание неправильное, сварщик попытается построить ВСЕ блоки (включая уже построенные).

**⚠️ ПРОБЛЕМА РАЗДУВАНИЯ XML ЧЕРТЕЖЕЙ (обнаружена 2026-05-14)**:
Экспорт `request_grid_blueprint` может вырасти (например 41КБ → 786КБ) из-за данных
ComponentContainer. **Загрузка полного (раздутого) XML вызывает полное рассогласование —
remainingBlocks == totalBlocks даже при правильных offset/rotation.**

**Решение: Очистите до минимального XML перед загрузкой.** Оставьте ТОЛЬКО эти теги:
```python
essential_tags = {
    'SubtypeName', 'Min', 'BlockOrientation', 'ColorMaskHSV',
    'Owner', 'BuiltBy', 'ShareMode', 'EntityId',
    'ProjectionOffset', 'ProjectionRotation',
    'Enabled', 'KeepProjection',
}
for cg in root.iter('CubeGrid'):
    cb = cg.find('CubeBlocks')
    if cb is None: continue
    for block in list(cb):
        to_remove = [child for child in block
                     if (child.tag.split('}')[-1] if '}' in child.tag else child.tag) not in essential_tags]
        for child in to_remove:
            block.remove(child)
minimal_xml = '<?xml version="1.0" encoding="utf-8"?>\r\n' + ET.tostring(root, encoding='unicode')
```

**⚠️ `set_offset()` / `set_rotation()` — это ОТНОСИТЕЛЬНЫЕ (ДЕЛЬТА) команды, а НЕ абсолютные!**
`set_offset(0, 0, 0)` означает "не двигаться" — это НЕ устанавливает смещение в начало координат.

**⚠️ `set_offset()` / `set_rotation()` НЕ влияют на проекцию после `load_blueprint_xml()`**:
Телеметрия показывает новые значения, но `remainingBlocks` НЕ пересчитывается.

**Полные детали, код brute-force и verified workflow → [projection-alignment.md](projection-alignment.md)**

**Ярлык: Разместите проектор в начале координат сетки (0,0,0).** Если `local_position` проектора
— `(0.0, 0.0, 0.0)`, то `ProjectionOffset=(0,0,0)` и `ProjectionRotation=(0,0,0)` совпадут идеально.
Поиск полным перебором не нужен. Это рекомендуемый подход для новых сеток.

**Требования к формату `load_blueprint_xml` (подтверждено 2026-05-16):**
- Должен включать атрибуты пространствён имён `xmlns:xsd` и `xmlns:xsi` на корневом элементе
- Минимальный XML (очищенный от ComponentContainer) загружается успешно
- Полный раздутый XML может молча завершиться неудачей — `isProjecting` остаётся `False`, `totalBlocks=0`
- `blueprint_snapshot()` возвращает **dict** (не сырой XML): ключи включают `xml`, `gridName`, `gridCount`, `ok`
- `totalBlocks` в телеметрии считает только НОВЫЕ блоки — уже построенные на сетке исключены

**Тайминг телеметрии**: `proj.update()` требуется 0.3-1.0с после изменения offset/rotation для
отражения нового `remainingBlocks`. Слишком быстрый опрос (<0.1с) возвращает устаревшие значения.

**Добавление нового блока к существующей сетке** (полный XML-шаблон: [blueprint-editing.md](blueprint-editing.md)):
1. Экспортируйте чертеж → очистите до минимального XML
2. Разберите XML, вставьте новый элемент блока в `<CubeBlocks>`
3. Установите `<Min>` на желаемую локальную позицию (не должна перекрывать существующие блоки)
4. Установите `<BlockOrientation>` для правильного направления
5. **Встройте проверенные offset/rotation в блок проектора** (см. шаг 8 в [projection-alignment.md](projection-alignment.md))
6. Загрузите изменённый минимальный XML
7. Проверьте `remainingBlocks` — должно равняться количеству новых блоков
8. Включите сварщик → ждите → выключите сварщик

## Процедура клонирования чертежей (сохранение шаблона сетки)

Когда пользователь хочет сохранить текущее состояние сетки как повторно используемый чертеж
для постройки копий (клонов):

1. **Экспортируйте чертеж сетки** — `request_grid_blueprint()` захватывает ВСЮ сетку,
   включая все пристыкованные/подключённые корабли, слившиеся в одну сетку.
2. **Сохраните сырой XML** — запишите в `/workspace/blueprints/<gridname>-raw.sbc`
3. **Очистите ComponentContainer** — уменьшает размер (например 240КБ → 150КБ).
4. **Исправьте объявление кодировки** — замените `encoding="utf-16"` на `encoding="utf-8"`.
5. **Проверьте XML** — разберите с `xml.etree.ElementTree`, подсчитайте блоки.
6. **Сохраните очищенную версию** — запишите в `/workspace/blueprints/<gridname>-clone.sbc`

**Ключевая идея**: `request_grid_blueprint()` экспортирует всю физическую сетку. Если два корабля
пристыкованы через коннекторы и слились в одну сетку, экспорт содержит ВСЕ блоки обоих кораблей.

**Regex для очистки** (проще, чем XML-tree подход для ComponentContainer):
```python
import re
stripped = re.sub(r'<ComponentContainer>.*?</ComponentContainer>', '', xml, flags=re.DOTALL)
```

**Полные детали редактирования чертежей → [blueprint-editing.md](blueprint-editing.md)**

## Включение всех отключённых блоков на сетке

Новообретённые/сваренные корабли часто имеют большинство блоков отключённых.
Только батареи, солнечные панели и гироскопы обычно включены:

```python
grid = prepare_grid("grid_name")  # STRING arg!
enabled = 0
for block in grid.blocks.values():
    state = block.state or {}
    if state.get('enabled') is False:
        dev = grid.get_device_any(block.block_id)
        if dev:
            try:
                dev.set_enabled(True)
                enabled += 1
            except Exception:
                pass
print(f"Enabled {enabled} blocks")
time.sleep(2)  # wait for SE to process
```

**⚠️ Не все блоки могут быть включены через API.** Мод SE обрабатывает команды включения/выключения только для определённых типов блоков:
- ✅ **Можно включить**: ThrusterDevice, BatteryDevice, GyroDevice, OreDetectorDevice, ShipWelderDevice, NanobotDrillSystemDevice, RefineryDevice, AssemblerDevice, GasGeneratorDevice, GenericDevice (H2 Engine, SolarPanel)
- ❌ **Нельзя включить**: MergeBlock, CargoContainer, Cockpit, RemoteControl, Conveyors
Для них требуется терминал в игре. API возвращает 1 (успех), но состояние блока не меняется.

## Команды сетки

```python
grid.send_grid_command('wake')    # activate telemetry
grid.park_on()                    # parking mode
grid.park_off()                   # exit parking
```

## Управление устройствами

```python
dev.enable() / dev.disable()      # toggle on/off
dev.toggle_enabled()              # flip state
```
