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
amount: 10000
base_gps: GPS:Base:-137317:-111140:-82039:
undock_distance: 80
dock_approach_distance: 100
```

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
python examples/space_flight/space_navigator_v5.py --grid skynet-agent0 --target="GPS:Uranium_cluster_1:-123456.0:-111222.0:-82333.0:#44FF44:" --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80
```

Важно:

- не используй примерные координаты;
- не используй `X:Y:Z`;
- всегда вставляй реальную GPS-строку из `shared_map_deposits.py`.

Если полёт завершился ошибкой или корабль не достиг цели — останови миссию.

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

Выполни:

```bash
python examples/organized/drill_nano/mine_ore_robot_safe_live_move.py --grid skynet-agent0 --ore Uranium --amount 3000 --scan-radius 1500 --area-size 75 --density-radius 20 --max-points 120 --startup-timeout 90 --no-progress-timeout 60
```

После завершения внимательно проверь вывод.

Успешным результатом считается ситуация, когда скрипт явно показывает, что добыча завершена или нужное количество достигнуто.

Если добыча не началась, нет прогресса, не найдена руда или корабль не может добывать — останови миссию.

---

## Шаг 7. Вернуться на базу

Выполни:

```bash
python examples/space_flight/space_navigator_v5.py --grid skynet-agent0 --target="GPS:Base:-137317:-111140:-82039:" --max-speed 95 --far-speed 75 --medium-speed 35 --close-speed 8 --arrival 80
```

Если полёт на базу завершился ошибкой — останови миссию.

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

Выполни:

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

Выполни:

```bash
python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0
```

Если скрипт сообщает, что коннекторы не соединены, не используй `--force` сразу.

Сначала проверь стыковку:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

Если корабль действительно пристыкован, но перенос не работает, можно повторить перенос с `--force`:

```bash
python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0 --force
```

---

## Шаг 11. Финальная проверка

Выполни:

```bash
python examples/organized/parking/check_docking_status.py --grid skynet-agent0
```

Затем выполни диагностический dry-run переноса:

```bash
python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0 --dry-run
```

В финальном ответе пользователю сообщи:

```text
Миссия завершена:
- корабль: skynet-agent0
- база: skynet-farpost0
- руда: Uranium
- цель добычи: 3000
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

Если корабль пристыкован, повтори перенос с force:

```bash
python examples/organized/container/advanced/pull_items_from_docked_grid.py --source-grid skynet-agent0 --target-grid skynet-farpost0 --force
```

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
