# Mission: проекция чертежа на проектор с выравниванием по Merge Block

Два скрипта под два размера проектора:

| Скрипт | Версия | Когда использовать |
|---|---|---|
| `examples/organized/projector/align_clone_projection.py` | v17 | LargeProjector на большой станции/корабле. |
| `examples/organized/projector/align_clone_projection_small.py` | **v20** | **SmallProjector** (в т.ч. на субгриде, прицепленном ротором к большой базе). Сам устраняет баг UI-offset origin на малом проекторе. |

Оба скрипта поддерживают три сценария:

- **opposite** (по умолчанию) — ставит проекцию впритык с зазором, рядом с живым гридом (сборка клона в стороне).
- **overlay** — кладёт проекцию поверх тех же ячеек, что и контактная пара.
- **offline** — только готовит XML без подключения к игре/Redis.

---

## Главное правило выбора скрипта

> **Всегда используй v20 для SmallProjector**, даже если он живёт на субгриде ротора, прицепленного к большой станции.
>
> У SE в UI offset для SmallProjector сдвинут на `(-1, -1, 0)` относительно реальной origin-кубика. v17 это не учитывает и кладёт проекцию со сдвигом в 1 клетку. v20 автоматически делает `Projector UI origin correction: (-1, -1, 0)` и кладёт ровно туда, куда нужно.

`v17` и `v20` — это два независимых исполняемых файла; оба живут в `examples/organized/projector/`. Внутри они делят ~70% кода (парсинг XML, выбор merge/connector пары, 24 кубических поворота, pre-flip вокруг контактной линии, anchor-based XML-сдвиг), но у v20 поверх v17 три добавки: projector orientation compensation, fixed anchor для отсутствующего `Min` у проектора, и projector UI origin correction.

---

## Канонический запуск на малом проекторе (v20)

Типичный кейс: на `skynet-farpost0` есть Merge+Connector пара на субгриде, рядом с ними SmallProjector, нужно положить рядом чертёж `skynet-scout0/bp.sbc`.

```bash
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection_small.py skynet-farpost0 "C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-scout0" --normal=auto --projector-subtype=SmallProjector
```

- `C:\Python311\python.exe` — точная версия интерпретатора, под которой ведётся разработка. Можно заменить на актуальный `python` из PATH, но эта команда детерминирована.
- `skynet-farpost0` — главный (родительский) грид. Скрипт сам видит субгрид через `farpost0.iter_blocks()`.
- Путь к `bp.sbc` опционален — скрипт сам берёт `%APPDATA%/SpaceEngineers/Blueprints/local/<grid>/bp.sbc`.
- `--projector-subtype=SmallProjector` обязателен, когда на гриде несколько проекторов (например, LargeProjector на самой станции + SmallProjector на субгриде ротора).
- `--normal=auto` обязателен для случаев, когда точная ориентация контакта неизвестна. Скрипт перебирает все перпендикуляры к линии merge↔connector и выбирает сторону с наименьшим числом коллизий.

### Что выведет v20 (успешный dry-run)

```text
SCRIPT_VERSION: align-clone-projection-offset-v20-small-projector-ui-origin-correction-2026-06-08
Blueprint file: C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-scout0\bp.sbc
Grid step: 0.5 m                          ← правильный шаг для малой сетки
Projector: None (<eid>) at (0, 1, 1)      ← SmallProjector на субгриде
Projector UI origin correction: (-1, -1, 0) (auto SmallProjector)
Projector orientation compensation: identity fallback; projector orientation unavailable; using identity grid axes
Contact axis: z
Pre-flip around contact line: True
Rotation mode: xml block transform
Placement mode: opposite
Contact normal: (-1, 0, 0)                ← auto-выбор перпендикуляра
Target merge:    (-1, 3, 1)
Target connector:(-1, 3, 0)
ProjectionOffset to apply: (-1, 5, 3)
XML relative shift applied to non-anchor blocks: (-1, 5, 3)
Projector UI offset kept for model-origin correction: (-1, -1, 0)
Embedded final projector transform into XML blocks: 1, offset=(-1, -1, 0), rotation=(0, 0, 0)
XML shifted blocks: 18; anchor projector kept at (0, 1, 1)
Prepared blueprint saved: bp-contact-clone-offset.sbc
```

