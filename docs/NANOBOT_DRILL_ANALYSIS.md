# Nanobot Drill & Fill — Полный анализ API и возможностей

> Index: `AGENTS.md` — Добыча ресурсов | Quick start: `docs/agent-skills/gaming/secontrol-space-engineers/references/nanobot-drill-quickstart.md`

## Обзор

Nanobot Drill & Fill — это мод для Space Engineers, доступный через secontrol как 
`NanobotDrillSystemDevice`. Позволяет **бурить вокселы, собирать ресурсы и заполнять 
территорию** — всё через настройку зоны действия относительно корабля.

---

## 1. Зона действия (Area) — координаты относительно корабля

Дрилл работает в **локальных координатах корабля**. Зона — это 3D-куб вокруг дрона:

| Свойство | Ось (корабль) | Текущее значение | Описание |
|---|---|---|---|
| `Drill.AreaOffsetLeftRight` | X (право/лево) | `0.0 м` | Смещение вправо-влево |
| `Drill.AreaOffsetUpDown` | Y (вверх/вниз) | `44.0 м` | Смещение вверх-вниз |
| `Drill.AreaOffsetFrontBack` | Z (вперёд/назад) | `0.0 м` | Смещение вперёд-назад |
| `Drill.AreaWidth` | X | `25.0 м` | Ширина зоны |
| `Drill.AreaHeight` | Y | `25.0 м` | Высота зоны |
| `Drill.AreaDepth` | Z | `25.0 м` | Глубина зоны |

### Как задать координаты

Чтобы направить дрилл на **конкретную мировую точку**, нужно:

1. **Получить позицию и ориентацию корабля** из RemoteControl:
   ```python
   rc = grid.get_first_device(RemoteControlDevice)
   rc.update()
   pos = rc.telemetry["worldPosition"]       # {x, y, z}
   orientation = rc.telemetry["orientation"]  # {forward, up, right}
   ```

2. **Перевести мировые координаты → локальные**:
   ```python
   # target_world — мировая координата цели
   dx = target_world - ship_position
   
   # Проецируем на оси корабля:
   offset_front_back = dot(dx, ship_forward)   # вперёд/назад
   offset_up_down    = dot(dx, ship_up)         # вверх/вниз
   offset_left_right = dot(dx, ship_right)      # вправо/влево
   ```

3. **Задать смещение**:
   ```python
   drill.set_property("AreaOffsetUpDown", offset_up_down)
   drill.set_property("AreaOffsetLeftRight", offset_left_right)
   drill.set_property("AreaOffsetFrontBack", offset_front_back)
   ```

> **Примечание:** `AreaOffsetUpDown` работает как **положительное = вниз** (по гравитации). 
> При полёте на высоте 50м, ставят `AreaOffsetUpDown = 50.0`, чтобы зона достала до земли.

---

## 2. Режимы работы (`Drill.WorkMode`)

| Значение | Режим | Описание |
|---|---|---|
| `0` | **Fill** | Заполнение террейна (создание вокселей) |
| `1` | **Collect** | Сбор плавающих объектов (обломки, руда) |
| `2` | **Drill** | Бурение вокселов (добыча руды/камня) |

**⚠️ ВАЖНЫЙ БАГ в secontrol v0.3.0:** метод `set_work_mode()` имеет перепутанные значения:
```python
# НЕПРАВИЛЬНО (текущий код):
mode_map = {"drill": 1, "collect": 2, "fill": 0}  # drill отсылает 1 = Collect!

# ПРАВИЛЬНО:
mode_map = {"drill": 2, "collect": 1, "fill": 0}
```

**Workaround** — напрямую задать property:
```python
drill.set_property("WorkMode", 2)  # Drill
```

---

## 3. Авто-обнаружение целей (`Drill.PossibleDrillTargets`)

Дрилл **автоматически сканирует** вокселы в зоне действия. Результат:

```python
targets = props["Drill.PossibleDrillTargets"]
```

Каждая цель — массив из 5 элементов:
```
[0] = Описание: "MyVoxelPhysics {hash} Id=N OreType=volume (Dist=X, Min=[X,Y,Z], Max=[X,Y,Z])"
[1] = Voxel Object ID: "MyVoxelPhysics {hash}"
[2] = Расстояние от дрилла: float (метры)
[3] = Тип руды: "MyObjectBuilder_VoxelMaterialDefinition/MarsRocks"
[4] = Объём: float (единицы)
```

### Текущие цели на taburet3 (8 штук MarsRocks):

| # | Расстояние | Объём | Min координаты | Max координаты |
|---|---|---|---|---|
| 0 | 31.2 м | 3816 | (119, 485, 298) | (135, 506, 320) |
| 1 | 40.6 м | 1423 | (135, 485, 299) | (145, 506, 320) |
| 2 | 44.2 м | 2908 | (114, 488, 320) | (135, 506, 336) |
| 3 | 45.3 м | 3261 | (113, 506, 303) | (135, 525, 320) |
| 4 | 51.8 м | 1536 | (135, 506, 303) | (146, 521, 320) |
| 5 | 52.2 м | 1404 | (135, 489, 320) | (147, 506, 335) |
| 6 | 55.9 м | 2391 | (118, 506, 320) | (135, 525, 338) |
| 7 | 58.9 м | 627 | (135, 506, 320) | (146, 518, 334) |

