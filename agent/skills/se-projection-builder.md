---
name: se-projection-builder
description: "Build new blocks on a Space Engineers grid via projector + nanobot welder. Export blueprint, modify XML, load projection, verify alignment, build."
tags: [space-engineers, secontrol, projector, blueprint, welder]
related_skills: []
linked_files:
  references:
    - references/color-conversion.md
    - references/grind-mode-detail.md
    - references/grind-color-investigation.md
---

# Projection Builder — строительство блоков через проектор

Добавление новых блоков на грид Space Engineers через экспорт блюпринта → модификацию XML → загрузку на проектор → сборку наносборщиком.

## Предусловия

- Грид доступен через secontrol (`Grid(redis, owner_id, grid_id, player_id, name)`)
- На гриде есть **проектор** и **наносборщик** (ShipWelder / NanobotBuildAndRepairSystem)
- Проектор расположен в позиции `(0,0,0)` на гриде (offset-free) ИЛИ вычислен правильный offset

## Пошаговый процесс

### 1. Подключение к гриду

```python
from secontrol import Grid, RedisEventClient
from secontrol.common import resolve_owner_id, resolve_player_id

owner_id = resolve_owner_id()
player_id = resolve_player_id(owner_id)
redis = RedisEventClient()
g = Grid(redis, owner_id, GRID_ID, player_id, "GridName", auto_wake=True)
```

### 2. Найти проектор и наносборщик

```python
# Найти устройства
for dev_id, dev in g.devices.items():
    dtype = type(dev).__name__
    print(f"  {dev_id}: {dtype}")

proj = g.devices['PROJECTOR_ID']
welder = g.devices['WELDER_ID']
```

### 3. Отключить наносборщик (ОБЯЗАТЕЛЬНО перед загрузкой!)

```python
welder.set_enabled(False)
time.sleep(1)
```

### 4. Экспорт текущего блюпринта

```python
proj.clear_projection()
time.sleep(1)
proj.request_grid_blueprint(include_connected=False)
time.sleep(10)

snap = proj.blueprint_snapshot()
xml_str = snap['xml']  # XML строка из dict
```

### 5. Снимок блоков грида (для верификации)

```python
blocks = list(g.iter_blocks())
for b in blocks:
    print(f"  {b.block_type} | {b.subtype} | local_pos={b.local_position}")
```

### 6. Модификация XML — добавление нового блока

**Ключевые правила:**
- **Координаты Min:** `local_pos = Min * 2.5` (для large grid). Min = local_pos / 2.5
- **Ориентация:** `BlockOrientation Forward="..." Up="..."` — критически важна, проверять через экспорт существующих блоков
- **Минимальный XML:** убрать ComponentContainer, инвентарь, лишние теги — иначе XML раздувается и ломает совпадение
- **Owner:** ставить `owner_id` из env
- **ColorMaskHSV:** копировать с соседних блоков (обычно `x="0" y="-0.8" z="0"`)

**Шаблон нового блока:**
```xml
<MyObjectBuilder_CubeBlock xsi:type="MyObjectBuilder_ТИП_БЛОКА">
  <SubtypeName>SubtypeBlock</SubtypeName>
  <Min x="X" y="Y" z="Z" />
  <BlockOrientation Forward="..." Up="..." />
  <ColorMaskHSV x="0" y="-0.8" z="0" />
  <Owner>OWNER_ID</Owner>
</MyObjectBuilder_CubeBlock>
```

**Типы блоков (xsi:type):**
- SolarPanel → `MyObjectBuilder_SolarPanel`
- Battery → `MyObjectBuilder_BatteryBlock`
- CargoContainer → `MyObjectBuilder_CargoContainer`
- Refinery → `MyObjectBuilder_Refinery`
- Assembler → `MyObjectBuilder_Assembler`
- Cockpit → `MyObjectBuilder_Cockpit`
- Thruster → `MyObjectBuilder_Thrust`
- Gyroscope → `MyObjectBuilder_Gyro`
- LandingGear → `MyObjectBuilder_LandingGear`
- Connector → `MyObjectBuilder_ShipConnector`
- MedicalRoom → `MyObjectBuilder_MedicalRoom`

