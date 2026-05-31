# Space Navigator v5

`space_navigator_v5.py` — версия навигатора для быстрого перелёта в пустом космосе с сохранением защиты от столкновений.

Основное отличие от v4: скорость теперь может автоматически подниматься до `--max-speed`, если свежий скан показывает свободный тормозной коридор перед кораблём.

## Быстрый запуск

Из корня проекта:

```powershell
cd C:\secontrol
```

Полететь к ближайшему астероиду быстрее, но с контролем коридора:

```powershell
python examples/space_flight/space_navigator_v5.py `
  --grid agent1 `
  --nearest-asteroid `
  --max-speed 95 `
  --far-speed 75 `
  --medium-speed 35 `
  --close-speed 8 `
  --arrival 80
```

Полететь к GPS/координатам:

```powershell
python examples/space_flight/space_navigator_v5.py `
  --grid agent1 `
  --target "GPS:Point:-137000:-111000:-82000:" `
  --max-speed 95 `
  --far-speed 75 `
  --medium-speed 35 `
  --close-speed 8 `
  --arrival 80
```

Проверить план без полёта:

```powershell
python examples/space_flight/space_navigator_v5.py `
  --grid agent1 `
  --nearest-asteroid `
  --dry-run
```

## Что делает v5

На каждом шаге v5:

1. делает или переиспользует свежий voxel scan;
2. строит карту препятствий;
3. строит путь до безопасной локальной точки;
4. проверяет цилиндрический коридор перед кораблём;
5. считает безопасную скорость по тормозному пути;
6. летит к waypoint только внутри уже просканированного объёма.

Boost включён по умолчанию в CLI v5. Отключить его можно так:

```powershell
python examples/space_flight/space_navigator_v5.py --grid agent1 --nearest-asteroid --no-open-space-boost
```

## Настройки open-space boost

Основные параметры:

```powershell
--open-space-radius 900
--open-space-lookahead 3000
--open-space-corridor-radius 140
--open-space-min-target-distance 700
--brake-accel 8
--reaction-time 1.5
--safety-margin 140
--scan-max-age 3
```

Смысл:

- `--open-space-radius` — ближайший voxel должен быть не ближе этого расстояния;
- `--open-space-lookahead` — сколько метров вперёд должно быть свободно для максимальной скорости;
- `--open-space-corridor-radius` — радиус проверяемого коридора без учёта радиуса корабля;
- `--brake-accel` — консервативная оценка торможения корабля;
- `--reaction-time` — запас на задержки телеметрии и команд;
- `--safety-margin` — дополнительный запас до препятствия;
- `--scan-max-age` — старый скан не разрешает boost.

Фактический радиус коридора считается так:

```text
ship_radius + open_space_corridor_radius
```

## Рекомендуемая команда для agent1

Быстрый, но ещё консервативный вариант:

```powershell
python examples/space_flight/space_navigator_v5.py `
  --grid agent1 `
  --nearest-asteroid `
  --max-speed 95 `
  --far-speed 75 `
  --medium-speed 35 `
  --close-speed 8 `
  --arrival 80 `
  --open-space-radius 900 `
  --open-space-lookahead 3000 `
  --open-space-corridor-radius 140 `
  --brake-accel 8 `
  --reaction-time 1.5 `
  --safety-margin 140 `
  --scan-max-age 3
```

Если всё ещё слишком осторожно:

```powershell
--open-space-radius 700 --safety-margin 100 --open-space-lookahead 2500
```

Если опасно или корабль тяжёлый:

```powershell
--open-space-radius 1200 --safety-margin 220 --open-space-lookahead 4000 --brake-accel 5
```

## Как читать лог скорости

v5 пишет строку вида:

```text
[SPEED] mode=OPEN_SPACE_BOOST speed=95.0m/s profile=COARSE nearest=2500m corridor=3000m/3000m target=4200m safe_cap=95.0
```

Основные режимы:

- `OPEN_SPACE_BOOST` — можно лететь до `--max-speed`;
- `CORRIDOR_CAP` — впереди есть voxel в коридоре, скорость ограничена;
- `NEAR_VOXEL_CAP` — voxel рядом, даже если коридор свободен;
- `STALE_SCAN_CAP` — скан старый, boost запрещён;
- `TARGET_CAP` — цель близко, boost запрещён;
- `FINE_CLOSE` — финальная зона, используется `--close-speed`.

## Почему это безопаснее простого max-speed

v5 не делает так:

```text
если рядом нет вокселей — лететь максимум
```

Вместо этого он требует:

```text
рядом чисто + впереди чистый коридор + скан свежий + тормозной путь помещается в свободную дистанцию
```

Если одно из условий не выполнено, скорость ограничивается старой логикой v4 или ещё ниже по тормозному расчёту.
