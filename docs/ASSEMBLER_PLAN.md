# План: Постройка Assembler на DroneBase

**Цель:** Построить Assembler на гриде DroneBase, чтобы база могла производить компоненты и расти дальше.

---

## Исходная ситуация

| Параметр | Состояние |
|---|---|
| **DroneBase** (ID 138748817302648345) | ShipWelder включён, Projector без blueprint |
| **DroneBase 2** (ID 134540402238780591) | Reactor включён, Projector без blueprint |
| **Контейнеры обеих баз** | Пустые — 0 ресурсов |
| **Survival Kit** | Выключен (enabled: False) |
| **taburet3 / taburet2** | Пустые инвентари |
| **Respawn Rover** | Пустой инвентарь |
| **Коннекторы** | Обе базы имеют Connector |

---

## Блокировка: нечего строить

Assembler требует компоненты:
- **Steel Plate × 30**
- **Interior Plate × 8**
- **Motor × 4**
- **Construction Component × 8**
- **Computer × 4**

Ни на одной базе, ни на кораблях нет ни одного ресурса. Всё пустое.

---

## Шаг 1 — Добыть железную руду

**Чем:** taburet3 или taburet2 (у обоих есть NanobotDrillSystem + OreDetector)

```python
from secontrol.common import prepare_grid

grid = prepare_grid('74055729860857332')  # taburet3

# Найти руду
detector = next(d for d in grid.devices.values() if d.device_type == 'ore_detector')
detector.scan()  # найти ближайшее железо

# Включить дрель и копать
drill = next(d for d in grid.devices.values() if d.device_type == 'nanobot_drill_system')
drill.enable()
```

**Альтернатива:** если у кораблей уже есть контейнеры с рудой из прошлых сессий — проверить `grid.inventory_items()`.

---

## Шаг 2 — Переработать руду в слитки

**Проблема:** на DroneBase нет Refinery. Survival Kit умеет перерабатывать, но:
- Включён (enabled: False) — нужно включить
- Медленный (x0.2 скорость)
- Нужно, чтобы контейнер с рудой был подключён к Survival Kit через конвейер

**Включить Survival Kit на DroneBase:**

```python
grid = prepare_grid('138748817302648345')  # DroneBase
sk = next(d for d in grid.devices.values() if d.device_type == 'survivalkit')
sk.enable()
```

**Перенести руду из taburet3 → DroneBase:**

```python
# taburet3 должен быть состыкован через Connector с DroneBase
# Перекинуть руду в контейнер DroneBase
from secontrol.inventory import InventoryTransfer
transfer = InventoryTransfer(grid)
transfer.pull_resources_from('taburet3')  # или вручную через connector
```

---

## Шаг 3 — Загрузить blueprint Assembler'а в Projector

**На DroneBase есть Projector без blueprint.** Нужно создать/загрузить blueprint для строительства Assembler'а.

### Вариант А — Использовать встроенный префаб SE:

```python
projector = next(d for d in grid.devices.values() if d.device_type == 'projector')
projector.load_prefab('LargeAssembler')  # встроенный префаб SE
```

### Вариант Б — Создать минимальный blueprint вручную:

Минимальный blueprint Assembler'а (1 блок, Large Grid):

```xml
<?xml version="1.0" encoding="utf-16"?>
<MyObjectBuilder_ShipBlueprintDefinition>
  <Id Type="MyObjectBuilder_ShipBlueprintDefinition" Subtype="AssemblerBlueprint" />
  <DisplayName>Assembler</DisplayName>
  <CubeGrids>
    <CubeGrid>
      <SubtypeName />
      <GridSizeEnum>Large</GridSizeEnum>
      <CubeBlocks>
        <MyObjectBuilder_CubeBlock xsi:type="MyObjectBuilder_Assembler">
          <SubtypeName>LargeAssembler</SubtypeName>
          <Min x="0" y="0" z="0" />
          <ColorMaskHSV x="0" y="0" z="0" />
          <Owner>144115188075855919</Owner>
          <BuiltBy>144115188075855919</BuiltBy>
          <ShareMode>Faction</ShareMode>
          <ShowOnHUD>false</ShowOnHUD>
          <ShowInTerminal>true</ShowInTerminal>
          <Enabled>true</Enabled>
          <Orientation>
            <Forward>Forward</Forward>
            <Up>Up</Up>
          </Orientation>
        </MyObjectBuilder_CubeBlock>
      </CubeBlocks>
      <DisplayName>Assembler</DisplayName>
    </CubeGrid>
  </CubeGrids>
</MyObjectBuilder_ShipBlueprintDefinition>
```

```python
projector.load_blueprint_xml(assembler_blueprint_xml)
projector.set_offset(x=0, y=0, z=0)
projector.rotate(dx=0, dy=0, dz=0)
```

---

## Шаг 4 — Построить через ShipWelder

ShipWelder (BuildAndRepairSystem) на DroneBase уже включён. Автоматически варит блоки, видимые в проекции Projector.

**Проверить статус постройки:**

```python
projector = next(d for d in grid.devices.values() if d.device_type == 'projector')
print("remaining_blocks:", projector.remaining_blocks)
print("total_blocks:", projector.total_blocks)
print("buildable_blocks:", projector.buildable_blocks)
```

Когда `remaining_blocks == 0` и `buildable_blocks == 0` — Assembler построен.

---

## Шаг 5 — Проверить работу Assembler

```python
grid = prepare_grid('138748817302648345')
assembler = next(
    (d for d in grid.devices.values() if d.device_type == 'assembler'),
    None
)
if assembler:
    print("Assembler установлен и работает!")
    assembler.enable()
    assembler.request_blueprints()
else:
    print("Assembler ещё не построен — нужны компоненты")
```

---

## Критический путь (минимум действий)

```
Добыть Iron Ore (taburet3 drill)
    ↓
Перенести в DroneBase (connector transfer)
    ↓
Включить Survival Kit (refine ore → ingots)
    ↓
Включить Survival Kit (assemble ingots → components)
    ↓
Загрузить blueprint в Projector
    ↓
ShipWelder строит Assembler автоматически
    ↓
Assembler готов → база может производить любые компоненты
```

---

## Примечания

- **Survival Kit собирает только базовые компоненты** (Steel Plate, Interior Plate, Motor, Construction Component, Computer) — этого достаточно для Assembler
- **Steel Plate = Iron Ingot × 21** (для Large Grid Assembler нужно ~30 Steel Plate → ~630 Iron Ingot)
- **Нет Refinery** на DroneBase — Survival Kit перерабатывает со скоростью x0.2, но для одного Assembler'а хватит
- **Коннекторы обоих гридов** позволяют передавать ресурсы между кораблями и базой
