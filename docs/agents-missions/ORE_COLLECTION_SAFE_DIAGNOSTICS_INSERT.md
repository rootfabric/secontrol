<!-- ORE_MISSION_SAFE_DIAGNOSTICS_INSERT_START -->

---

## Safe diagnostics before mining clarification

Если запрос на добычу неполный, не запускай добычу сразу. Но и не останавливайся сразу на уточняющих вопросах.

Сначала выполни безопасные проверки:

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py rover
python examples/organized/parking/check_docking_status.py --grid agent
python examples/organized/parking/check_docking_status.py --grid rover
python examples/organized/diagnostics/check_flight_ready.py agent
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --help
```

Для запроса вида `100 тонн Stone` обязательно проверь до старта:

1. какой грид реально имеет Nanobot Drill / drill system;
2. cargo capacity и текущий inventory;
3. docking status;
4. поддерживает ли mining script `--ore Stone`;
5. где находится база, если пользователь её не указал;
6. не находится ли целевой rover уже на базе и не является ли он только получателем/транспортом.

Только после diagnostics задай один конкретный вопрос, если выбор всё ещё нужен.

Пример правильного ответа перед действиями:

```text
Понял: пробуем добычу камня на agent, rover считаю стоящим на базе. Перед стартом 100 т не запускаю вслепую: сначала проверю agent/rover, cargo capacity, Nanobot Drill, docking и поддержку --ore Stone.
```

<!-- ORE_MISSION_SAFE_DIAGNOSTICS_INSERT_END -->
