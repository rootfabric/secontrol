# Mission improvements — конкретные патчи для se-ore-collection-mission.md

## Изменения, которые я бы внёс

### 1. Step 0: Pre-flight checks (новый раздел)

Перед Шагом 1 добавить:

```markdown
## Шаг 0. Pre-flight checks

Перед стартом миссии:

1. **Grid health:**
   ```bash
   python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py <ship>
   ```
   Проверить: integrity OK, hydrogen > 30%, batteries OK.

2. **Docking status:**
   ```bash
   python examples/organized/parking/check_docking_status.py --grid <ship>
   ```

3. **Реальное количество руды** (не SharedMap):
   ```bash
   python examples/organized/radar/ore_scanner.py --grid <ship> --radius 3000 --full_scan
   ```

4. **Свободные коннекторы базы:**
   ```bash
   python examples/organized/parking/dock.py <ship> <base> 100 --list-connectors
   ```

Если любая проверка FAIL — останови миссию или дозаправься.
```

### 2. Step 6.5: Decision threshold для больших amount

Сейчас в playbook:
```markdown
- amount ≥ 100 000 кг: 80% = 80 000+ кг
- Спрашивать ничего не надо, если не получается добыть больше трети
```

Я бы добавил:

```markdown
### Fallback: 50-80% delivered, но mining log shows target reached

Если mining log рапортует `OK: target reached, <ORE> +<X>` но в
контейнере < 80% от amount — это **не** mining failure, это
**inventory reconciliation loss**.

Возможные причины:
- Часть руды в Refinery output
- Потери при добыче через буфер
- Потери при server reboot

Действие: продолжить миссию (mining прошёл успешно), зафиксировать
реальное количество в финальном отчёте.
```

### 3. Step 7.5: v5 stuck recovery (новый раздел)

После Шага 7 добавить:

```markdown
### Fallback: v5 stuck within 500m of base

Если v5 stuck на дистанции 200-500м от базы (progress=0 for 60+ сек,
position not changing) и рядом астероид — v5 не справляется с
объездом. Использовать `dock.py`:

```bash
python -u examples/organized/parking/dock.py <ship> <base> 100
```

`dock.py` имеет собственный final-push и справляется с астероидами
лучше. Recovery время: 1-2 мин вместо 25+ мин зависания v5.

Если дистанция < 200м — `dock.py --no-long-approach`.
```

### 4. Step 10.1: Pull retry (новый раздел)

В Шаге 10 добавить про Unicode bug:

```markdown
### Fallback: pull_from_attached_ships.py падает на Unicode

Известный баг: на Windows консоли (cp1251) скрипт падает на
`\u2192` и `\u2705` символах. Если упал в середине переноса:

1. **Запустить pull ещё раз** — может перенести остаток.
2. **Проверить реальное состояние** через `grid_report.py` на обоих
   grid'ах — сколько перенеслось, сколько осталось.
3. **Если 2-я попытка тоже падает** — использовать
   `pull_items_from_docked_grid.py --force`:
   ```bash
   python examples/organized/container/advanced/pull_items_from_docked_grid.py \
     --source-grid <ship> --target-grid <base> --force
   ```

Долгосрочное решение: добавить `sys.stdout = io.TextIOWrapper(
sys.stdout.buffer, encoding='utf-8')` в начало pull_from_attached_ships.py.
```

### 5. Step 11: Reconciliation report (усилить существующий)

В Шаге 11 (Финальная проверка) добавить:

```markdown
## Шаг 11. Reconciliation report

Перед финальным ответом агенту нужно посчитать:

- **Добыто (mining log):** `grep "OK: target reached" tmp/mining.log`
- **В контейнере корабля после pull:** `grid_report.py <ship>` — Gold Ore
- **На базе:** `grid_report.py <base>` — Gold Ore
- **Reconciliation loss %:** (добыто - доставлено) / добыто * 100

Если loss > 5% — добавить в финальный отчёт секцию "Потери и причины":

```text
Миссия завершена:
- корабль: skynet-agent0
- база: skynet-farpost0
- руда: Gold
- цель добычи: 50 000 кг
- добыто (mining log): 50 278.4 кг
- доставлено на базу: 37 799 кг
- потери: 12 479 кг (24.8%) — Refinery + reconciliation
- стыковка: да
- перенос: выполнен (с 1 retry)
```
```

### 6. Новый appendix: Hardening recommendations

```markdown
## Appendix: Hardening recommendations

Эти улучшения убирают известные баги и ускоряют миссии.

### A. Починить Unicode в pull_from_attached_ships.py и dock.py

В начало обоих скриптов добавить:

```python
import sys
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
```

### B. Создать preflight_check.py

См. `docs/agent-experience/pre-flight-checks.md` для деталей.

### C. Добавить --max-steps в v5 (если нет)

Позволяет v5 самому остановиться через N шагов.

### D. Добавить final reconciliation в mining log

В конец mining log добавить:
```
[FINAL] script_reported=X, container_actual=Y, loss=Z%
```

### E. Создать fallback: dock.py как primary arrival

Если база близко к астероиду — `dock.py` надёжнее, чем `v5`. Сделать
`dock.py` основным способом прибытия на базу, а `v5` — только для
перелётов между объектами.
```

## Что НЕ нужно менять

Не нужно трогать:

- Mining скрипт (Pt/Pd/Au fallback работает)
- smooth_undock.py (отлично работает)
- Базовая логика mission (последовательность шагов)

Эти вещи прошли проверку боем.
