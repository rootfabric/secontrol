# Long script timeout strategy

## Проблема

Длинные скрипты (`v5` flight, `mining`) превышают bash таймаут
(10-15 минут), и агент не может отличить:

- Скрипт ещё работает, но медленно
- Скрипт завис (stuck)
- Скрипт завершился успешно (но bash timeout сработал)

В моей миссии:
- `flight_to_gold.log` — v5 не уложился в 10 мин
- `flight_to_gold_retry.log` — то же самое
- `flight_to_base.log` — v5 не уложился в 15 мин (на 263м застрял)

После каждого таймаута я проверял `Get-Process python` и `redis
position` — это правильно, но не масштабируется.

## Стратегия: verify-after-exit

Всегда после bash таймаута:

1. **Проверить, работает ли процесс:**
   ```bash
   Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, CPU
   ```

2. **Если процессов нет — прочитать лог:**
   ```bash
   Get-Content tmp/<log>.log -Tail 50
   ```
   Искать:
   - "Target reached", "DOCKING COMPLETE", "OK: target reached" — успех
   - "stuck", "no progress", "max steps exceeded" — нужен recovery

3. **Проверить реальное состояние через redis:**
   ```python
   from secontrol.fleet_dashboard.redis_reader import FleetRedisReader
   r = FleetRedisReader()
   print(r.get_fleet_status())
   ```
   Сравнить позицию с предыдущим замером — если не меняется 60+ сек,
   скрипт завис.

## Стратегия: long-timeout для mining

Mining может идти 20-30 минут для больших объёмов.
Использовать `timeout: 1800000` (30 мин) — этого хватит.

Для полётов — `timeout: 900000` (15 мин) обычно достаточно.
Если превышен — это сигнал о stuck, нужен recovery.

## Стратегия: nohup + log tailing

Альтернативно, запускать длинные скрипты в фоне с nohup:

```bash
# В shell
nohup python -u examples/.../script.py > tmp/script.log 2>&1 &
PID=$!
echo "PID: $PID"

# Тогда можно делать verify в основном shell
sleep 60
Get-Content tmp/script.log -Tail 20
```

Преимущество: bash не ждёт завершения, можно делать periodic checks.

Недостаток: если скрипт упадёт — нужно вручную чистить.

## Стратегия: max-steps в v5

В `space_navigator_v5.py` есть `--max-steps` (не пробовал, но видел
в help у `dock.py`). Это позволяет скрипту самому остановиться через
N шагов, а не зависать.

## Рекомендация

В миссии добавить:

```markdown
## Длинные скрипты: правила таймаутов

| Скрипт | Ожидаемое время | Таймаут | Если превышен |
|---|---|---|---|
| `undock` | 1-2 мин | 180000 (3 мин) | recovery не нужен |
| `v5` flight < 5 км | 3-7 мин | 600000 (10 мин) | check log + redis |
| `v5` flight 5-20 км | 7-15 мин | 900000 (15 мин) | check log + redis |
| `mining` 50 т | 10-30 мин | 1800000 (30 мин) | check log + redis |
| `dock` | 1-3 мин | 600000 (10 мин) | check log + redis |

После таймаута **всегда**:
1. `Get-Process python` — есть ли процесс
2. `Get-Content log -Tail 30` — последние строки
3. `redis position` — двигается ли корабль
```

## Альтернативный подход: pull-style скрипты

Для очень длинных операций (mining) — реализовать pull-style:
- Скрипт пишет прогресс в Redis каждые 5 сек
- Агент читает из Redis, не из лога
- Можно прервать скрипт извне, если прогресс < ожидаемого

Это уже частично реализовано в mining (`update_progress`), но
агентский loop мог бы использовать это напрямую.