Ключевая строка для SmallProjector: `Projector UI offset kept for model-origin correction: (-1, -1, 0)` — скрипт **не обнуляет** UI offset, а оставляет корректирующий `(-1, -1, 0)`, чтобы SE правильно совместил origin проекции с origin-кубиком малого проектора.

### v20-специфичные опции

| Флаг | Что делает |
|---|---|
| `--projector-ui-correction=-1,-1,0` | Ручная коррекция UI origin (по умолчанию авто для SmallProjector) |
| `--no-small-projector-correction` | Отключить автокоррекцию (если уже учтена вручную) |
| `--projector-forward=Forward` | Зафиксировать ориентацию проектора (`Forward`/`Backward`/`Left`/`Right`/`Up`/`Down`) |
| `--projector-up=Up` | Зафиксировать Up-ось проектора |
| `--ignore-projector-orientation` | Полностью игнорировать ориентацию проектора (использовать identity axes) |

Если хочешь увидеть только XML без загрузки в проектор — добавь `--no-upload`.

---

## Канонический запуск на большом проекторе (v17)

```bash
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection.py skynet-farpost0 "C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-agent0\bp.sbc" --normal=-z
```

- Подходит, когда blueprint — большая сетка (large grid) и проектор — LargeProjector.
- Если на гриде несколько проекторов, дополни `--projector-subtype=LargeProjector`.
- `--normal=-z` можно заменить на `auto`, `+x`, `-x`, `+y`, `-y`, `+z`.

Если путь к чертежу опустить, скрипт сам берёт `%APPDATA%/SpaceEngineers/Blueprints/local/<grid>/bp.sbc` (`align_clone_projection.py:1885`).

---

## Что делает скрипт внутри

Полный путь — `main()` (`align_clone_projection.py:1928` для v17, `align_clone_projection_small.py:2182` для v20). Внутри 8 фаз. v20 добавляет поверх v17 три: **projector orientation compensation**, **fixed anchor для missing Min**, **projector UI origin correction**.

### 1. Разрешение источника чертежа

`resolve_blueprint_path()` (`align_clone_projection.py:383`, `align_clone_projection_small.py:520`) принимает:

- путь к `bp.sbc`;
- директорию с `bp.sbc` (или любую вложенную);
- `.zip` с чертежом — распакует во временную папку;
- пустую строку → `%APPDATA%/SpaceEngineers/Blueprints/local/<grid>/bp.sbc`.

Затем `parse_blueprint()` (`align_clone_projection.py:442`, `align_clone_projection_small.py:579`) нормализует XML в `MyObjectBuilder_ShipBlueprintDefinition`, если пришёл `ShipBlueprint` напрямую.

`grid_step_from_blueprint()` (`align_clone_projection.py:466`, `align_clone_projection_small.py:603`) берёт шаг из `GridSizeEnum` (2.5 м для large, 0.5 м для small).

### 2. Подключение к живому гриду и сбор телеметрии

```text
prepare_grid(grid, auto_wake=True)        # пробуждает грид
grid.refresh_devices()                    # актуализирует устройства
collect_live_blocks(grid, grid_step)      # все блоки в grid-step координатах
find_projector(grid, name, subtype)       # v17: через find_devices_by_type
                                          # v20: напрямую из live_by_entity_map
```

`live_by_entity_map` индексирует живые блоки по `EntityId` — это нужно, чтобы скрипт мог сопоставить blueprint merge/connector с реальной парой на корабле, даже если в чертеже они сдвинуты.

> **Известный нюанс:** v20 в dry-run сообщает `Projector: None (<eid>) at (0, 1, 1)` с одним `eid`, а v17 — с другим (при одинаковом `Min`). Это потому что v20 берёт блок из `live_by_entity_map` напрямую, а v17 — через `find_devices_by_type()`. Поведение корректное, но для трейсинга используй `eid` из `grid_report.py`.

### 3. Чистка и дополнение blueprint XML

| Шаг | Функция | Что делает |
|---|---|---|
| Восстановление Min | `fill_missing_min_from_live()` | Если в XML нет `Min`, берёт позицию из телеметрии по `EntityId` |
| Восстановление Min проектора | `fill_missing_projector_min()` | Без Min у projector-блока скрипт падает; использует `live_projector_min` как fallback. v20 усиливает это через `collect_missing_projector_min_elements()` (`align_clone_projection_small.py:677`) — собирает все `CubeBlock` без `Min` рядом с проектором и закрепляет их как fixed anchor. |
| Удаление мусора | `remove_blocks_without_min()` | Блоки без `Min` не имеют смысла для контакта и удаляются |
| Стрип тегов | `strip_bloated_block_data()` (опц.) | Оставляет только `ESSENTIAL_BLOCK_TAGS` (см. `align_clone_projection.py:66`) — по умолчанию **выключено**, чтобы XML оставался максимально совместимым с плагином |