### 7. Загрузка модифицированного XML на проектор

```python
result = proj.load_blueprint_xml(xml)
time.sleep(5)
proj.update()
t = proj.telemetry
print(f"totalBlocks={t.get('totalBlocks')}, remainingBlocks={t.get('remainingBlocks')}, buildableBlocks={t.get('buildableBlocks')}")
```

### 8. Верификация

- `remainingBlocks=0` → все блоки совпали (проекция выключится автоматически)
- `remainingBlocks=N` → N блоков нужно построить (новый блок + возможные расхождения)
- `buildableBlocks=N` → N блоков готовы к постройке наносборщиком

**Если remainingBlocks не совпадает с ожидаемым:**
1. Экспортировать блюпринт заново
2. Сравнить Min и BlockOrientation каждого блока
3. Проверить что нет дубликатов в XML
4. Убедиться что XML минималистичен (без ComponentContainer)

### 9. Сборка через Nanobot Build & Repair System

**ВАЖНО:** NanobotBuildAndRepairSystem зарегистирован как `ShipWelderDevice`, но для строительства нужен `BuildAndRepairDevice` API. `set_enabled(True)` только включает блок, но не активирует строительство!

```python
from secontrol.devices.build_and_repair_device import BuildAndRepairDevice

# Создать обёртку BuildAndRepairDevice
welder_raw = g.devices['WELDER_ID']
bar = BuildAndRepairDevice(g, welder_raw.metadata)
bar._telemetry = welder_raw.telemetry

# Настроить строительство
bar.set_allow_build(True)   # разрешить строительство проекций
bar.set_mode(1)             # режим сварки (0=idle, 1=weld, 2=grind)
bar.set_work_mode(1)        # режим работы (0=off, 1=work)
bar.set_weld_only()         # только сварка (не разбирать)

# Ждать пока remainingBlocks станет 0
proj.update()
t = proj.telemetry
# Когда remainingBlocks=0:
bar.set_mode(0)             # вернуть в idle
```

**Если обычный ShipWelder (не Nanobot):**
```python
welder.set_enabled(True)
# ... ждать ...
welder.set_enabled(False)
```

## Позиционирование блоков

### Вычисление Min из позиции в игре

1. Поставить блок в игре вручную
2. Экспортировать блюпринт (`request_grid_blueprint`)
3. Найти блок в XML → прочитать Min
4. Использовать эти координаты в модифицированном XML

### Вычисление Min из local_position телеметрии

```python
# Для large grid: local_pos = Min * 2.5
min_x = round(local_pos[0] / 2.5)
min_y = round(local_pos[1] / 2.5)
min_z = round(local_pos[2] / 2.5)
```

### Вычисление orientation

Ориентацию НЕ вычислять теоретически — только копировать из экспортированного XML аналогичного блока или ставить `Forward="Forward" Up="Up"` (по умолчанию) и проверять в игре.

## Offset и Rotation проектора

- Если проектор на `(0,0,0)` → offset=(0,0,0), rotation=(0,0,0) — не нужны корректировки
- Если проектор НЕ на origin → нужно вычислить offset из позиции проектора
- `set_offset` / `set_rotation` принимают **дельту** (на сколько сдвинуть), не абсолютные значения
- После `load_blueprint_xml` offset/rotation сбрасываются — команды `set_offset` после загрузки НЕ работают на некоторых серверах

## Покраска блоков (paint_block)

Для покраски блоков используется `g.paint_block(block_id, hsv=[H, S, V])`.
Подробная таблица конвертации: см. `references/color-conversion.md`.

**Краткая формула** (из ColorMaskHSV целевого блока в paint_block):
```python
# Из экспорта: ColorMaskHSV x=H/360, y и z в -1..1
# paint_block принимает hsv=[H, api_S, api_V] где api_S и api_V в 0..1
api_S = (colorMask_y + 1) / 2   # y=0.2 → api_S=0.6, y=-0.8 → api_S=0.1
api_V = (colorMask_z + 1) / 2   # z=0.05 → api_V=0.525
g.paint_block(block_id, hsv=[H, api_S, api_V])
```

