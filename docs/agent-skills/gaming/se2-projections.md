# SE2 Проекции и стройка (GridProjections)

Как ставить проекции, дополнять (сваривать) их и строить базы автоматически.
Реализовано в плагине SE2GameAPI (`src/Game/Constructions/ProjectionService.cs`),
транспорт — Redis-очередь `se2:local:build`.

## Механизм движка (реверс)

В SE2 нет блока-проектора как в SE1. Проекция — отдельная **сущность** с компонентом
`ProjectionSourceComponent`:

```
грид-источник
  → BlueprintHelpers.SerializeGrid(grid, null)        # EntityBundle (путь blueprint-копии)
  → GridProjectionsSessionComponent.PrepareGridProjection(bundle, owner)   # EntityObjectBuilder
  → IEntitySpawner.SpawnEntity(ob, DEntityBuilder.ForScene(scene))         # призрак в мире
  → AttachProjection(projection, hostGrid)             # матриализация в клетках ХОСТА
```

Достройка:

- **Сварщик игрока**: `IntegrityToolComponent` поднимает integrity блока призрака,
  при заполнении вызывается `TryMaterializeBlock` — блок становится реальным.
- **Программно**: `GridProjectionsSessionComponent.TryMaterializeBlock(projection, ChildRef, owner, removeProjection)` —
  один блок за вызов. Результат — `BuildResultEnum`:
  `Success=0, FailedOccupiedGridCells=1, FailedOccupiedCollision=2, FailedOccupiedVoxel=4,
  FailedMissingMountPoint=8, FailedDistance=16, FailedOwnership=32, FailedPCU=64, ...`

### Важные правила

1. **`PrepareGridProjection` пересчитывает блоки** в локальные координаты (`TransformInvBundle`) —
   сдвиг позиций OB внутри бандла вручную бесполезен, мирные позиции сохраняются.
2. **Материализация идёт в клетках грида-хоста**: проекция привязывается через
   `AttachProjection(projection, hostGrid)`. Блоки обязаны попадать в свободные клетки хоста
   и иметь **mount point** — касание с существующими блоками (иначе `FailedMissingMountPoint`).
3. **Удаление хоста убивает привязанную проекцию** (attach = lifecycle-связь).
4. **Owner** (`IdentityId`) обязателен и не `default` — берётся от блока грида;
   для NPC-гридов без владельца подставляется любой валидный владелец мира.
5. `Serialize` требует OB, аллоцированный через `EntitySerializer.AllocateEmptyEOBFor(entity)`
   (приватный — вызывать рефлексией), иначе NRE.
6. `ChildRef` — путь в иерархии бандла: `[индекс в Builders, индекс в Children span, ...]`.
   Дети корня перебираются `HierarchyComponentObjectBuilderExtensions.TryGetDirectChilds(rootOb)`
   (возвращает `Span<EntityObjectBuilder>`).
7. Позиция проекции сдвигается **после спавна** через `EntityTransformFunctions.Teleport(entity.Data, ref wt)`.

## Redis API (очередь `se2:local:build:requests`)

Запрос (JSON, RPUSH; deadline ≤110 с):

```json
{
  "requestId": "<uuid4hex>", "epoch": "<из se2:local:state>", "gridId": "186:1",
  "action": "create | convert | list | materialize | create_template",
  "targetGridId": "...", "offset": [x, y, z], "count": N,
  "expiresAtMs": 0
}
```

Ответ: ключ `se2:local:build:{requestId}` (TTL 5 мин) + событие в `se2:local:build:events`:

```json
{"state": "complete", "error": null, "projectionEntityId": "882:2",
 "projections": 1, "materialized": 2, "updatedAtMs": ...}
```

### Действия

| action | параметры | что делает |
|---|---|---|
| `create` | `gridId`=источник, `targetGridId`=хост, `offset` | SerializeGrid источника → проекция у хоста+offset |
| `convert` | `gridId`=источник, `targetGridId`=хост (default: сам), `offset` | призрак грида на его месте, attach к хосту, teleport на offset; источник НЕ удаляется |
| `create_template` | `gridId`=донор блока, `targetGridId`=хост, `offset`, `count`=N | **программный шаблон**: плита N×N из самого массового (броня) блока донора |
| `list` | — | все проекции сцены |
| `materialize` | `gridId`=хост, `targetGridId`=projection id, `count` | материализация блоков призрака (count=0 → все) |

### Ошибки материализации

- `FailedMissingMountPoint` — блок не касается существующих: сдвинь offset ближе;
- `FailedOccupiedGridCells` — клетка занята (блок хоста или воксель): подбери offset;
- стык ищется перебором offset (шаг ≈ размеру блока).

### Правила шаблонов (create_template, программная сборка)

1. **Скейл сеток должен совпадать**: блок донора (2 м/1.5 м) и грид-хост — одна размерность,
   иначе все клетки `OccupiedGridCells`. Броня базы (2 м) → хост только крупная база.
2. **Transform корня донора сбрасывается в identity** перед `PrepareGridProjection` —
   иначе `TransformInvBundle` запечёт мировые координаты базы в локальные позиции блоков,
   и плиту нельзя будет позиционировать.
3. Позиция блока хранится в `ChildTransformComponentObjectBuilder.Transform.Position`
   (`RelativeTransform`, локально к гриду). Мировая позиция блока — НЕ `WorldTransform`.
4. Порядок сборки бандла: клонировать root OB → очистить его Children → добавить
   клонов блоков (`AddDirectChild`) → только потом `bundle.Add(root, entity, true)`.
5. Броня-кандидат: группы детей по `Definition`; «простой» блок — без функциональных
   компонентных OB (Thruster/Powerable/Gyro/...).
6. Плита строится в X-Z (горизонталь), центрирована на origin — offset задаёт точную
   мировую позицию центра.
7. Точная стыковка: окно касания может быть меньше перебора offset; надёжный путь —
   вычислять клетку через `CubeGridCoords.LocalToGrid` (TODO).

### Воксельные сканы: ловушки координат

1. **Оси тайлов единичные** (`|axisX|=1.000`): размер вокселя в осях НЕ закодирован.
   При `lod=0` шаг = 1 м (позиции `origin + (x+0.5)*ax` верны), но при `lod>0` реальный
   шаг = `2^lod` м, а оси остаются единичными — координаты сжимаются в `2^lod` раз.
   **Для точной геометрии всегда lod=0.**
2. **Partial-сканы**: публикуется часть тайлов (issues: `query_empty` на невыгруженных
   хранилищах) — покрытие меняется от скана к скану; «ближайшая порода» может оказаться
   в непокрытом участке (погрешность до нескольких метров).
3. Направление к породе надёжнее проверять эталоном: блок-ориентир, поставленный
   игроком в камне (его позиция = истина).

## Пример: основание базы из шаблона

```python
# плита 4x4 из брони донора у хоста
run("create_template", gridId=donor, targetGridId=host, offset=[12.0, 0.0, 0.0], count=4)
# материализовать все блоки
run("materialize", gridId=host, targetGridId=pid)
```

Тестовые скрипты: `tmp/test_projection.py`, `tmp/test_cycle_h2.py`, `tmp/find_contact.py`.
Живой пруф: проекция H2 Prototype у Bullfrog, 2 блока материализованы (Success).
