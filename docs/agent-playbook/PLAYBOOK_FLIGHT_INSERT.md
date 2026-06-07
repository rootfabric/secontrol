## Диагностика полёта без ложного hard-block

Перед любым выводом `fleet paralyzed`, `grid cannot fly`, `RC cannot be enabled`, `player offline hard-block` или `script will not work` используй отдельный playbook:

```bash
cat docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md
```

Минимальный порядок:

```bash
# 1. Проверить общий статус грида
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py agent1

# 2. Проверить стыковку
python examples/organized/parking/check_docking_status.py --grid agent1

# 3. Проверить готовность, но не делать hard-block только по этому выводу
python examples/organized/diagnostics/check_flight_ready.py agent1

# 4. Если безопасно, выполнить короткий guarded flight check через canonical navigator
python examples/space_flight/space_navigator_v5.py --grid agent1 --target="GPS:flight_check:X:Y:Z:#FF75C9F1:" --max-speed 20 --far-speed 20 --medium-speed 10 --close-speed 3 --arrival 20
```

Важно:

- `Remote Control enabled=false`, `isFunctional=false`, `online=false` и `Redis publish result = 1 subscriber` — это warning, не proof.
- `1 subscriber` означает наличие подписчика Redis, а не выполнение команды в игре.
- Для RC используй RC-specific path: `handbrake_off`, `thrusters_on`, `gyro_control_on`, `enable`, `goto`.
- Не делай вывод о невозможности полёта по subtype движка. Проверяй position/speed delta.
- Hard-block разрешён только после guarded flight check или если flight check небезопасен: пристыкован, внутри voxel, нет command subscriber, нет телеметрии, пользователь запретил движение.