⚠️ **НЕ использовать `S_game/100`!** Формат терминала игры НЕ совпадает напрямую
с ColorMaskHSV. Единственный надёжный способ — взять x,y,z из экспорта блока
и пересчитать в api-значения.

⚠️ **ВСЕГДА использовать `hsv=`, НЕ `rgb=`!** Покраска через `rgb=[127,0,82]` даёт
ColorMaskHSV `(0.89, 1.0, -0.004)` — совершенно другой результат, чем `hsv=[321, 1.0, 0.5]`
→ `(0.89, 1.0, 0.0)`. Game engine по-разному обрабатывает RGB vs HSV payload.

Верификация — экспорт блюпринта и проверка ColorMaskHSV.

### Верификация цвета — обязательно при grind workflow

```python
proj.request_grid_blueprint(include_connected=False)
time.sleep(10)
snap = proj.blueprint_snapshot()
import xml.etree.ElementTree as ET
root = ET.fromstring(snap['xml'])
for cb in root.iter('MyObjectBuilder_CubeBlock'):
    sub = cb.findtext('SubtypeName', '?')
    color = cb.find('ColorMaskHSV')
    if color is not None:
        x, y, z = color.get('x'), color.get('y'), color.get('z')
        # Точные строки без float-конвертации для сравнения
        print(f"  {sub}: x={x}  y={y}  z={z}")
```

**Float-шум:** `paint_block` иногда даёт `y=0.200000048` вместо `y=0.2`. Разница ~5×10⁻⁸
не влияет на gameplay, но при сравнении использовать `abs(a-b) < 1e-6`.

## Разборка блоков (Grind Mode)

Nanobot BARS разбирает блоки по **точному совпадению цвета** с grind color. Все три компонента HSV должны совпадать (оттенок, насыщеность, значение).

**Grind color через API (`set_grind_color`) не работает** — команды уходят (result=1), но мод их игнорирует. Настройка grind color возможна только через терминал наносборщика в игре.

### Workflow разборки

1. Игрок вручную настраивает в терминале наносборщика: режим Grind, Use Grind Color, нужный цвет
2. Покрасить целевые блоки через `paint_block(hsv=[H, S_norm, V_norm])` — **точно** в цвет grind color
3. Включить наносборщик: `welder.set_enabled(True)`
4. Подождать ~90 секунд, проверить через экспорт

### Конвертация ColorMaskHSV → paint_block

Игра хранит ColorMaskHSV: x=H/360, y и z в -1..1. API `paint_block` принимает `hsv=[H, S, V]` где S и V в 0..1.

**Формула:**
```python
api_S = (colorMask_y + 1) / 2
api_V = (colorMask_z + 1) / 2
```

Примеры:
- Железный блок: ColorMaskHSV y=0.2, z=0.05 → api_S=0.6, api_V=0.525 → `hsv=[321, 0.6, 0.525]`
- Блок по умолчанию: y=-0.8, z=0 → api_S=0.1, api_V=0.5 → `hsv=[0, 0.1, 0.5]`

**НЕ гадать HSV из терминала игры** — формат терминала может не совпадать с ColorMaskHSV.
Всегда брать точные x,y,z из blueprint экспорта нужного блока.

**Проверять точность через экспорт блюпринта** — сравнить ColorMaskHSV целевого блока и перекрашенного.

**Экспериментально подтверждено (2026-05-16):** при идентичном ColorMaskHSV
`(0.891666651, 0.2, 0.05)` наносборщик разобрал **оба** блока:
- LargeBlockArmorBlock → ✅ разобран
- LargeBlockSolarPanel → ✅ разобран

Nanobot BARS разбирает **любые** блоки по цвету (structural и functional),
если ColorMaskHSV точно совпадает с grind color.

### Настройка grind mode

#### Через API (команды принимаются, но мод может игнорировать)

```python
welder.send_command({"cmd": "set", "payload": {"property": "BuildAndRepair.Mode", "value": 2}})
welder.send_command({"cmd": "set", "payload": {"property": "BuildAndRepair.WorkMode", "value": 1}})
welder.send_command({"cmd": "set", "payload": {"property": "BuildAndRepair.UseGrindColor", "value": True}})
welder.send_command({"cmd": "set", "payload": {"property": "BuildAndRepair.GrindColor", "color": [R, G, B]}})
```

