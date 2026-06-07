# SE Ore Collection Mission — добыча руды с возвратом на базу

## Назначение

Этот сценарий описывает полную миссию добычи руды:

1. Проверить, пристыкован ли корабль.
2. Найти ближайшую известную точку нужной руды.
3. Если корабль припаркован — отстыковаться.
4. Долететь до точки руды.
5. Просканировать область.
6. Добыть нужное количество руды.
7. Вернуться на базу.
8. Пристыковаться к базе.
9. Переложить добытые ресурсы на базу.

Сценарий предназначен для агента, который работает в локальном репозитории `secontrol`.

Агент должен выполнять команды строго из корня репозитория.

---

## Миссия по умолчанию

Используй эти параметры, если пользователь не указал другие:

```text
ship: skynet-agent0
base: skynet-farpost0
ore: Uranium
amount: 10000          # в килограммах (10 тонн)
base_gps: GPS:Base:-137317:-111140:-82039:
undock_distance: 80
dock_approach_distance: 100
```

**`amount` всегда указывается в килограммах (кг)**, не в тоннах. Если пользователь говорит "тонна" — умножай на 1000. "1 миллион тон" = 1 000 000 000 кг (обычно пользователь имеет в виду 1 000 000 кг = 1000 т, **уточни если неясно**).

### Подстановка параметров из запроса пользователя

Все шаги ниже написаны для `ore=Uranium, amount=3000`. Если пользователь просит другую руду или объём — подставь значения в каждое место, где встречается `Uranium` / `3000`:

- `--material Uranium` → `--material <ORE>`
- `--ore Uranium` → `--ore <ORE>`
- `amount: 3000` (или другое) → `amount: <AMOUNT>`

Если пользователь просит большой объём (≥50 000 кг), **перед стартом проверь**, что локальный кластер `<ORE>` содержит достаточно руды. Эвристика: `депозиты × 255 кг` за один респаун. Например, 37 Pt депозитов = ~9 435 кг за респаун, для 100 т нужно ~11 респаунов. Если кластер мал — спроси пользователя, лететь ли к другому кластеру.

---

## Главные правила безопасности

1. Не придумывай новые команды, если есть готовая команда из этого сценария.
2. Не используй `GPS:Uranium_1:X:Y:Z:` как реальную цель. Это только пример плохого GPS. Реальный GPS нужно взять из вывода команды поиска руды.
3. Перед любым полётом проверь, не пристыкован ли корабль.
4. Если корабль пристыкован — сначала отстыкуйся.
5. Перед стыковкой проверь доступные коннекторы.
6. Если команда завершилась ошибкой, останови миссию и коротко объясни:
   - на каком шаге ошибка;
   - какая команда выполнялась;
   - что видно в выводе;
   - какую команду можно повторить.
7. Не продолжай миссию после неуспешного полёта, неуспешной добычи или неуспешной стыковки.
8. После длинной команды всегда анализируй вывод перед следующим шагом.
9. Если целевая руда не найдена в SharedMap, сначала выполни сканирование руды, затем повтори поиск.
10. Если база не имеет свободного коннектора, не пытайся парковаться в занятый коннектор.
11. **Длинные скрипты (v5, mining) запускай с `python -u` (unbuffered stdout),** иначе вывод буферизуется и ты не увидишь прогресс в реальном времени.
12. **Не верь команде, что v5 «летит», только по логу.** Проверяй позицию корабля через redis (gridinfo) — лог может врать или буферизоваться.

---

## Краткий план для агента

Перед выполнением агент должен сформировать внутренний план:

```text
1. Check docking status
2. Find nearest Uranium GPS
3. Undock if ship is connected
4. Fly to Uranium GPS
5. Scan ore around ship
6. Mine Uranium
7. Fly back to base GPS
8. List free connectors on base
9. Dock to base
10. Transfer cargo to base
11. Verify final status
```

---

## Шаг 1. Проверить стыковку

Выполни:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

Ожидаемый смысл вывода:

- посмотреть коннекторы корабля `skynet-agent0`;
- понять, есть ли `status=Connected`;
- понять, соединён ли он с базой `skynet-farpost0`.

Если корабль уже пристыкован к базе — на шаге 3 нужно отстыковаться.

Если корабль не пристыкован — шаг 3 можно пропустить.

---

## Шаг 2. Найти ближайшую известную точку Uranium

Выполни:

