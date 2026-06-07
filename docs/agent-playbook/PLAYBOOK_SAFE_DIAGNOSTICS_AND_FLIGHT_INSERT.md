<!-- AGENT_SAFE_DIAGNOSTICS_INSERT_START -->

---

## Обязательная диагностика до вопросов

Если запрос пользователя неполный, но можно безопасно проверить факты, не останавливайся на уточняющих вопросах. Сначала выполни read-only diagnostics.

Безопасные команды перед вопросами:

```bash
# Общее состояние всех гридов
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py

# Проверить возможный рабочий грид
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py rover

# Проверить стыковку
python examples/organized/parking/check_docking_status.py --grid agent
python examples/organized/parking/check_docking_status.py --grid rover

# Проверить готовность к полёту
python examples/organized/diagnostics/check_flight_ready.py agent

# Проверить аргументы скрипта добычи без запуска добычи
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --help
```

Спрашивай пользователя только после этих проверок, если всё ещё нужен выбор.

Подробно: `docs/agent-playbook/SAFE_DIAGNOSTICS_BEFORE_CLARIFICATION.md`.

<!-- AGENT_SAFE_DIAGNOSTICS_INSERT_END -->

<!-- AGENT_FLIGHT_DIAGNOSTICS_INSERT_START -->

---

## Обязательное правило диагностики полёта

Не объявляй `fleet paralyzed`, `grid cannot fly`, `RC cannot be enabled`, `player offline hard-block` или `script will not work` только по статической телеметрии.

`enabled=false`, `isFunctional=false`, `online=false`, `0 players online`, `1 subscriber`, generic `block_enable` failure и thruster subtype — это warning signals, не hard blockers.

Перед отказом:

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent1
python examples/organized/parking/check_docking_status.py --grid agent1
python examples/organized/diagnostics/check_flight_ready.py agent1
```

Если грид не пристыкован и тест безопасен, проверь фактическое движение коротким guarded flight check или каноническим navigator test. Источник истины — position/speed delta, а не одно поле RC telemetry.

Подробно: `docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md`.

<!-- AGENT_FLIGHT_DIAGNOSTICS_INSERT_END -->