⚠️ `set_grind_color(r, g, b)` принимает **RGB**, не HSV. Конвертировать: `colorsys.hsv_to_rgb(H/360, S/100, V/100)`.

#### Вручную в игре (рекомендуется)

1. Открыть терминал наносборщика → переключить на "Grind"
2. Установить "Grind Color" в пикере → **запомнить точные H, S, V**
3. Включить "Use Grind Color"
4. Покрасить целевые блоки через API в этот цвет (см. формулу выше)
5. Наносборщик начнёт разборку structural блоков

### Telemetry: Nanobot НЕ передаёт grind-данные

Телеметрия наносборщика содержит только: `enabled`, `isWorking`, `isFunctional`, `deviceKind`, `load`, `items`.

**Отсутствующие поля** (ключей НЕТ в Redis):
`buildandrepair_grindcolor`, `buildandrepair_mode`, `buildandrepair_workmode`,
`buildandrepair_usegrindcolor`, `buildandrepair_allowbuild`,
`possibleGrindTargets`, `currentGrindTarget`.

Нельзя прочитать grind state через API — только визуально в игре.

## Удаление блоков с грида

Два способа: **grind через наносборщик** (подтверждён) и **прямая команда** (не проверена).

### Способ 1: Grind через Nanobot BARS (подтверждено 2026-05-16)

Работает для **любых** блоков (structural и functional) при точном совпадении цвета.

#### Пошаговый workflow

```python
import time
from secontrol import Grid, RedisEventClient
from secontrol.common import resolve_owner_id, resolve_player_id

owner_id = resolve_owner_id()
player_id = resolve_player_id(owner_id)
redis = RedisEventClient()
g = Grid(redis, owner_id, GRID_ID, player_id, "GridName", auto_wake=True)

# 1. Найти наносборщик
welder = None
for dev_id, dev in g.devices.items():
    if 'Welder' in type(dev).__name__ or 'Nanobot' in type(dev).__name__:
        welder = dev
        break

# 2. Экспортировать блюпринт — найти целевые блоки и их точные ColorMaskHSV
proj = g.find_devices_by_type('ProjectorDevice')[0]
proj.request_grid_blueprint(include_connected=False)
time.sleep(10)
snap = proj.blueprint_snapshot()

import xml.etree.ElementTree as ET
root = ET.fromstring(snap['xml'])

# 3. Определить grind color из игры (ВРУЧНУЮ в терминале наносборщика!)
#    H=..., S=..., V=... — запомнить точные значения
#    Найти блок с таким же цветом в экспорте → взять его x, y, z

GRIND_X = 0.891666651  # пример: H=321
GRIND_Y = 0.2          # пример: S из игры
GRIND_Z = 0.05         # пример: V из игры

# 4. Рассчитать параметры для paint_block
api_S = (GRIND_Y + 1) / 2   # → 0.6
api_V = (GRIND_Z + 1) / 2   # → 0.525
hue = GRIND_X * 360          # → 321

# 5. Покрасить целевые блоки в grind color
target_block_ids = []
for cb in root.iter('MyObjectBuilder_CubeBlock'):
    sub = cb.findtext('SubtypeName', '?')
    # Фильтровать по типу, позиции, имени и т.д.
    if sub == 'LargeBlockSolarPanel':
        eid = cb.find('EntityId')
        if eid is not None:
            target_block_ids.append(int(eid.text))

for bid in target_block_ids:
    result = g.paint_block(bid, hsv=[hue, api_S, api_V])
    print(f"paint_block({bid}): {result}")

time.sleep(2)

# 6. Верификация покраски — ColorMaskHSV должен ТОЧНО совпасть
proj.request_grid_blueprint(include_connected=False)
time.sleep(10)
snap = proj.blueprint_snapshot()
root = ET.fromstring(snap['xml'])
# ... проверить что ColorMaskHSV совпадает с grind color (abs < 1e-6)

# 7. Включить наносборщик
welder.set_enabled(True)

# 8. Ждать ~90 секунд
time.sleep(90)

# 9. Проверить — блоки должны исчезнуть
proj.request_grid_blueprint(include_connected=False)
time.sleep(10)
snap = proj.blueprint_snapshot()
root = ET.fromstring(snap['xml'])
blocks_after = list(root.iter('MyObjectBuilder_CubeBlock'))
print(f"Блоков было → стало: ... → {len(blocks_after)}")
```

