# Pull from attached ships: Unicode crash

## Симптом

`examples/organized/container/advanced/pull_from_attached_ships.py` падает
на Windows консоли (cp1251) при попытке напечатать Unicode-символы:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 30: character maps to <undefined>
```

Символ `\u2192` — это стрелка `→` в логе типа:
```
>>> Large Cargo Container  [container]
    24,895 x MyObjectBuilder_Ore:Gold Ore →
    [ERROR] 'charmap' codec can't encode character '\u2192'
```

То же самое с `\u2705` (✅) в `dock.py`:
```
print("\n✅ DOCKING COMPLETE")
UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'
```

## Что сломалось

Windows PowerShell по умолчанию использует кодировку `cp1251` (русская
кодировка). Python 3 пытается напечатать `→` или `✅` в stdout, драйвер
консоли не знает этих символов → exception.

Скрипт падает **между обработкой контейнеров**, до фактического
переноса. Это значит, что часть руды может не перенестись, и
необходимо перезапускать.

## Workarounds (по убыванию надёжности)

### 1. Установить UTF-8 для stdout (рекомендую)

В начале скрипта добавить:

```python
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
```

Это решает проблему для всех Unicode-символов.

### 2. Заменить `\u2192` и `\u2705` на ASCII

В `pull_from_attached_ships.py` заменить:
- `→` на `->`
- `✅` на `OK:`
- `❌` на `FAIL:`
- прочие эмодзи на ASCII

Быстрый фикс через grep:

```bash
python -c "
import re
p = 'examples/organized/container/advanced/pull_from_attached_ships.py'
with open(p, encoding='utf-8') as f: s = f.read()
s = s.replace('→', '->').replace('✅', 'OK:').replace('❌', 'FAIL:')
with open(p, 'w', encoding='utf-8') as f: f.write(s)
"
```

### 3. Установить PYTHONIOENCODING

```bash
PYTHONIOENCODING=utf-8 python examples/organized/container/advanced/pull_from_attached_ships.py ...
```

Работает, но нужно не забывать каждый раз.

### 4. Перенаправить вывод в файл

```bash
python -u examples/organized/container/advanced/pull_from_attached_ships.py --base-grid skynet-farpost0 --target-tag cargo > tmp/pull.log 2>&1
```

В файл пишется в UTF-8, проблем нет. Но терминал всё равно падает.

## Playbook уже знает об этом

`docs/agents-missions/se-ore-collection-mission.md` секция "Если cargo-контейнеры базы заполнены" описывает этот баг и рекомендует:

1. Запустить pull ещё раз
2. Если падает — оставшиеся кг застрянут
3. Альтернативный скрипт: `pull_items_from_docked_grid.py --force`

В моей миссии вторая попытка "0 контейнеров" — это значит, что первая
попытка **успела перенести часть** (судя по тому, что на базе 37 799 кг,
а в dry-run было только 24 895 кг — то есть что-то ещё перенеслось
помимо Large Cargo Container).

## Рекомендация

Создать `pre-commit hook` или просто quick-fix оба скрипта
(`pull_from_attached_ships.py` и `dock.py`) с заменой Unicode на ASCII
или с обёрткой stdout. Это разовая работа, убирает 2 известных бага.
