---
name: se-grid-find-by-name
description: Быстрый поиск грида по имени/подстроке и получение его grid_id. Используй, когда оператор называет грид вслух ("база фарпост", "skynet-agent0") и нужно мгновенно получить id без перебора списка вручную.
---

# SE Grid — поиск по имени

Одна задача: **имя (или его часть) → `grid_id`**. Делается одним вызовом.

## 1. Самый быстрый путь — CLI-скрипт

```bash
# Все гриды (список id + имён)
python docs/agent-skills/gaming/se-grid-find-by-name/scripts/find_grid.py

# Один грид по подстроке
python docs/agent-skills/gaming/se-grid-find-by-name/scripts/find_grid.py farpost0

# Кириллица тоже работает (если такое имя есть в игре)
python docs/agent-skills/gaming/se-grid-find-by-name/scripts/find_grid.py "база фарпост"

# Только id (для пайплайнов)
python docs/agent-skills/gaming/se-grid-find-by-name/scripts/find_grid.py farpost0 --id-only
```

Скрипт печатает `grid_id, name` (или просто `grid_id` с `--id-only`) и завершается с кодом 0 при найденном гриде, 1 — если не найдено.

## 2. Из Python — одна строка

```python
from secontrol.common import get_all_grids
gid, gname = next((g for g in get_all_grids() if "farpost0".lower() in g[1].lower()), (None, None))
```

Или сразу получить живой объект `Grid` (подписка на телеметрию + `wake`):

```python
from secontrol.common import prepare_grid
grid = prepare_grid("farpost0")   # имя/подстрока ИЛИ числовой id
```

## 3. Как это работает (коротко)

- Источник истины — Redis-ключ `se:{REDIS_USERNAME}:grids` (его пишет SE-мост).
- Резолвер: `_resolve_grid_identifier()` в `src/secontrol/common.py:142` — сначала точное равенство, затем `query.lower() in name.lower()` по полям `name`/`gridName`/`displayName`.
- Суб-гриды отбрасываются автоматически (`_is_subgrid()` там же).
- В памяти держится живой кэш: `Grids._states` в `src/secontrol/grids.py:1773` (`Grids.search()`).

## 4. Главные грабли

1. **Алиасов нет.** «Имя оператора» = имя грида в игре. Хочешь `"база фарпост"` — переименуй грид в SE (Info → Name) или заведи маппинг в `common.py` поверх `_resolve_grid_identifier`.
2. **Поиск — substring, не fuzzy.** Запрос должен быть подстрокой реального имени: `farpost0` матчит `skynet-farpost0`, а `фарпост` НЕ матчит `farpost0` (разные строки). Регистр игнорируется.
3. **Несколько совпадений = ошибка.** Если подстрока неоднозначна (`--grid baza` → `baza0`, `baza1`, `baza2`), `_resolve_grid_identifier` кинет `ValueError`. Добавь уточнение (`baza0`).
4. **Кириллица в Redis работает**, но имя в SE-мосте и в скрипте должно совпадать байт-в-байт. Проверь список: `python scripts/find_grid.py`.

## 5. Чек-лист оператора

- [ ] Не знаю точного имени → `python scripts/find_grid.py` (без аргументов) — копирую из списка.
- [ ] Знаю подстроку → `python scripts/find_grid.py <подстрока>`.
- [ ] Хочу готовый `Grid` в скрипте → `prepare_grid("подстрока")`.
- [ ] Не нашлось → в выводе будет полный список имён — ищу похожее.
- [ ] Кириллица не работает → грид в игре назван латиницей, маппинга нет.