### 4. Выбор контактной пары merge ↔ connector

`choose_blueprint_pair()` (`align_clone_projection.py:598`, `align_clone_projection_small.py:758`) — находит все Merge Block и Connector в чертеже, фильтрует по `--contact-tag` (имя/subtype/entity_id), сортирует пары по Manhattan-расстоянию и берёт ближайшую.

`choose_live_pair()` (`align_clone_projection.py:621`, `align_clone_projection_small.py:781`) делает то же на живом гриде. Сначала пробует сопоставить по `EntityId` blueprint→live, потом фолбэк на tag-фильтр.

> **Почему Merge+Connector, а не что-то одно?** Merge Block даёт жёсткий контакт по грани, Connector — длинную ось для выравнивания. Пара фиксирует и сторону, и направление клона. Условие: live-вектор между merge и connector должен быть **осе-выровнен** (одна активная ось X/Y/Z), иначе скрипт упадёт с `ValueError`.

### 5. Геометрия: вращение XML вокруг контактной линии

`prepare_blueprint_geometry()` (`align_clone_projection.py:777`, `align_clone_projection_small.py:937`) — сердце выравнивания. Шаги:

1. `choose_base_rotation()` подбирает из 24 кубических поворотов (`cube_rotations()`) тот, который превращает blueprint-вектор `merge→connector` в live-вектор.
2. **Pre-flip 180°** вокруг оси контакта (`rotate_180_around_axis()`, `align_clone_projection.py:700`, `align_clone_projection_small.py:860`). Зачем: клон должен расти в сторону **от** источника, а не в него. `pivot` — это `blueprint_pair.merge.min`, и вся blueprint-геометрия отражается относительно плоскости, проходящей через merge и направленной вдоль линии контакта.
3. Для **каждого блока** пересчитывается Min через `transform_block_min_by_occupied_cells()` (`align_clone_projection.py:359`). Это критично: SE Min — это угол occupied-box, а не центр. Для thruster 1×1×2, танка 3×3×3, cargo 3×3×3 простое вращение Min даст визуальный дрейф. Скрипт перебирает все занятые ячейки, вращает их, берёт новый минимум (`align_clone_projection.py:802-813`).
4. `update_orientation()` пишет новые `Forward/Up` в `BlockOrientation`, чтобы `BlockOrientation` остался каноническим (один из 6 направлений × знак).

После фазы вектор `transformed_connector - transformed_merge` в blueprint **обязан** совпасть с live-вектором. Если нет — внутренняя ошибка (`align_clone_projection.py:818`).

**v20-only: projector orientation compensation.** `projector_axis_transforms()` (`align_clone_projection_small.py:434`) читает live-ориентацию проектора через `live_block_orientation()` (`align_clone_projection_small.py:414`) — возвращает `forward` и `up` вектора по телеметрии. Парсинг CLI-флагов `--projector-forward=` и `--projector-up=` — через `parse_direction_arg()` (`align_clone_projection_small.py:466`) и `parse_axis_direction()` (`align_clone_projection_small.py:340`). Итог: `choose_placement_projector_rotation()` (`align_clone_projection_small.py:1349`) учитывает реальную ориентацию проектора, а не только identity axes.

### 6. Выбор стороны (`choose_placement`)

`choose_placement()` (`align_clone_projection.py:1021`, `align_clone_projection_small.py:1226`). С учётом режима:

- `opposite` — перебираются нормали, перпендикулярные контактной оси. `target_merge = live.merge + normal*gap`, `target_connector = live.connector + normal*gap`. `gap` = `--contact-gap` (по умолчанию 1, для face-to-face merge/connector это правильно: грань merge упирается в merge на расстоянии 1 клетки).
- `overlay` — единственный кандидат `normal = (0,0,0)`, проекция ляжет поверх тех же клеток.

Для каждого кандидата:

