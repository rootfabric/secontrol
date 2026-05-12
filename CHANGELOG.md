# Changelog

## [0.3.x] — 2025

- Auto-wake on `Grid` construction: `Grid.__init__` now accepts `auto_wake=True` and wakes the grid automatically.
- Added device uptime visualization utilities (`tools/telemetry_reader.py`, `tools/telemetry_reader_gui.py`).
- Added retry logic for Redis operations and worker API access (`tenacity`).

## [0.3.0] — 2025

- Bumped to version 0.3.0.
- Grid search via `Grids.search()`.
- Worker API integration with retries.
- `Grid.from_name()` factory method.
- `send_grid_command()` with auto-populated metadata fields.

## [0.1.0] — 2024-05-29

- Начальная публикация библиотеки `secontrol`.
- Добавлен высокоуровневый клиент `RedisEventClient` и утилиты для работы с гридами.
- Добавлены примеры использования и базовые тесты.
- Настроена упаковка проекта через `pyproject.toml`.
