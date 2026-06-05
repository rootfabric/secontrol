# Проверка после применения

## 1. Проверка установки пакета

```bash
python -c "import secontrol; print(secontrol.__file__)"
```

## 2. Проверка структуры

```bash
python - <<'PY'
from pathlib import Path
required = [
    'commands/README.md',
    'examples/README.md',
    'docs/QUICKSTART_AGENT.md',
    'docs/COMMANDS.md',
    'docs/playbooks/operator.md',
    'docs/playbooks/developer.md',
    'AGENTS.md',
    '.env.example',
]
missing = [p for p in required if not Path(p).exists()]
if missing:
    raise SystemExit('Missing: ' + ', '.join(missing))
print('Structure OK')
PY
```

## 3. Проверка синтаксиса

```bash
python -m compileall commands examples/basic examples/devices examples/controllers
```

## 4. Проверка живых команд

```bash
python commands/diagnostics/list_grids.py
python commands/radar/space_survey.py --grid agent1
python commands/docking/check_docking_status.py --grid agent1
```

Живые команды требуют заполненный `.env`, Redis gateway и доступный Space Engineers server integration.
