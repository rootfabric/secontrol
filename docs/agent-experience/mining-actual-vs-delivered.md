# Mining: actual vs delivered — где теряется руда

## Симптом

`mine_ore_robot_safe_live_move.py` рапортует `+50278.4 кг Gold`, но на
базе оказывается только 37 799 кг Gold Ore. Потери ~25%.

## Возможные причины (по убыванию вероятности)

### 1. Mining скрипт считает "mined", не "in container"

В логе mining:
```
[60.5s] Gold: mined+45535.1/50000.0, PointOre+45535.1, OreInv=34151.4, ...
```

`PointOre` = добыто с текущей точки (45 535 кг).
`OreInv` = в инвентаре (34 151 кг).
Разница 11 384 кг.

Скрипт завершается по `mined+`, не по `OreInv+`. То есть часть руды
в момент остановки была "в процессе" — в detector'е, в процессе
конвейерной передачи, в буфере Refinery.

### 2. Refinery поглотил часть

На корабле Basic Refinery. Если руда попала в Refinery output —
она превращается в Gravel, а Gold — частично в Gold Ingot
(но не 100% recovery).

В dry-run перед pull:
```
>>> Basic Refinery (output)  [refinery]
    20 x MyObjectBuilder_Ingot:Gravel
    42 x MyObjectBuilder_Ingot:Iron Ingot
    3 x MyObjectBuilder_Ingot:Nickel Ingot
    6 x MyObjectBuilder_Ingot:Silicon Wafer
```

Тут Gold нет. Но Refinery мог обработать часть золота в Gold Ingot.

### 3. Потери при server reboot

Между mining и pull произошла перезагрузка сервера. Возможно,
часть буфера Refinery потерялась (SE сохраняет inventory, но
процессинг Refinery при reboot может быть сброшен).

### 4. Потери при pull

`pull_from_attached_ships.py` упал на Unicode в середине работы.
Возможно, часть руды не перенеслась. Но вторая попытка
`0 шт. перенесено` — это значит, что после первой попытки на корабле
уже не было контейнеров с Gold (либо перенеслось, либо упало).

Стоп: вторая попытка "0 контейнеров" — но dry-run сразу после dock
показал 24 895 кг Gold. Значит первая попытка **успела перенести
24 895 кг**, а на базе оказалось 37 799 — то есть ещё 12 904 кг
попало на базу из Refinery или другого пути.

## Рекомендация

После mining проверять **реальное количество в контейнерах**, а не
верить `mined+` счётчику:

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py skynet-agent0
```

И если есть расхождение > 5% — фиксировать в отчёте миссии.

## Долгосрочный fix

В скрипт mining добавить final-reconciliation:

```python
final_ore = get_container_ore_inventory(grid, ore_type)
script_reported = total_mined
loss_pct = (script_reported - final_ore) / script_reported * 100
log.info(f"Reconciliation: script={script_reported:.1f}, container={final_ore:.1f}, loss={loss_pct:.1f}%")
```

Это поможет понять реальные потери и улучшить скрипт.

## Альтернативный путь

Использовать Refinery с queue для переработки добытого золота
в Gold Ingot — Ingot имеет фиксированный 1:1 ratio и не теряется
в буфере. Но это меняет продукт (Ore → Ingot), и пользователь
просил именно Gold.