- `compute_offset_for_target()` (`align_clone_projection.py:1005`, `align_clone_projection_small.py:1207`) считает `ProjectionOffset`, чтобы projected merge попал в `target_merge` с учётом `--anchor-mode`:
  - `projector-block` (по умолчанию) — Min блоков отсчитываются от projector-блока внутри чертежа;
  - `projector-origin` — от (0,0,0) внутри чертежа;
  - `grid-origin` — от grid origin.
- Считается **collision score** — сколько Min-ячеек клона пересекутся с живыми блоками. **v20:** `count_projected_min_cell_collisions()` (`align_clone_projection_small.py:1899`) делает это после применения `add_vec3i()` (`align_clone_projection_small.py:1088`) с учётом `projector_ui_origin_correction` — т.е. учитывает реальный UI-сдвиг.
- Считается **center score** — расстояние от центра клона до центра живого грида (на случай равных коллизий выбираем клон подальше).

Лучший кандидат: минимум коллизий → максимум center score → детерминированный порядок нормали.

### 7. Запекание контакта в XML (placement-apply=xml, по умолчанию)

> **Это самая тонкая часть — почему нельзя просто сдвинуть ProjectionOffset.**

`align_clone_projection.py:2271-2330` (v17) и `align_clone_projection_small.py` фаза 7 (v20) объясняют это в комментарии: **Space Engineers игнорирует абсолютный сдвиг всего чертежа**. Если сдвинуть Min у всех блоков включая projector-блок, проекция всё равно отрисуется относительно живого projector'а. Поэтому `placement-apply=xml` (по умолчанию) работает иначе:

1. `baked_relative_shift = placement.offset` — берём посчитанный сдвиг.
2. `shift_blueprint_blocks()` (`align_clone_projection.py:1648`, `align_clone_projection_small.py:1868`) сдвигает **все блоки, кроме anchor projector**, на `baked_relative_shift` внутри самого XML.
3. Anchor projector остаётся на месте, поэтому SE-движок рисует остальную геометрию относительно него — ровно туда, куда нужно.
4. `projector_offset` остаётся `(0, 0, 0)` (не двигаем UI offset). **v20: если UI origin correction активна — projector_offset оставляется `(-1, -1, 0)` для SmallProjector, и `embed_projector_transform()` (`align_clone_projection_small.py:1856`) запекает это в XML.**

Это **единственный надёжный путь** для клона рядом с текущим кораблём. `placement-apply=offset` оставлен для диагностики и требует, чтобы у SE-плагина был `ProjectionMatrix` для калибровки UI-осей (`calibrate_projector_offset_axes()`, `align_clone_projection.py:1771`, `align_clone_projection_small.py:2009`).

**v20-only: projector UI origin correction.** `default_projector_ui_origin_correction()` (`align_clone_projection_small.py:1066`) возвращает `(-1, -1, 0)` для SmallProjector и `(0, 0, 0)` для LargeProjector. `resolve_projector_ui_origin_correction()` (`align_clone_projection_small.py:1080`) мерджит это с `--projector-ui-correction=...` и `--no-small-projector-correction`. Финальный сдвиг: `projector_offset = base_offset + ui_origin_correction` через `add_vec3i()`.

### 8. Очистка, загрузка, проверка

1. `clear_existing_projector_blueprint()` (`align_clone_projection.py:1461`, `align_clone_projection_small.py:1678`) — пытается `clear_projection`/`delete_projection`/`clear_blueprint`/`reset_projection`, после каждой попытки читает телеметрию. Критерий успеха: `total/remaining/buildable == 0` и `isProjecting == False`. Сбрасывает offset/rotation в (0,0,0). С `--skip-clear-existing` пропускается.
2. `embed_projector_transform()` (`align_clone_projection.py:1636`, `align_clone_projection_small.py:1856`) — вписывает `ProjectionOffset`/`ProjectionRotation` в **каждый** projector-блок внутри XML (на случай, если SE-плагин читает их из блоков). **v20:** дополнительно запекает `projector_ui_origin_correction` для anchor projector'а.
3. `finalize_blueprint()` (`align_clone_projection.py:1231`, `align_clone_projection_small.py:1448`) — ставит `DisplayName`, `Id/Type/Subtype`, дописывает `xmlns:xsd`, сериализует в UTF-8.
4. `output_path` — `--output` или `<display_name>.sbc` рядом со скриптом.
5. `projector.set_enabled(True)` + `load_blueprint_xml(xml, keep=args.keep)`.
6. `apply_projector_transform()` (`align_clone_projection.py:1571`, `align_clone_projection_small.py:1791`) — `set_flags(keep=True, align_grids=False, lock_projection=False, use_adaptive_offsets=False, use_adaptive_rotation=False)`, потом `set_rotation()`, потом `set_offset()`. На каждый шаг `wait_for_*()` опрашивает телеметрию. Если `set_offset` не подтвердился, делает fallback на `move_offset(delta)`, потом raw-payload.
7. Финальный `print` телеметрии: `isProjecting`, `projectedGridName`, `offset`, `rotation`, `totalBlocks`, `remainingBlocks`, `buildableBlocks`.

