# Pre-flight checks — что проверять до старта миссии

## Чек-лист

Перед стартом ore collection миссии агент должен выполнить:

### 1. Grid health

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py <ship>
```

Проверить:
- `Integrity: ALL INTACT` (не damaged)
- `READY FOR FLIGHT` статус
- `Hydrogen` non-zero (если нет — сначала дозаправка)
- `Batteries: [OK] 100%` или близко

### 2. Docking status

```bash
python examples/organized/parking/check_docking_status.py --grid <ship>
```

Если `status=Connected` — отстыковать **до** mining (иначе невозможно лететь).

### 3. Ore availability (РЕАЛЬНАЯ, не SharedMap)

```bash
python examples/organized/radar/ore_scanner.py --grid <ship> --radius 3000 --full_scan
```

Проверить:
- Количество точек нужной руды
- Content per point (обычно 255 кг за точку)
- Общий доступный объём: `count × 255 × 1 респаун`

**Не верь SharedMap** — он показывает consolidated кластеры, а реальных
точек может быть в 5-30 раз больше. В моей миссии SharedMap показал
2 депозита, а реально — 68 точек.

### 4. Mining script support

```bash
python -u examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --help
```

Проверить, что все нужные флаги доступны (--scan-radius, --area-size,
--min-point-density, --empty-cluster-skip-radius для Pt/Pd/Au).

### 5. База готова к приёму

```bash
python examples/organized/parking/dock.py <ship> <base> 100 --list-connectors
```

Проверить:
- Есть свободный коннектор
- Cargo containers на базе не заполнены (если заполнены — pull упадёт
  на Unicode bug, см. `pull-unicode-bug.md`)

### 6. Fuel: дозаправка перед стартом

Если `Hydrogen < 30%` — сначала дозаправка:

```bash
python examples/organized/refuel/refuel.py <ship> <base> --hydrogen 100
```

(если есть такой скрипт — нужно проверить)

## Что я НЕ проверил в миссии 50 т Gold

1. **Реальное количество Gold в радиусе** — верил SharedMap (2 депозита),
   а оказалось 68 точек. Если бы знал, оценил бы реалистичную цель
   лучше.
2. **Свободные контейнеры на базе** — не проверил до старта.
   Повезло, что `Ore Storage` на farpost0 был полупуст.
3. **Состояние водорода после reboot** — отображалось `no tanks found`,
   но в реальности долетели. Это сбивает с толку при следующих миссиях.

## Рекомендация: preflight.py

Создать `examples/organized/diagnostics/preflight_check.py` который
выполняет все 6 проверок разом и выводит go/no-go:

```bash
python examples/organized/diagnostics/preflight_check.py --ship skynet-agent0 --base skynet-farpost0 --ore Gold
```

Output:

```
[OK] Grid integrity
[OK] Batteries 100%
[WARN] Hydrogen 22% — recommend refuel before flight
[OK] Docking status: Unconnected
[OK] Free connectors on base: 4
[OK] Cargo space on base: 85000L free
[OK] Gold availability: 68 points × 255 kg = 17.3 t in radius 3km
[OK] Mission support: all flags available

Recommendation: GO with refuel
```

## Что добавить в mission playbook

Перед Шагом 1 добавить новый "Шаг 0: Pre-flight checks":

```markdown
## Шаг 0. Pre-flight checks

Перед стартом миссии:

1. `grid_report.py` — integrity, fuel, batteries
2. `check_docking_status.py` — отстыковать если нужно
3. `ore_scanner.py --full_scan` — реальное количество руды
4. `dock.py --list-connectors` — свободные коннекторы на базе
5. **Если hydrogen < 30% — сначала дозаправка**

Если любая проверка FAIL — останови миссию.
```
