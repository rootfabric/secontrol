# secontrol

`secontrol` — это высокоуровневый клиент для взаимодействия с Redis-шлюзом Space Engineers. Библиотека упрощает получение телеметрии, отправку команд и реализацию автоматизаций, используя устойчивые подписки на ключевые события.

## Возможности

- Подключение к Redis с помощью конфигурации из `.env` или аргументов конструктора.
- Наблюдение за ключами и каналами с автоматическим восстановлением подписок.
- Утилиты для получения идентификаторов владельца, игрока и грида.
- Примеры, демонстрирующие публикацию команд и мониторинг состояний.

## Установка

После публикации на PyPI библиотеку можно будет установить стандартным способом:

```bash
pip install secontrol
```

До публикации можно установить пакет из исходников:

```bash
pip install .
```

## Быстрый старт

```python
from secontrol.common import prepare_grid

#Первый грид игрока
client, grid = prepare_grid()
#Устройства на гриде
print(", ".join((d.name or f"{d.device_type}:{d.device_id}") for d in grid.devices.values()) or "(no devices)")

```

### Переменные окружения

| Переменная        | Назначение                                              |
| ----------------- | ------------------------------------------------------- |
| `REDIS_URL`       | URL Redis-инстанса (по умолчанию `redis://api.outenemy.ru:6379/0`). |
| `REDIS_USERNAME`  | Имя пользователя для авторизации.                       |
| `REDIS_PASSWORD`  | Пароль для подключения.                                 |
| `SE_PLAYER_ID`    | Идентификатор игрока Space Engineers.                   |
| `SE_GRID_ID`      | Идентификатор грида. Если не задан, используется первый доступный. |

Переменные можно определить в файле `.env` в корне проекта или системы. Модуль автоматически читает файл с помощью [`python-dotenv`](https://pypi.org/project/python-dotenv/).

## Примеры

Готовые скрипты находятся в каталоге [`sepy/examples`](src/secontrol/examples). Чтобы запустить пример:

```bash
python -m secontrol.examples.list_grids
```

## Разработка

1. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]
   ```
2. Запустите тесты:
   ```bash
   pytest
   ```

## Подготовка и публикация пакета

1. Обновите версию в `pyproject.toml` и `src/secontrol/__init__.py`.
2. Сформируйте wheel и sdist:
   ```bash
   python -m build
   ```
3. Проверьте содержимое архива:
   ```bash
   tar tzf dist/secontrol-<версия>.tar.gz
   ```
4. Загрузите пакет на TestPyPI:
   ```bash
   twine upload --repository testpypi dist/*
   ```
5. Убедитесь, что установка проходит успешно:
   ```bash
  pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple secontrol
   ```
6. Опубликуйте на PyPI:
   ```bash
   twine upload dist/*
   ```

После публикации команда `pip install sepy` станет доступной всем пользователям.

## Лицензия

Проект распространяется по лицензии MIT. См. файл [LICENSE](LICENSE).

