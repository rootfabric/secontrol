# Рекомендуемый набор скриптов Nanobot Drill Automation Fix v12

> Index: `AGENTS.md` — Добыча ресурсов | Agent instructions: `nanodrill_agent.md`

Основной набор:

- `mine_ore_robot_safe_live_move.py` — основной универсальный добывающий скрипт.
- `mine_platinum_simple_v11_safe.py` — проверенный простой сценарий для Platinum.
- `scan_probe_mine_ore.py` — общий helper/fallback; нужен `mine_platinum_simple_v11_safe.py`.
- `configure_ore_only.py` — безопасная настройка фильтра Ore + выбранная руда без добычи.
- `stop_drill.py` — аварийная остановка.
- `set_nanodrill_area.py` — диагностика/расчет области, не использовать перед добывающим скриптом.
- `check_nanodrill_strict_patch.py` — диагностика активного patch/mod.
- `clear_until_platinum_visible.py`, `sweep_clear_until_ore_visible.py` — специальные сценарии вскрытия, не обычная добыча.
- `nanodrill_agent.md` — инструкция агенту.

Папка `deprecated/` содержит старые или опасные варианты. Агент не должен использовать их по умолчанию.