> **Примечание:** Min/Max координаты — это воксельные координаты в пространстве воксельного 
> объекта, НЕ мировые координаты. Для перевода в мировые нужен `WorldMatrix` воксельной карты.

---

## 4. Текущая цель (`Drill.CurrentDrillTarget`)

Показывает, что дрилл **сейчас бурит**:
```
MyVoxelPhysics {85EBF5B0652B9CB} Id=1 MarsRocks=3816 (Dist=31.24, Min=[119,485,298], Max=[135,506,320])
```

---

## 5. Управление фильтрами руд

### OreFilter (для режима Drill):
```python
drill.set_ore_filter("Iron")           # Только железо
drill.set_ore_filters(["Iron", "Nickel"])  # Железо + никель
drill.clear_ore_filters()              # Отключить все
```

### SetCollectEnabled (для режима Collect):
```python
drill.set_collect_filter(["Stone", "Iron"])
```

Известные хеши руд:
```
stone=1137917536, ice=1579040667, iron=2112235764, nickel=-723128632,
silicon=-122448462, cobalt=-2115209756, magnesium=2104309205,
silver=1033257407, gold=-496794321, platinum=-510410391, uranium=1880922462
```

---

## 6. Прочие настройки

| Свойство | Текущее | Описание |
|---|---|---|
| `Drill.ScriptControlled` | `False` | Если True — мод управляется скриптом, False — работает автономно |
| `Drill.ShowArea` | `True` | Показывать зону действия в игре |
| `Drill.TerrainClearingMode` | `True` | Очистка террейна (удаляет вокселы полностью) |
| `Drill.UseConveyor` | `?` | Использовать конвейерную систему |

---

## 7. Действия (Actions)

Через `drill.run_action("...")`:

| Действие | Описание |
|---|---|
| `OnOff_On` / `OnOff_Off` | Включить/выключить |
| `Drill_On` / `Drill_Off` | Запустить/остановить бурение |
| `Collect_On` | Запустить сбор |
| `Fill_On` | Запустить заполнение |
| `AreaOffsetUpDown_Increase` / `_Decrease` | Шаговое изменение смещения вверх/вниз |
| `AreaOffsetLeftRight_Increase` / `_Decrease` | Шаговое изменение смещения вправо/влево |
| `AreaOffsetFrontBack_Increase` / `_Decrease` | Шаговое изменение смещения вперёд/назад |
| `AreaWidth_Increase` / `_Decrease` | Изменение ширины зоны |
| `AreaHeight_Increase` / `_Decrease` | Изменение высоты зоны |
| `AreaDepth_Increase` / `_Decrease` | Изменение глубины зоны |
| `ShowArea_On` / `ShowArea_Off` | Показать/скрыть зону |
| `TerrainClearingMode_On/Off` | Вкл/выкл режим расчистки |

---

## 8. Примеры из проекта

### Простой Drill (examples/organized/basic/intermediate/nanobot_drill_filter_example.py):
```python
drill.set_ore_filters(["Uranium", "Iron"])
drill.turn_on()
drill.start_drilling()
time.sleep(6)
drill.stop_drilling()
```

### Навигация к ресурсу + Drill (examples/organized/autopilot/harvest/simple_nano_focus_to_res.py):
```python
# 1. Найти ресурс через RadarController
controller = SurfaceFlightController("taburet2")
controller.load_map_region(radius=400)
nearest = controller.find_nearest_resources(search_radius=400)
resource_point = nearest[0]["position"]

# 2. Перелететь к нему
controller.lift_drone_to_point_altitude(resource_point, 50.0)

# 3. Настроить зону дрилла на глубину (от высоты полёта)
drill.set_property("AreaOffsetUpDown", 50.0)  # вниз на 50м

# 4. Запустить бурение
drill.turn_on()
```

### Полный цикл (examples/organized/autopilot/harvest/harvest_full.py):
1. Отстыковка от базы
2. Подъём на 100м
3. Сканирование + поиск ресурса
4. Перелёт к ресурсу
5. Настройка зоны дрилла
6. Бурение с мониторингом контейнеров (стоп при ≥95%)
7. Возврат на базу + докинг

---

## 9. Вывод: можно ли задать точку для добычи?

**ДА!** Дрилл поддерживает точное позиционирование зоны через 3 offset-параметра 
в локальных координатах корабля. Алгоритм:

1. Определить мировую координату цели (через RadarController или вручную)
2. Получить позицию и ориентацию корабля (RemoteControl)
3. Вычислить разницу и спроецировать на оси корабля
4. Установить `AreaOffsetLeftRight`, `AreaOffsetUpDown`, `AreaOffsetFrontBack`
5. Запустить `Drill_On` — мод сам найдёт и будет бурить вокселы в зоне

Размер зоны можно менять (`AreaWidth/Height/Depth`), чтобы захватить 
больше или меньше целей.
