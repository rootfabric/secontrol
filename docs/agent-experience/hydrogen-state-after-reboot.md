# Hydrogen state after server reboot

## Симптом

До добычи руды:
```
Hydrogen: [WARN] 3,250,725/15,000,000 L (21.7%)
```

После mining + server reboot:
```
Hydrogen: [WARN] no hydrogen tanks found
Fuel Status: [FAIL] CRITICAL: Hydrogen thrusters present but no tank found!
```

`grid_report` показывает 20 H2 thrusters, но `no hydrogen tanks found`.

## Что реально происходит

**Гипотеза 1: Display bug в grid_report.**
Возможно, после reboot `grid_report` не получает telemetry о баках,
но они есть. Корабль в реальности летит (долетел 13.7 км с
"NOT READY FOR FLIGHT" статусом).

**Гипотеза 2: Баки реально пусты/отключены.**
Mining использовал водород для маневрирования. Долетели обратно на
остатках. После reboot telemetry показывает 0. Но при полёте
back баки ещё работали.

**Гипотеза 3: Mining отключил баки.**
Некоторые mining скрипты отключают Hydrogen Tanks для снижения
вибрации/помех при бурении. После reboot баки остались disabled.

## Что это значит для миссии

В моём случае корабль долетел 13.7 км обратно, пристыковался,
несмотря на "NOT READY FOR FLIGHT" — то есть **водород реально был**.

После reboot и pull операций водород пропал из telemetry,
но миссия уже завершена — это не блокер.

## Рекомендация для pre-flight

Добавить проверку перед стартом:

```bash
# Проверить реальное состояние баков через Redis telemetry
python -c "
import redis, os
r = redis.Redis(host='192.168.0.15', port=6379, db=0,
                 username=os.getenv('SE_OWNER'),
                 password=os.getenv('SE_REDIS_PASS'))
# H2 tank telemetry keys
keys = r.keys('se:*:grid:133599597791901654:*HydrogenTank*')
for k in keys[:5]:
    print(k.decode(), r.hgetall(k))
"
```

Если ключей нет или значения 0 — нужна дозаправка.

## Рекомендация для mission playbook

Добавить в `se-ore-collection-mission.md`:

```markdown
### Pre-flight: проверка водорода

Перед стартом миссии проверь не только `Hydrogen: [WARN] 22%` в
`grid_report`, но и реальную telemetry через redis. Display bug
возможен после server reboot.

Если `Hydrogen: no hydrogen tanks found` или `0%` — **сначала
дозаправься на базе** через `refuel.py` или прямой transfer из
базы в танки корабля.
```

## Долгосрочное улучшение

Исправить `grid_report.py` чтобы:
1. Не показывать `no hydrogen tanks found` если thrusters есть —
   выводить `[WARN] tank telemetry missing, check manually`
2. Проверять состояние баков через несколько источников:
   - Redis telemetry
   - Block properties
   - Functional/working status
