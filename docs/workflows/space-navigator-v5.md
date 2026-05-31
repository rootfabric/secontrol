# Space Navigator v5

> Index: `AGENTS.md` — Перелёты

## Назначение

`Space Navigator v5` ускоряет дальние перелёты в Space Engineers без отказа от voxel-scan безопасности. CLI-файл:

```text
examples/space_flight/space_navigator_v5.py
```

Также добавлена копия для старого расположения:

```text
scripts/space_navigator_v5.py
```

v5 использует тот же `SpaceNavigatorController`, но включает `OpenSpaceBoostConfig`.

## Главное отличие от v4

v4 выбирал скорость в основном по ближайшему voxel и дистанции до цели. Из-за этого корабль мог идти медленно, если какой-то voxel есть в scan volume, даже когда прямой коридор впереди свободен.

v5 добавляет corridor-aware speed cap:

```text
speed = min(max_speed, braking_limit_by_corridor, braking_limit_by_target)
```

Boost разрешается только если:

1. текущий scan свежий;
2. профиль сейчас `COARSE`;
3. цель не слишком близко;
4. ближайший voxel дальше `open_space_radius`;
5. впереди по направлению waypoint свободен коридор `open_space_lookahead`;
6. тормозной путь с запасами помещается в свободную дистанцию.

## Быстрая команда

```powershell
cd C:\secontrol
python examples/space_flight/space_navigator_v5.py `
  --grid agent1 `
  --nearest-asteroid `
  --max-speed 95 `
  --far-speed 75 `
  --medium-speed 35 `
  --close-speed 8 `
  --arrival 80
```

## Полная рекомендуемая команда

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

## Отключение boost

```powershell
python examples/space_flight/space_navigator_v5.py --grid agent1 --nearest-asteroid --no-open-space-boost
```

## Отладка скорости

v5 печатает строку `[SPEED]` перед каждым перелётом к waypoint.

Пример хорошего ускорения:

```text
[SPEED] mode=OPEN_SPACE_BOOST speed=95.0m/s profile=COARSE nearest=inf corridor=3000m/3000m target=8200m safe_cap=95.0
```

Пример ограничения препятствием:

```text
[SPEED] mode=CORRIDOR_CAP speed=42.0m/s profile=COARSE nearest=1100m corridor=480m/3000m target=2700m safe_cap=42.0
```

## Настройка под корабль

Если корабль тяжёлый и тормозит плохо, уменьши `--brake-accel`:

```powershell
--brake-accel 5 --safety-margin 220
```

Если корабль манёвренный и лог показывает постоянный `CORRIDOR_CAP` слишком рано:

```powershell
--open-space-radius 700 --safety-margin 100 --open-space-lookahead 2500
```

Если корабль широкий:

```powershell
--ship-radius 70 --open-space-corridor-radius 180
```

## Важное ограничение

Boost по умолчанию работает только в `COARSE`-профиле. Не включай `--boost-in-medium` рядом с астероидом, пока не проверишь поведение на `--dry-run` и малых скоростях.
