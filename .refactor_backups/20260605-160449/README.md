# secontrol refactor solution

Архив содержит готовое решение для рефакторинга структуры `rootfabric/secontrol`.

## Что делает `apply_refactor.py`

- Создаёт верхнеуровневый каталог `commands/` для боевых команд агента.
- Копирует рабочие скрипты из старых путей `examples/organized/...` в `commands/...`.
- Оставляет совместимые wrappers на старых путях, чтобы не сломать существующие команды.
- Разделяет `commands/` и `examples/`: первые — для запуска агентом, вторые — для обучения SDK.
- Переписывает `AGENTS.md` как единый вход для агента.
- Добавляет `.env.example`.
- Добавляет `docs/QUICKSTART_AGENT.md`, `docs/COMMANDS.md`, `commands/README.md`, `examples/README.md`, `docs/README.md`.
- Копирует playbook-и в `docs/playbooks/`.
- Обновляет `README.md`, добавляя быстрый старт агента и новые ссылки.
- Пишет отчёт применения в `tmp/refactor_manifest.md`.
- Сохраняет заменённые файлы в `.refactor_backups/`.

## Как применить

Скопируй `apply_refactor.py` в корень локального репозитория `secontrol` и запусти:

```bash
python apply_refactor.py
```

Для Windows PowerShell:

```powershell
python .\apply_refactor.py
```

После применения проверь:

```bash
python commands/diagnostics/list_grids.py
python commands/radar/space_survey.py --grid agent1
python commands/docking/check_docking_status.py --grid agent1
```

Если Redis или Space Engineers gateway недоступны, эти команды могут падать уже на подключении. Это нормально: скрипт рефакторинга проверяет синтаксис Python-файлов, но не может проверить живой игровой сервер без окружения.

## Новый принцип структуры

```text
src/secontrol/        Python SDK
commands/             runnable operational commands for agents
examples/             small educational SDK examples
docs/playbooks/       operator, developer, admin guides
docs/workflows/       multi-step workflows
docs/skills/          reusable agent skills
tests/                tests
tmp/                  temporary files only
```

## Правило для агентов

1. Сначала искать готовую команду в `commands/`.
2. Если команды нет — искать SDK-пример в `examples/`.
3. Если примера нет — читать `docs/playbooks/developer.md` и только потом писать код.
