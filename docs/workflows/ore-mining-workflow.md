# Сбор руды — Nanobot Drill Mining Workflow

## Быстрый старт

### 1. Сканирование руды

```bash
python examples/organized/radar/ore_deposit_scanner.py --grid skynet-baza0 --radius 500
```

Вывод: руды с GPS-координатами и кластерами.

### 2. Добыча (одной командой)

```python
from secontrol import Grid
from secontrol.devices.nanobot_drill_system_device import NanobotDrillSystemDevice

grid = Grid.from_name("skynet-baza0")
drill = grid.find_devices_by_type(NanobotDrillSystemDevice)[0]

# Только Nickel — без камня
drill.start_drilling_ore(["Nickel"])
```

Для нескольких руд:
```python
drill.start_drilling_ore(["Nickel", "Silicon"])
drill.start_drilling_ore(["Uranium"])
```

## Как это работает

`start_drilling_ore` делает всё сам:
1. `stop_drilling()` + `turn_off()`
2. `set_script_controlled(True)`
3. `set_collect_filter(["Ore"])` — не `["all"]`, иначе берёт камень
4. `set_ore_filters(ore_subtypes, work_mode="Collect")`
5. `set_work_mode("Collect")`
6. `set_script_controlled(False)`
7. `turn_on()`

## Проверка

```python
drill.update()
print("work mode:", drill.get_work_mode())
print("known ores:", drill.debug_get_enabled_known_ores())
```

Должно быть: `work mode: Collect`, нужный `ore: True`, остальные `False`.

## Важно

- **Не** использовать `drill.start_drilling()` (режим Drill)
- **Не** использовать `drill.set_collect_filter(["all"])`
- OreHash: Stone=1137917536, Ice=1579040667, Iron=2112235764, Nickel=-723128632, Silicon=-122448462, Cobalt=-2115209756, Magnesium=2104309205, Silver=1033257407, Gold=-496794321, Platinum=-510410391, Uranium=1880922462

## Drill area

Drill area — 75×75×75m (радиус ~37.5m). Работает на расстоянии 50m+ от руды. Offset обычно не нужен — работает "как есть".

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Targets=0 | Проверить `surfaceDistance=0` в asteroidIndex — корабль должен быть на астероиде |
| ScriptControlled=True | `set_script_controlled(False)` |
| Бур берёт лишнее | Использовать `start_drilling_ore(["Руда"])` — фильтрует камень |
| Drill state corruption | Полный reset: stop→off→offsets=0→WorkMode=Collect→on→start |