```bash
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-agent0 --material Uranium --clusters --gps --limit 1
```

Из вывода найди блок:

```text
GPS markers:
```

И скопируй первую GPS-строку, например:

```text
GPS:Uranium_cluster_1:-123456.0:-111222.0:-82333.0:#44FF44:
```

Эту строку нужно использовать как цель полёта.

Если вывод содержит:

```text
No ore deposits found.
```

тогда сначала выполни сканирование:

```bash
python examples/organized/radar/ore_scanner.py --grid skynet-agent0
```

Затем повтори поиск:

```bash
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-agent0 --material Uranium --clusters --gps --limit 1
```

Если после повторного поиска Uranium всё ещё не найден — останови миссию.

---

## Шаг 3. Отстыковаться, если корабль пристыкован

Если на шаге 1 корабль был пристыкован, выполни:

```bash
python examples/organized/parking/smooth_undock.py skynet-agent0 skynet-farpost0 80
```

После расстыковки снова проверь статус:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

Если корабль всё ещё подключён — останови миссию.

---

## Шаг 4. Лететь к ближайшей точке Uranium

Используй GPS, полученный на шаге 2.

Пример команды с реальным GPS из вывода:

```bash
python -u examples/space_flight/space_navigator_v5.py --grid skynet-agent0 --target="GPS:Uranium_cluster_1:-123456.0:-111222.0:-82333.0:#44FF44:" --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80 > tmp/flight_to_ore.log 2>&1
```

**Всегда запускай v5 с `python -u` и перенаправляй stdout в файл** (через `>`), не через `Tee-Object` или `Out-String`. Иначе вывод буферизуется и ты не увидишь прогресс в реальном времени.

Важно:

- не используй примерные координаты;
- не используй `X:Y:Z`;
- всегда вставляй реальную GPS-строку из `shared_map_deposits.py`.

### Fallback: v5 «застрял»

`space_navigator_v5.py` иногда зависает в `MEDIUM` profile: корабль перестаёт двигаться, RC показывает `enabled=False` в стейте, но в command queue копятся команды `goto` (33+ штук). Скрипт при этом работает и «считает», что летит.

**Диагностика stuck:**
1. Смотри позицию через redis (не в лог):
   ```python
   from secontrol.fleet_dashboard.redis_reader import FleetRedisReader
   r = FleetRedisReader()
   print(r.get_fleet_status())  # ищи pos для своего grid_id
   ```
2. Если позиция не меняется ≥60 сек — v5 застрял.

**Recovery (один раз; если не помогло — останови миссию):**
1. Убей процесс: `Stop-Process -Id <PID> -Force` (PID из `Get-Process python`).
2. Очисти command queue RC:
   ```python
   import redis
   r = redis.Redis(host='192.168.0.15', port=6379, db=0, username='<OWNER>', password='<PASS>')
   r.delete(f'se:<OWNER>:grid:<GRID_ID>:device:<RC_DEVICE_ID>:command')
   ```
3. Перезапусти v5 **с другими флагами** (уменьши скорость, увеличь arrival):
   ```bash
   python -u examples/space_flight/space_navigator_v5.py --grid skynet-agent0 --target="GPS:..." --max-speed 50 --far-speed 50 --medium-speed 25 --close-speed 3 --arrival 30 > tmp/flight_retry.log 2>&1
   ```

Если вторая попытка тоже застряла — останови миссию.

---

## Шаг 5. Просканировать руды рядом

После прибытия выполни:

```bash
python examples/organized/radar/ore_scanner.py --grid skynet-agent0
```

Если сканер нашёл Uranium — продолжай.

Если Uranium не найден, но точка была из SharedMap — всё равно можно попробовать добычу, потому что данные могли быть неточными, но агент должен отметить это в отчёте.

---

## Шаг 6. Добыть Uranium

Размер `scan-radius` зависит от объёма `amount` (это ключевой параметр для больших миссий):

| amount | --scan-radius | почему |
|---|---|---|
| ≤ 10 000 кг | 1500 | один локальный кластер (1-2 км) |
| 10 000 - 100 000 кг | 3000 | несколько ближних кластеров (до 5 км) |
| 100 000 - 1 000 000 кг | 5000-10000 | нужны дальние кластеры (до 17 км); 1М льда реально за 2-5 мин |
| > 1 000 000 кг | 10000+ | возможно, нужны несколько рейсов к разным кластерам |

