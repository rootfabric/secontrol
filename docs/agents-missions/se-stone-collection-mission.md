# SE Stone Collection Mission — добыча камня

## Назначение

Этот сценарий используется, когда пользователь просит добыть Stone/камень.

Stone не требует поиска рудной жилы. Для добычи Stone достаточно любого доступного вокселя, на который можно навести область Nanobot Drill.

## Миссия по умолчанию

```text
grid: rover
material: Stone
amount: 100000
amount_unit: kg
```

## Главные правила

1. Stone — не обычная руда для SharedMap-поиска.
2. Не ищи `Stone deposit` как обязательное условие.
3. Любой voxel подходит для добычи Stone.
4. Основное действие — навести Nanobot area на voxel и поставить `CollectFilter=Stone`.
5. Не считай Stone загрязнением, если пользователь попросил добывать Stone.
6. Не требуй Remote Control, Beacon или Connector для добычи на месте.
7. Не требуй Cargo Container как обязательный блок. Проверяй все доступные инвентари грида.
8. Если Nanobot Drill выключен — попробуй включить его через Nanobot/terminal command и затем перечитай телеметрию.
9. Не объявляй hard-block только по `enabled=false`. Сначала сделай `command -> wait -> read-back`.
10. Если грид не летает, но стоит рядом с вокселем, это не мешает добыче Stone.

## Краткий план агента

```text
1. Resolve target grid.
2. Inspect Nanobot Drill.
3. Inspect available inventories.
4. Find or confirm any nearby voxel.
5. Aim Nanobot area at voxel.
6. Configure Collect mode with Stone filter.
7. Start Nanobot Drill.
8. Monitor Stone inventory delta.
9. Stop when target amount is reached or inventory is full.
10. Report result.
```

## Команды диагностики

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py rover
```

Проверь:

- есть ли Nanobot Drill;
- есть ли cockpit/cargo/connector/refinery/assembler/Nanobot inventory;
- есть ли питание;
- рядом ли voxel/asteroid/planet surface.

## Команда добычи, если текущий скрипт уже поддерживает Stone mode

```bash
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py \
  --grid rover \
  --ore Stone \
  --amount 100000 \
  --area-size 75 \
  --scan-radius 500 \
  --startup-timeout 90 \
  --no-progress-timeout 60 \
  --working-point-min-seconds 180 \
  --check-interval 0.5 \
  --stone-safety-delta -1 \
  --max-stone-per-ore-ratio -1 \
  --powered-trial-on-wrong-targets
```

## Важное предупреждение

Если скрипт всё ещё использует `CollectFilter=Ore`, он может быть непригоден для Stone без доработки.

Для Stone правильный режим:

```text
WorkMode = Collect
CollectFilter = Stone
Stone safety = disabled
Stone/Ore ratio safety = disabled
```

Если скрипт останавливается с сообщениями вида:

```text
SAFETY STOP: point Stone ...
SAFETY STOP: Stone/Ore ratio ...
only non-Stone targets ...
```

это не значит, что камень нельзя добыть. Это значит, что запущен рудный режим, где Stone считается ошибочной примесью.

## Что считать успехом

Успех:

```text
Stone inventory increased by requested amount
```

или:

```text
Stone добывается, но доступный инвентарь заполнен
```

В финальном отчёте указать:

```text
- grid: rover
- material: Stone
- target amount: 100000 kg
- mined Stone delta: ...
- inventory status: enough/full/unknown
- Nanobot status: running/stopped
- last successful command: ...
```

## Запрещено

Не делать так как обязательный шаг:

```bash
python examples/organized/radar/shared_map/shared_map_deposits.py --grid rover --material Stone --clusters --gps
```

Не писать:

```text
Stone не найден в SharedMap, миссия невозможна.
```

Правильно:

```text
Stone добывается из любого voxel. Нужно навести Nanobot area на воксель и включить фильтр Stone.
```
