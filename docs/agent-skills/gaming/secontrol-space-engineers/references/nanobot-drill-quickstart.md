# Nanobot Drill — быстрый старт для агента

## Одной строкой (рекомендуется)

```python
drill.start_drilling_ore(["Ice"])           # только лёд
drill.start_drilling_ore(["Uranium"])        # только уран
drill.start_drilling_ore(["Iron", "Nickel"]) # железо и никель
```

Метод `start_drilling_ore` делает всё сам:
1. `stop_drilling()` + `turn_off()`
2. `set_script_controlled(True)`
3. `set_collect_filter(["Ore"])` — не `["all"]`, иначе берёт камень
4. `set_ore_filters(ore_subtypes, work_mode="Collect")`
5. `set_work_mode("Collect")`
6. `set_script_controlled(False)`
7. `turn_on()`

## Проверка

```python
drill.update()
print("work mode:", drill.get_work_mode())
print("known ores:", drill.debug_get_enabled_known_ores())
```

Должно быть: `work mode: Collect`, нужный `ore: True`, остальные `False`.

## Важно

- **Не** использовать `drill.start_drilling()` (режим Drill)
- **Не** использовать `drill.set_collect_filter(["all"])`
- OreHash: Stone=1137917536, Ice=1579040667, Iron=2112235764, Nickel=-723128632 и т.д.