**Сначала определи правильный scan-radius по таблице выше, потом запускай mining:**

```bash
python -u examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --grid skynet-agent0 --ore <ORE> --amount <AMOUNT> --scan-radius <RADIUS> --area-size 75 --density-radius 20 --max-points 120 --startup-timeout 90 --no-progress-timeout 60 > tmp/mining.log 2>&1
```

**Всегда запускай mining с `python -u` и в файл**, чтобы видеть прогресс в реальном времени.

После завершения внимательно проверь вывод.

Успешным результатом считается ситуация, когда скрипт явно показывает, что добыча завершена или нужное количество достигнуто.

Если добыча не началась, нет прогресса, не найдена руда или корабль не может добывать — останови миссию.

### Fallback: 1-я попытка вышла с "no dense point" и добыто <50% amount

Это значит, что **локальный кластер мал для amount**. Увеличь `--scan-radius` в 2-3 раза и перезапусти mining. Например, для 1М кг с `--scan-radius 1500` добылось 609k, после `--scan-radius 2500` — 1.14М. **Не пытайся решить проблему уменьшением `area-size`** — это не тот случай.

### Fallback: добыто меньше amount

Скрипт может остановиться на любом объёме (кластер исчерпан, скрипт застрял в retry, истёк таймаут). Если добыто **<80% от amount** — переходи к Шагу 6.5 (decision point) и спроси пользователя. Если **≥80%** — продолжай по плану.

### Fallback (только для Pt/Pd/Au): mining сразу скипает все точки

**Этот fallback нужен ТОЛЬКО для руд с низкой плотностью (Platinum, Palladium, Gold). Для льда и камня он не нужен.**

С дефолтными `area-size 75` и авто-`empty-cluster-skip-radius` (~53 м) скрипт после первого failed point скипает все соседние точки, и добыча встаёт. Если в логе видишь `Platinum: 0` или `No ore in current area` на каждой итерации при том, что сканер руды показывает депозиты рядом — уменьши зону:

```bash
python -u examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --grid skynet-agent0 --ore <ORE> --amount <AMOUNT> --scan-radius 1500 --area-size 8 --density-radius 10 --empty-cluster-skip-radius 10 --min-point-density 3 --max-points 5 --startup-timeout 90 --no-progress-timeout 60 --stone-safety-delta 50 --max-stone-per-ore-ratio 0.2 > tmp/mining_v2.log 2>&1
```

Что делают добавленные флаги:
- `--area-size 8` — уменьшает рабочую зону, чтобы `empty-cluster-skip-radius` стал меньше;
- `--empty-cluster-skip-radius 10` — не скипать точки дальше 10 м после fail;
- `--min-point-density 3` — принимать разреженные точки (дефолт 6 слишком строгий);
- `--max-points 5` — не уходить далеко после первых неудач;
- `--stone-safety-delta 50` / `--max-stone-per-ore-ratio 0.2` — допустить долю камня при добыче вплотную к астероиду.

---

## Шаг 6.5. Decision point (только если добыто <80% от amount)

Спроси пользователя через `question` tool, что делать дальше. Варианты:

1. **Продолжить добычу** (если кластер ещё богат — перезапусти mining с тем же amount-достигнутым, скрипт продолжит с респауна).
2. **Вернуться с тем, что есть** (если mining застрял в retry и добыча не растёт).
3. **Лететь к другому кластеру** (если локальный исчерпан; используй `shared_map_deposits.py` для поиска следующей точки).

**Threshold для больших amount:**

- amount ≤ 10 000 кг: 80% threshold работает как описано. Если добыто 7 000 из 10 000 — спрашиваем.
- amount ≥ 100 000 кг: 80% = 80 000+ кг, что в любом случае больше одной типичной миссии. Если добыто ≥80% — **продолжай автоматически**. 
Спрашивать ничего не надо, если не получается добыть больше трети, лети на другое меторождение если есть рядом(50км) если других месторождений нет, летим домой.

По умолчанию для больших объёмов (≥50 000 кг) — рекомендуй «Вернуться с тем, что есть», если процесс mining не показывает рост за последние 2 минуты.

---

## Шаг 7. Вернуться на базу

Выполни:

```bash
python -u examples/space_flight/space_navigator_v5.py --grid skynet-agent0 --target="GPS:Base:-137317:-111140:-82039:" --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80 > tmp/flight_to_base.log 2>&1
```

