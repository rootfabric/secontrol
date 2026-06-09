# v5 stuck recovery — flight problems

## Симптомы

`space_navigator_v5.py` зависает в `MEDIUM` profile:

```
[NAV] step=N profile=MEDIUM pos=(...) target_dist=...m
[FLY] stopped=(...) progress=0m remaining=...m
[FLY] waypoint made no useful progress (progress=0.0m, expected>25.0m)
```

Корабль не движется, в command queue копятся команды `goto` (33+ штук).
Скрипт при этом работает и "считает", что летит. На дистанции 263м от базы
он постоянно "упирается" в waypoint, не может продвинуться > 25м.

## Конкретный случай

Миссия skynet-agent0 → Gold → skynet-farpost0. После добычи 50 т Gold
на дистанции 13.7 км от базы v5 застрял на 263м. Прогресс 0м за 25 минут.

В логе: `Ice: content=255, ... 1057 voxels, 4 contacts` — рядом с базой
астероид с айсбергами, v5 делает объезд, но не сходится.

## Recovery (сработало)

1. Прервать v5 (процесс сам завершился, но если висит — `Stop-Process`)
2. **Использовать `dock.py` вместо v5** для подлёта к базе:

```bash
python -u examples/organized/parking/dock.py skynet-agent0 skynet-farpost0 100
```

`dock.py` имеет собственный алгоритм final push и справляется с
астероидами лучше. `>> LOCKED!` через 1-2 минуты вместо 25 минут зависания.

## Recovery (классическое из playbook) — не помогло

Playbook предлагает:

```bash
python -u examples/space_flight/space_navigator_v5.py --grid skynet-agent0 \
  --target="GPS:..." --max-speed 50 --far-speed 50 --medium-speed 25 \
  --close-speed 3 --arrival 30
```

В моём случае это **не помогло** — v5 опять завис на 263м. Возможно,
проблема в том, что v5 видит препятствия в voxel-карте и строит объездной
путь, который не сходится.

## Альтернативы (не пробовал, но должны работать)

1. **`dock.py --no-long-approach`** — если дистанция < 200м, dock.py
   не делает long-approach, сразу final push.
2. **Телепортация админа** — если v5 совсем не сходится, admin может
   переместить корабль ближе.

## Рекомендация для mission playbook

Добавить в `se-ore-collection-mission.md` секцию "Step 7.5: If v5 stuck
within 500m of base — use `dock.py` instead":

```markdown
### Fallback: v5 stuck near base

If v5 stuck within 500m of base (progress=0 for 60+ sec, position not
changing) and base is in voxel-dense area (asteroid nearby), use `dock.py`:

```bash
python -u examples/organized/parking/dock.py <ship> <base> 100
```

`dock.py` has its own final-push logic and handles asteroids better than
v5. Typical recovery time: 1-2 minutes vs 25+ minutes of v5 stuck.
```

## Verify-after-write

Всегда проверять позицию через `redis_reader` после остановки скрипта:

```python
from secontrol.fleet_dashboard.redis_reader import FleetRedisReader
import json, math
r = FleetRedisReader()
s = r.get_fleet_status()
ag = [g for g in s['grids'] if g['name']=='skynet-agent0'][0]
fp = [g for g in s['grids'] if g['name']=='skynet-farpost0'][0]
dx = fp['position']['x']-ag['position']['x']
dy = fp['position']['y']-ag['position']['y']
dz = fp['position']['z']-ag['position']['z']
print('dist to base:', math.sqrt(dx*dx+dy*dy+dz*dz))
```

Если дистанция не меняется 60+ сек → v5 застрял.