---

## Главный кейс: сборка клона напротив merge-блока

Условия:

- На `skynet-farpost0` есть **Merge Block + Connector**, смотрящие в нужную сторону. Если они на субгриде ротора — `grid_report.py skynet-farpost0` всё равно их увидит.
- Чертеж `bp.sbc` экспортирован из `skynet-scout0` (или совместимого) и лежит в `Blueprints/local/skynet-scout0/bp.sbc`.
- На этом гриде (или субгриде) есть Projector, направленный в ту же сторону, где хотим клона.

Шаги:

```bash
# 1. Убедиться, что farpost0 — главный грид с projector'ом
C:\Python311\python.exe docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py skynet-farpost0 | grep -i projector

# 2. Запустить сборку на малом проекторе
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection_small.py skynet-farpost0 "C:\Users\root\AppData\Roaming\SpaceEngineers\Blueprints\local\skynet-scout0\bp.sbc" --normal=auto --projector-subtype=SmallProjector
```

Что произойдёт (по логам скрипта):

```text
SCRIPT_VERSION: align-clone-projection-offset-v20-small-projector-ui-origin-correction-2026-06-08
Blueprint file: C:\...\bp.sbc
Grid step: 0.5 m
Projector: None (<eid>) at (0, 1, 1)
Projector UI origin correction: (-1, -1, 0) (auto SmallProjector)
Contact axis: z
Pre-flip around contact line: True
Rotation mode: xml block transform
Contact normal: (-1, 0, 0)
Target merge:    (-1, 3, 1)
Target connector:(-1, 3, 0)
ProjectionOffset to apply: (-1, 5, 3)
XML relative shift applied to non-anchor blocks: (-1, 5, 3)
Projector UI offset kept for model-origin correction: (-1, -1, 0)
XML shifted blocks: 18; anchor projector kept at (0, 1, 1)
Prepared blueprint saved: bp-contact-clone-offset.sbc
Projection loaded, projector enabled, offset applied.
```

Скрипт автоматически выберет `contact_gap=1`, pre-flip вокруг Z, сдвиг `(-1, 5, 3)`, оставит anchor projector на `(0, 1, 1)`. Готовый XML сохранится рядом как `bp-contact-clone-offset.sbc`.

### Если merge/connector в чертеже смотрят не туда

Скрипт на это не ругается — он только требует, чтобы **live-пара** была осе-выровненной. Но визуально клон может оказаться перевёрнутым. В этом случае:

- `--no-preflip` — отключить зеркалирование 180° вокруг контактной линии (используй, если хочешь клон по ту же сторону, а не напротив).
- `--contact-mode=overlay` — положить клон поверх тех же клеток, что merge+connector (например, для сварки в той же позиции).
- `--manual-offset=0,0,1` — заставить UI offset быть фиксированным (но **только вместе с placement-apply=offset**, иначе XML-relative уже зафиксировал позицию).
- `--manual-rotation=2,0,0` — задать `ProjectionRotation` в шагах по 90° (например, `2` = 180° вокруг X).
- `--blueprint-projector-min=0,1,0` — вручную указать Min projector-блока внутри чертежа, если он не парсится.

### Если в чертеже несколько projector'ов

`choose_blueprint_projector_block()` (`align_clone_projection.py:909`, `align_clone_projection_small.py:1110`) выберет первый с `Min`. Чтобы выбрать конкретный — дай ему `CustomName` и используй `--contact-tag` или исправь blueprint вручную.

---

## Полезные опции (v17 + v20)

