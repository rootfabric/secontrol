# Nanobot BARS Grind Mode — детали

## Что работает

- **Grind-by-color**: наносборщик разбирает блоки, чей ColorMaskHSV точно совпадает с grind color
- **Разбирает ВСЕ типы блоков**: и structural (armor), и functional (solar panel, battery, cargo)
- **API paint_block** корректно красит блоки в нужный цвет
- **Включение через set_enabled(True)** — наносборщик начинает работу

## Что НЕ работает

- **set_grind_color через API** — команды уходят (result=1), мод игнорирует
- **set_mode(2) через API** — аналогично, мод не переключает режим
- **set_use_grind_color(True) через API** — аналогично
- **Telemetry** — наносборщик НЕ передаёт grind state в Redis (нет ключей buildandrepair_*)

## Workflow (подтверждён 2026-05-16)

1. Игрок настраивает в игре: режим Grind, Use Grind Color, цвет
2. Определить grind color: экспорт блюпринта → найти ColorMaskHSV блока, который наносборщик уже разбирает
3. Покрасить целевые блоки: `paint_block(hsv=[H, (y+1)/2, (z+1)/2])`
4. Включить наносборщик: `welder.set_enabled(True)`
5. Ждать ~60-90 секунд
6. Проверить экспорт — блоки должны исчезнуть

## Пример из сессии

- Grind color: H=321, S=60, V=52 (в формате ColorMaskHSV: y=0.2, z=0.05)
- Железный блок: ColorMaskHSV (0.8917, 0.2, 0.05) → ✅ разобран
- Солнечная панель: ColorMaskHSV (0.8917, 0.200000048, 0.0499999523) → ✅ разобран
- Время: ~60 секунд на оба блока
- Блоков было 11 → стало 9

## Важно: точность цвета

Nanobot сравнивает ColorMaskHSV с высокой точностью. При различии в 1 единицу S (например S=100 vs S=60) блок НЕ разбирается. Всегда брать точные значения из экспорта.

## Telemetry наносборщика

В Redis содержится только:
- `enabled`, `isWorking`, `isFunctional`, `deviceKind`
- `load` (performance metrics)
- `items` (инвентарь)
- `gridId`, `gridName`, `id`, `name`, `subtype`, `type`, `ownerId`, `timestamp`

Отсутствуют (НЕТ ключей в Redis):
- `buildandrepair_grindcolor`
- `buildandrepair_mode`
- `buildandrepair_workmode`
- `buildandrepair_usegrindcolor`
- `buildandrepair_allowbuild`
- `possibleGrindTargets`
- `currentGrindTarget`

**Невозможно прочитать grind state через API** — только визуально в игре.
