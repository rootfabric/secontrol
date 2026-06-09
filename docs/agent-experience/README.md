# Agent Experience — заметки и улучшения по результатам миссий

Папка с реальным опытом запуска миссий: что ломалось, что работало, что стоит чинить.

Каждый файл — отдельный класс проблем + конкретные рекомендации.

## Главный индекс

| Файл | Что покрывает |
|---|---|
| `flight-stuck-recovery.md` | v5 зависает в MEDIUM profile, recovery, dock.py как fallback |
| `mining-actual-vs-delivered.md` | Расхождение между `+50278` в mining log и `37799` на базе |
| `pull-unicode-bug.md` | `pull_from_attached_ships.py` падает на `\u2192` |
| `hydrogen-state-after-reboot.md` | `no hydrogen tanks found` после server reboot |
| `pre-flight-checks.md` | Что агент должен проверить до старта миссии |
| `long-script-timeout.md` | Стратегия запуска длинных скриптов с verify-after-exit |
| `mission-improvements.md` | Конкретные патчи для `se-ore-collection-mission.md` |

## Сводка: что мешало миссии "50 т Gold" на skynet-agent0

**Серьёзные блокеры (потребовали recovery):**

1. **v5 stuck на 263м от базы** — waypoint нет прогресса, прогон 25 минут. Решено: `dock.py` с approach 100.
2. **Server reboot во время возврата** — ID грида сохранился, но водородные баки пропали из telemetry.
3. **`pull_from_attached_ships.py` Unicode crash** на `\u2192` и `\u2705` — контейнеры не перенесены, нужно 2 попытки.

**Средние проблемы:**

4. **v5 долетел до safe target в 228м от GPS точки** — слишком далеко для mining, пришлось работать с этого расстояния.
5. **Добыто 50 278 кг, доставлено 37 799 кг** — потери 25% (см. mining-actual-vs-delivered).
6. **No hydrogen tanks found после reboot** — корабль NOT READY FOR FLIGHT, но реально долетел.

**Мелочи:**

7. **Таймауты bash (10-15 мин) превышаются длинными скриптами** — нужна стратегия verify-after-exit.
8. **SharedMap показывал 2 депозита, реально 68** — дисплей SharedMap врет для Gold.

## Рекомендации: топ-3 улучшения

1. **Добавить pre-flight checks** (см. `pre-flight-checks.md`) — проверять водород, баки, и реальное количество руды в радиусе до старта mining.
2. **Recovery через `dock.py` для последних 500м** — `dock.py` справляется с астероидами лучше, чем `space_navigator_v5.py`.
3. **Fix `pull_from_attached_ships.py` Unicode** — `print(..., file=sys.stdout.buffer)` или заменить `\u2192` на ASCII.

## Файлы

Созданы 2026-06-10 по итогам миссии skynet-agent0 + skynet-farpost0 (50 т Gold).