| Флаг | Скрипт | Что делает |
|---|---|---|
| `--projector-name="front_proj"` | оба | Взять projector, в имени которого есть подстрока |
| `--projector-subtype=SmallProjector` | оба | Фильтр по subtype проектора (нужен когда на гриде несколько) |
| `--contact-tag="clone"` | оба | Фильтровать merge/connector по подстроке в имени/subtype/entity_id |
| `--contact-gap=2` | оба | Зазор между merge-блоками (по умолчанию 1) |
| `--contact-mode=overlay` | оба | Положить клон поверх, а не рядом |
| `--no-preflip` | оба | Не зеркалить 180° вокруг линии контакта |
| `--rotation-mode=projector` | оба | Вместо XML-трансформа использовать `ProjectionRotation` (только для диагностики, требует `--placement-apply=offset`) |
| `--no-calibrate-offset-axes` | оба | Пропустить калибровку UI-осей через `ProjectionMatrix` (по умолчанию уже выключено: на dedicated server матрица недоступна) |
| `--no-upload` | оба | Только сгенерировать XML, не загружать в проектор |
| `--offline` | оба | Без Redis/игры, target = blueprint-пара (для отладки геометрии) |
| `--keep` | оба | Передать `keep=True` в `load_blueprint_xml` (не сбрасывать текущую проекцию) |
| `--skip-clear-existing` | оба | Не очищать текущую проекцию перед загрузкой |
| `--skip-reset` | оба | Не вызывать `reset_projection` перед загрузкой |
| `--output=clone.xml` | оба | Куда сохранить готовый XML |
| `--display-name="My Clone"` | оба | Имя в `DisplayName` готового XML |
| `--projector-ui-correction=-1,-1,0` | v20 | Ручная коррекция UI origin (по умолчанию авто для SmallProjector) |
| `--no-small-projector-correction` | v20 | Отключить автокоррекцию (если уже учтена вручную) |
| `--projector-forward=Forward` | v20 | Зафиксировать Forward-ось проектора |
| `--projector-up=Up` | v20 | Зафиксировать Up-ось проектора |
| `--ignore-projector-orientation` | v20 | Полностью игнорировать ориентацию проектора (identity axes) |

### Redis-память чертежей

Оба скрипта умеют кешировать подготовленные XML в Redis (по умолчанию `se:<owner>:memory:projection_blueprints`):

```bash
# Сохранить XML из файла в Redis
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection.py skynet-farpost0 "C:\...\bp.sbc" --redis-save-file=myclone

# Выгрузить чертеж из живого projector'а и сохранить в Redis
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection.py skynet-farpost0 --redis-save-grid=myclone

# Использовать сохранённый чертёж при следующей сборке
C:\Python311\python.exe C:\secontrol\examples\organized\projector\align_clone_projection.py skynet-farpost0 --redis-load=myclone --normal=-z

# Список / удаление / экспорт
... --redis-list
... --redis-delete=myclone
... --redis-export=myclone ./myclone.sbc
```

---

## Что скрипт **не** делает

- **Не сваривает клон.** Сварка — отдельный шаг через welder (`docs/EXAMPLES.md:398-404`).
- **Не двигает живой корабль.** Корабль-источник должен стоять на месте; скрипт только позиционирует голограмму.
- **Не проверяет, что у игрока есть лицензия/права на проектор.** Ошибки доступа придут в телеметрии.
- **Не поддерживает множественные live merge-connector пары.** Скрипт выбирает ближайшую пару по Manhattan-расстоянию; для нестандартных раскладок используй `--contact-tag`.

---

## Типичные ошибки

| Сообщение | Причина | Решение |
|---|---|---|
| `blueprint does not contain a Merge Block contact candidate` | В чертеже нет Merge Block | Добавь merge в исходный корабль и пересохрани |
| `live merge/connector pair was not found from telemetry` | На живом гриде нет пары, либо она отключена | Включи merge/connector на источнике |
| `live contact pair must be axis-aligned, got vector (...)` | Merge и connector на живом гриде не на одной оси | Разнеси их ровно на 1 клетку по X/Y/Z |
| `cannot rotate blueprint contact vector ... to live contact vector` | Blueprint-вектор и live-вектор разной длины | Manhattan-расстояние между merge и connector должно совпадать в обоих |
| `no placement candidates were generated` | `--normal` не перпендикулярен контактной оси | Используй `auto` или нормаль, перпендикулярную линии merge↔connector |
| `WARNING: projector offset still not confirmed` | SE-плагин не подтвердил offset по телеметрии | Обычно безопасно — XML-relative сдвиг уже зафиксирован, проверь визуально |
| `ERROR: ... grid/projector connection is not available` | Redis не отвечает или грид не найден | Проверь `.env` (`REDIS_USERNAME`/`REDIS_PASSWORD`) и `grid_report.py` |
| Клон сдвинут на 1 клетку от ожидаемой позиции | Запущен v17 на SmallProjector | Перезапусти через `align_clone_projection_small.py` с `--projector-subtype=SmallProjector` |
| `Projector orientation unavailable; using identity grid axes` | Телеметрия не вернула forward/up проектора | Убедись, что Projector включён (`isWorking=True`); для принудительного прогона добавь `--ignore-projector-orientation` |

