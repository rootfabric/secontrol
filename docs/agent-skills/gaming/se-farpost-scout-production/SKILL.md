---
name: se-farpost-scout-production
description: Полный цикл постройки малого скаута на проекторе верфи skynet-farpost0 - проверка материалов, производство компонентов ассемблером, нормализация чертежа, загрузка проекции через align_clone_projection_small (v20), контроль сварки NanobotBuildAndRepair через Redis-телеметрию субгрида, диагностика отказа наноботов подхватывать цель. Использовать, когда оператор говорит "построй скаут", "сделай еще один скаут", "новый корабль на фарпосте".
---

# SE Farpost Scout Production — конвейер постройки скаута на верфи фарпоста

Проверено в реальной сессии (2026-08). Производит малый скаут из чертежа `skynet-scout0`
на субгриде-верфи (`Small Grid 9079`, id `76868735630219079`) базы `skynet-farpost0`.

## 0. Ключевые факты об объектах

| Объект | Значение |
|---|---|
| База | `skynet-farpost0`, id `80828718952705651` |
| Верфь (субгрид ротора) | `Small Grid 9079`, id `76868735630219079`, 7 блоков |
| Проектор верфи | SmallProjector, eid `93838598837956066`, **на субгриде** |
| Наноботы | SELtdLargeNanobotBuildAndRepairSystem eid `95032828151954712`, **на базе** |
| Merge/Connector пары | на верфи и в чертеже скаута |
| Чертёж | `%APPDATA%\SpaceEngineers\Blueprints\local\skynet-scout0\bp.sbc` (19 блоков) |
| Большой проектор базы `Projector` | **НЕ принимает загрузки** (load_blueprint_xml и load_prefab молча игнорируются плагином) — не тратить время |
| Второй "welder" в configure_welding | это Survival Kit, не наноботы |

**Важно:** телеметрия устройств субгрида лежит в Redis-ключах с `grid:<СУБГРИД-id>`, а не базы:

```text
se:<owner>:grid:76868735630219079:projector:93838598837956066:telemetry
```

`FleetRedisReader._discover_telemetry('skynet-farpost0')` устройства субгрида НЕ находит.
Прямое чтение ключа — самый надёжный способ контролировать проекцию.

## 1. Проверка материалов (read-only)

Чертежи, экспортированные из живых гридов, содержат только частичные `<Components>`
(например 9 из 27), поэтому точную потребность считать по XML бесполезно.
Авторитетные источники:

1. Рецепты компонентов — через игровой API ассемблера:
   `AssemblerDevice.blueprint_requirements(bp, amount)`.
2. Факт сбориваемости — `buildableBlocks` в телеметрии проектора после загрузки.
3. Динамика недостачи — `buildandrepair_missingcomponents` в телеметрии наноботов.

Типовая потребность scout0 покрывается запасами фарпоста (железо/кобальт/никель/кремний).
Компонент `Thrust` требует золото+платину — на фарпосте их нет, но атмосферным
двигателям скаута он не нужен.

## 2. Производство компонентов (если пусто)

ВАЖНО: `production_check()` и `inventory()` падают в текущем чекауте
(`'ContainerDevice' object has no attribute 'get_inventory'`) — класть в очередь напрямую,
минуя проверку, и проверять факт чтением очереди:

```python
asm.add_queue_item_verified("Construction", 150, timeout=8.0)
# ...
print(asm.queue())   # read-after-write
```

Рецепты (игровые, для планирования слитков): Construction x150 = Fe 1200;
MetalGrid x80 = Fe 960 + Ni 400 + Co 240; Computer x25 = Fe 12.5 + Si 5.
Полный набор для одного скаута: Construction 150, MetalGrid 80, InteriorPlate 40,
Computer 25, Detector 4, Motor 6, SmallTube 30, LargeTube 8, Display 4, RadioComm 4.
Ассемблер фарпоста производит этот набор за несколько минут.

## 3. Нормализация чертежа

`load_blueprint_xml` требует элемент `<MyObjectBuilder_ShipBlueprintDefinition>`.
Сырой файл из Blueprints/local имеет корень `<Definitions><ShipBlueprints><ShipBlueprint ...>`.
Нормализация без изменения геометрии — переименование корня (см. скрипт нормализации в tmp).

## 4. Загрузка проекции (канонический v20)

```bash
python examples/organized/projector/align_clone_projection_small.py \
    skynet-farpost0 "%APPDATA%/SpaceEngineers/Blueprints/local/skynet-scout0" \
    --normal=auto --projector-subtype=SmallProjector
```

Успех: в конце вывода `isProjecting: True`, `totalBlocks: 19` (если 27 — артефакт старого
состояния: `clear_projection()` и перегрузить), `remainingBlocks == totalBlocks`.
Предупреждения `rotation/offset was not confirmed` безопасны — геометрия запечена в XML.

### Проверка после загрузки (v44, реальная сессия 2026-08-27)

Плагин публикует телеметрию проектора верфи В ДВА ключа, и они расходятся:

```text
se:<owner>:grid:80828718952705651:projector:<eid>:telemetry   ← база: УСТАРЕВШИЙ слепок (не обновляется)
se:<owner>:grid:76868735630219079:projector:<eid>:telemetry   ← субгрид: СВЕЖИЙ (читать этот)
```