#### Важные правила

- **Grind color настраивается ТОЛЬКО вручную в игре** — API `set_grind_color()` игнорируется модом
- **ColorMaskHSV должен совпадать ТОЧНО** — разница >1e-6 ломает совпадение
- **НЕ гадать HSV из терминала игры** — формат терминала может не совпадать с ColorMaskHSV. Всегда брать x,y,z из blueprint экспорта блока, у которого цвет совпадает с grind color
- **Конвертация:** `api_S = (y + 1) / 2`, `api_V = (z + 1) / 2`, `hue = x * 360`
- **Телеметрия НЕ содержит grind-данных** — `buildandrepair_grindcolor`, `possibleGrindTargets` и др. отсутствуют в Redis
- **Nanobot разбирает ЛЮБЫЕ блоки** — и structural (armor), и functional (solar panel, battery, cargo)
- **Device IDs могут меняться** — всегда заново искать через `g.devices.items()`

### Способ 2: Прямая команда remove_block (не проверена)

Возможно, SE сервер поддерживает grid-level команду удаления:

```python
g.send_grid_command("remove_block", payload={"blockId": BLOCK_ID})
```

⚠️ **Не проверено!** Может не работать или требовать admin-прав. Использовать grind workflow как основной метод.

### Способ 3: Ручное удаление в игре

Если API недоступен — игрок удаляет блоки через grinder/hand tool в игре.

## Pitfalls

1. **XML с ComponentContainer ломает совпадение** — всегда стрипать до минимального XML. Блюпринт может раздуваться с 40KB до 800KB.
2. **Ориентация критична** — неправильный Forward/Up → блок повёрнут не так, не совпадает с проекцией. Всегда проверять через экспорт.
3. **`set_offset` — дельта, не абсолют** — для смещения на (5,0,0) при текущем (2,0,0) подать (3,0,0).
4. **`load_blueprint_xml` может не работать** — если XML содержит ошибки формата, команда пройдёт (sent=1) но проектор не покажет блоки. Проверять totalBlocks после загрузки.
5. **Duplicate blocks** — экспорт может содержать дубликаты (connected grids). Не включать дубликаты в модифицированный XML.
6. **Nanobot welder строит автоматически** — если включён при загрузке проекции, начнёт строить всё подряд. ВСЕГДА отключать перед загрузкой.
7. **remainingBlocks=0 → проекция выключается** — нормальное поведение. Для добавления нового блока нужно загрузить проекцию заново.
8. **Grind mode через API не работает** — команды отправляются но наносборщик не начинает разборку. Нужна ручная настройка в игре.
9. **Grind color должен ТОЧНО совпадать** — даже разница в 1 единицу S или V ломает совпадение. Всегда брать точные ColorMaskHSV из экспорта целевого блока, а не из настроек терминала (форматы могут отличаться).
10. **Device IDs могут меняться между сессиями** — наносборщик сменил ID с `119686699013531045` на `80852573530523898`. Всегда заново обнаруживать устройства через `g.devices.items()`.
11. **`send_command` принимает dict** — не `(cmd_string, state=dict)`. Формат: `{"cmd": "set", "payload": {"property": "BuildAndRepair.X", "value": V}}` для свойств, `{"command": "ActionName", "payload": {}}` для actions.
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
# totalBlocks=1 → импорт работает, проблема в вашем XML
# totalBlocks=0 → проблема плагина, перезапустить SE сервер
```
5. **XML encoding="utf-16"** — заголовок не важен, игра принимает и utf-8 и utf-16 declarations.
6. **Duplicate blocks** — экспорт может содержать дубликаты (connected grids). Не включать дубликаты в модифицированный XML.
6. **Nanobot welder строит автоматически** — если включён при загрузке проекции, начнёт строить всё подряд. ВСЕГДА отключать перед загрузкой.
7. **remainingBlocks=0 → проекция выключается** — нормальное поведение. Для добавления нового блока нужно загрузить проекцию заново.