---

## Сводка функций v17 и v20

### v17 (`align_clone_projection.py`, 2380 строк)

| Функция | Строка |
|---|---|
| `resolve_blueprint_path` | 383 |
| `parse_blueprint` | 442 |
| `grid_step_from_blueprint` | 466 |
| `choose_blueprint_pair` | 598 |
| `choose_live_pair` | 621 |
| `rotate_180_around_axis` | 700 |
| `prepare_blueprint_geometry` | 777 |
| `find_projector` | 837 |
| `_projector_subtype` | 856 |
| `choose_blueprint_projector_block` | 909 |
| `compute_offset_for_target` | 1005 |
| `choose_placement` | 1021 |
| `choose_placement_projector_rotation` | 1136 |
| `finalize_blueprint` | 1231 |
| `clear_existing_projector_blueprint` | 1461 |
| `apply_projector_transform` | 1571 |
| `embed_projector_transform` | 1636 |
| `shift_blueprint_blocks` | 1648 |
| `calibrate_projector_offset_axes` | 1771 |
| `build_arg_parser` | 1880 |
| `main` | 1928 |

### v20 (`align_clone_projection_small.py`, 2703 строки)

| Функция | Строка | Назначение |
|---|---|---|
| `parse_axis_direction` | 340 | Парсит строку `+x`/`-z`/etc в `Vec3i` |
| `live_block_orientation` | 414 | Читает forward/up живого блока из телеметрии |
| `projector_axis_transforms` | 434 | Считает `forward_axis`/`up_axis` для проектора |
| `parse_direction_arg` | 466 | Парсит CLI-аргумент `--projector-forward=` |
| `resolve_blueprint_path` | 520 | см. v17 |
| `parse_blueprint` | 579 | см. v17 |
| `grid_step_from_blueprint` | 603 | см. v17 |
| `collect_missing_projector_min_elements` | 677 | Собирает CubeBlock без `Min` рядом с проектором (fixed anchor) |
| `choose_blueprint_pair` | 758 | см. v17 |
| `choose_live_pair` | 781 | см. v17 |
| `rotate_180_around_axis` | 860 | см. v17 |
| `prepare_blueprint_geometry` | 937 | см. v17 |
| `find_projector` | 1011 | см. v17 (берёт из `live_by_entity_map`) |
| `_projector_subtype` | 1030 | см. v17 |
| `default_projector_ui_origin_correction` | 1066 | `(-1, -1, 0)` для SmallProjector, `(0, 0, 0)` для Large |
| `resolve_projector_ui_origin_correction` | 1080 | Мердж explicit/disable/default |
| `add_vec3i` | 1088 | Векторное сложение `Vec3i + Vec3i` |
| `choose_blueprint_projector_block` | 1110 | см. v17 |
| `compute_offset_for_target` | 1207 | см. v17 |
| `choose_placement` | 1226 | см. v17 |
| `choose_placement_projector_rotation` | 1349 | Учитывает реальную ориентацию проектора |
| `finalize_blueprint` | 1448 | см. v17 |
| `clear_existing_projector_blueprint` | 1678 | см. v17 |
| `apply_projector_transform` | 1791 | см. v17 |
| `embed_projector_transform` | 1856 | Запекает `projector_offset + ui_origin_correction` |
| `shift_blueprint_blocks` | 1868 | см. v17 |
| `count_projected_min_cell_collisions` | 1899 | Коллизии с учётом `ui_origin_correction` |
| `calibrate_projector_offset_axes` | 2009 | см. v17 |
| `main` | 2182 | Точка входа |