Устройство из `prepare_grid('skynet-farpost0')` подписано на **базовый** (старый) ключ,
поэтому все WARNING'и скрипта про `not confirmed` — артефакт чтения не того ключа.
Реальные критерии успеха (субгридовый ключ + `projectionReport`):

- `hasCachedBlueprint: true`, `ready: true`;
- `projectedBlockCount: 19`, `missingBlockCount: 18`, `buildableBlocks >= 1`;
- `offset == ProjectionOffset to apply`, `rotation == ProjectionRotation to apply`.

Поле `isProjecting` в этой сборке остаётся `false`, даже когда голограмма реально
отображается (19 проекционных блоков в отчёте) — НЕ использовать как признак успеха.
`--strict-contact-verify PASS` от v44 скрипта + свежий субгридовый ключ — надёжная пара.

## 5. Контроль сварки (наноботы на базе)

Телеметрия наноботов обновляется только по запросу:

```python
welder.send_command({"cmd": "request_full_telemetry", "payload": {}})
```

Ключевые поля: `buildandrepair_possibletargets`, `buildandrepair_currenttarget`,
`buildandrepair_missingcomponents`, `buildandrepair_allowbuild`, area-offset/size.

Настройка (через `{'cmd':'set','payload':{'property':'BuildAndRepair.X','value':v}}`):
Mode=1, WorkMode=1, AllowBuild=true, WeldOptionFunctionalOnly=false (иначе пропускает
структурные блоки), AreaWidth/Height/Depth=200 (потолок мода), AreaOffset* — смещение коробки зоны.

## 6. ИЗВЕСТНАЯ ПРОБЛЕМА: цель видна, но не подхватывается

Симптом: `possibleTargets` содержит проекционный `Small Merge Block`, но
`currentTarget=None` часами; сварка не начинается; `missingcomponents={}`.

Что проверено и НЕ является причиной: наличие компонентов, isProjecting,
AllowBuild/WeldOptionFunctionalOnly, режимы Mode/WorkMode/WeldMode (0/1+WeldOnly_On),
рестарт блока, размер зоны (клампится к 200), большой проектор (мёртв для загрузок).

Вердикт свипа 2026-08: перебор всех 8 углов AreaOffset (+центр) при загруженной проекции -
цель листится ТОЛЬКО при offset=(0,0,0), подхват (currentTarget) не происходит НИ РАЗУ.
Флаг instantBuild=true проектор принимает, но в выживании блоки сам не спавнит.
Вывод: форк наноботов не берёт проекционные цели в работу; реальные поврежденные блоки
при этом варит нормально (ремонт турели прошёл). Требуется игрок или админ.

Процедуры-кандидаты:
1. Свип углов `AreaOffset` (±100 по трём осям) при загруженной проекции (tmp/sweep_area.py).
2. Ручная приварка первого блока игроком-сварщиком у merge-точки верфи — после старта
   наноботы обычно подхватывают остальное.
3. Просмотр терминала BaR в игре админом (логи мода видны только там).

Историческая конфигурация offsets (-100,+100,-100) — вероятно, была настроена под точку
сборки; при ней сейчас цель не листится вообще, при 0/0/0 — листится, но не подхватывается.

Дополнительно (сессия 2026-08, вторая половина):
- Геометрия v44 (forward-contact) кладёт проекционный merge в (0,4,1) НАД live merge (0,3,1),
  коннектор над коннектором — пары лицом к лицу, lock должен щёлкать автоматически.
- Merge и Connector верфи должны быть enabled (проверять: activate_shipyard_merge.py /
  activate_shipyard_connector.py из tmp сессии).
- Единственный успешный подхват цели случился при нулевой зоне И присутствии игрока у базы
  (вероятно, открытие терминала BaR форсирует перескан). Перезагрузки проекции, шевеление
  offset'ов и тумблеры сами по себе подхват не гарантируют.
- Первый сваренный блок висит свободно (он не касается ничего до lock) — отключать
  GrindJanitorNotOwned на время сборки, иначе жанитор может сгриндить якорь.
- Если remaining вдруг вернулся с N к total — якорный блок потерян: перезагрузить проекцию
  и повторить процедуру подхвата.

## 7. После сварки (шаги 4-6 пайплайна se-grid-build-pipeline)

```bash
python docs/agent-skills/gaming/se-grid-creation/scripts/enable_merge_blocks.py skynet-farpost0 --size small
python docs/agent-skills/gaming/se-grid-creation/scripts/enable_connectors.py skynet-farpost0 --size small
python docs/agent-skills/gaming/se-grid-creation/scripts/disable_merge_blocks.py skynet-farpost0   # >>> NEW GRID ID
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/rename_new_grid.py --auto-new skynet-scout6
python docs/agent-skills/gaming/se-grid-build-pipeline/scripts/undock_new_grid.py skynet-scout6 --distance 1000
```

Для отгона на 1 км: `undock_new_grid.py --distance 1000`; если импульсов не хватит —
повторять запуск до достижения дистанции (батарея нового грида может быть auto-disabled —
скрипт включает её сам). Проверка полётности: `check_flight_ready.py <grid>`, движение —
по position delta (FLIGHT_DIAGNOSTIC_RULES: статичная телеметрия не доказательство).

## 8. Порядок именования

Следующие свободные имена: `skynet-scout6`, `skynet-scout7`, ... (scout0-5 заняты,
scout5 жив в поле). Переименование сразу после detach, до отгона.