Если полёт на базу завершился ошибкой — примени fallback из Шага 4 (v5 stuck recovery). Если вторая попытка тоже не помогла — останови миссию.

---

## Шаг 8. Проверить коннекторы базы перед парковкой

Перед реальной стыковкой выполни:

```bash
python examples/organized/parking/dock.py skynet-agent0 skynet-farpost0 100 --list-connectors
```

Проверь, что на базе есть свободный целевой коннектор.

Если все коннекторы заняты или нерабочие — останови миссию.

---

## Шаг 9. Пристыковаться к базе

**Сначала проверь дистанцию** от корабля до базы (через `gridinfo` или `check_docking_status`).

- **Если дистанция < 2 × dock_approach_distance** (т.е. < 200 м при approach=100) — корабль уже близко, пропусти long-approach:
  ```bash
  python examples/organized/parking/dock.py skynet-agent0 skynet-farpost0 --no-long-approach
  ```
  Без `--no-long-approach` v5 попытается отлететь на 500 м и вернуться — это пустая трата времени.

- **Если дистанция ≥ 200 м** — стандартная команда:
  ```bash
  python examples/organized/parking/dock.py skynet-agent0 skynet-farpost0 100
  ```

Успешным результатом считается вывод:

```text
DOCKING COMPLETE
```

Если стыковка не завершилась успешно — останови миссию.

После стыковки можно дополнительно проверить статус:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

---

## Шаг 10. Переложить руду на базу

Используй `pull_from_attached_ships.py` — он гибче `pull_items_from_docked_grid.py`: ищет пристыкованные корабли через коннекторы базы, не требует знать имя корабля заранее, умеет `--target-tag cargo` для авто-выбора контейнера и перебирает несколько целевых контейнеров.

Сначала dry-run (чтобы увидеть, что есть на корабле):

```bash
python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo --dry-run
```

Потом реальный перенос:

```bash
python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo
```

Если скрипт сообщает, что коннекторы не соединены, не паникуй. Сначала проверь стыковку:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

### Если cargo-контейнеры базы заполнены

**Известный баг:** `pull_from_attached_ships.py` падает с `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` в `pick_next_container()` когда target container полный, и не переключается на следующий cargo container. Workaround:

1. **Запусти pull ещё раз** — иногда 2-я попытка успешно находит другой target container.
2. **Если и 2-я попытка падает** — оставшиеся кг застрянут в ship. Зафиксируй это в финальном отчёте, спроси пользователя (продолжать или принять частичный результат).
3. **Альтернативный скрипт** (если нужно перенести всё):
   ```bash
   python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0 --force
   ```
   Этот скрипт старый, без Unicode-эмодзи в выводе, но менее гибкий (не ищет target по тегу, нужно знать имя контейнера).
4. **Самый надёжный путь** — увеличить ёмкость cargo-контейнеров базы (построить дополнительные Ore Storage).

**Лимит ёмкости:** Large Cargo Container вмещает ~400-500 т. Если миссия добыла >1М кг, в один контейнер это не влезет. Планируй несколько cargo containers на базе для больших миссий.

## Особенности по типу руды

Разные руды в SE ведут себя по-разному, и миссию нужно адаптировать:

### Ice (лёд)
- **Высокая скорость респауна** (секунды) — кластеры восстанавливаются быстро.
- **Большие кластеры** — 10-60 точек в радиусе 1-17 км.
- **1М кг в одном кластере реально за 2-5 мин** при правильном `--scan-radius` (5000-10000).
- **Можно безопасно продолжать mining до 100%** даже после нескольких падений скрипта.
- **Средний rate**: ~3 700 кг/с (против ~668 кг/с для платины).
- **Совет по mining**: используй `--scan-radius 5000-10000` сразу для amount > 100k. Не нужен fallback с `area-size 8`.

### Platinum / Palladium / Gold
- **Низкая скорость респауна** (минуты-часы) — кластеры восстанавливаются медленно.
- **Один кластер не даст >50 т за разумное время** (37 точек × 255 кг × 1 респаун = ~9 400 кг).
- **Для amount > 50 000 кг — несколько рейсов к разным кластерам** или принимай частичный результат.
- **Нужен fallback с `area-size 8`** (см. Шаг 6) — пустые точки между депозитами.
- **Средний rate**: ~668 кг/с.

### Stone (камень)
- Если в mining логе `Stone/Ore=inf` — увеличь `--max-stone-per-ore-ratio` или смени точку (`--point-strategy density`).
- Камень часто попадает в зону добычи вплотную к астероиду.

### Uranium
- **Средняя скорость респауна** (минуты).
- **Средние кластеры** (5-20 точек).
- **Mission default** — описан в шагах выше.

### Silicon, Nickel, Cobalt, Iron
- **Высокая скорость респауна** (секунды-минуты).
- Используй те же правила, что и для Ice (большие кластеры, высокий rate).

---

## Шаг 11. Финальная проверка

Проверь, что груз реально ушёл с корабля и пришёл на базу. **Не запускай dry-run после реального переноса** — он покажет 0 и ничего не верифицирует.

```bash
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py skynet-agent0
python docs/agent-skills/gaming/se-grid-status-report/scripts/grid_report.py skynet-farpost0
```

Сравни:
- `agent0`: `<ORE> Ore` должен быть **0** (или близко к 0);
- `farpost0`: `<ORE> Ore` должен вырасти на добытое количество.

Если на `agent0` остался `<ORE>` — повтори Шаг 10.

В финальном ответе пользователю сообщи:

```text
Миссия завершена:
- корабль: skynet-agent0
- база: skynet-farpost0
- руда: <ORE>
- цель добычи: <AMOUNT>
- фактически добыто: <XXX> кг
- стыковка с базой: да/нет
- перенос ресурсов: выполнен/не выполнен
- последняя успешная команда: ...
```

---

## Быстрая команда миссии для пользователя

Когда пользователь просит:

```text
добудь 3000 урана и верни на базу
```

агент должен использовать этот сценарий с параметрами:

```text
ship: skynet-agent0
base: skynet-farpost0
ore: Uranium
amount: 3000
base_gps: GPS:Base:-137317:-111140:-82039:
```

Для других руд / объёмов — подставить нужные `<ORE>` и `<AMOUNT>` во все шаги. Для объёмов ≥50 000 кг — сначала оцени размер локального кластера через `shared_map_deposits.py` и предупреди пользователя, если кластер мал (см. «Миссия по умолчанию → Подстановка параметров»).

---

## Что делать при типовых проблемах

### Нет известной точки Uranium

Выполни:

```bash
python examples/organized/radar/ore_scanner.py --grid skynet-agent0
```

Потом повтори:

```bash
python examples/organized/radar/shared_map/shared_map_deposits.py --grid skynet-agent0 --material Uranium --clusters --gps --limit 1
```

Если Uranium всё ещё не найден — останови миссию.

---

### Корабль не летит

Проверь, не пристыкован ли он:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

Если пристыкован:

```bash
python examples/organized/parking/smooth_undock.py skynet-agent0 skynet-farpost0 80
```

---

### База не имеет свободного коннектора

Выполни:

```bash
python examples/organized/parking/dock.py skynet-agent0 skynet-farpost0 100 --list-connectors
```

Если свободных коннекторов нет — останови миссию и сообщи пользователю.

---

### Перенос ресурсов не работает

Проверь стыковку:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

Если корабль пристыкован, попробуй в этом порядке:

1. **Перезапусти pull_from_attached_ships.py** — иногда 2-я попытка успешно находит другой target container:
   ```bash
   python examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo
   ```
2. **Альтернативный скрипт с --force** (если нужно перенести всё):
   ```bash
   python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0 --force
   ```
3. **Если cargo-контейнеры базы заполнены** — см. секцию "Если cargo-контейнеры базы заполнены" в Шаге 10.

---

## Запрещено

Не выполнять такие команды:

```bash
python examples/space_flight/space_navigator_v5.py --grid skynet-agent0 --target="GPS:Uranium_1:X:Y:Z:"
```

Не продолжать миссию после неуспешной стыковки.

Не парковаться без проверки свободных коннекторов.

Не использовать случайную GPS-цель, если Uranium не найден.

Не переносить ресурсы до успешной стыковки.

Не запускать v5 и mining без `python -u` и без перенаправления в файл — потеряешь логи в реальном времени.

Не верить логу v5 «летит, step=85» без проверки позиции через redis — скрипт может врать.

Не писать `goto` команды напрямую в Redis command queue — используй только `space_navigator_v5.py`.

Не продолжать mining, если процесс не показывает рост инвентаря ≥2 минуты — переходи к Шагу 6.5.
