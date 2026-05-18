# ColorMaskHSV → paint_block конвертация

## Формат ColorMaskHSV в blueprint XML

```xml
<ColorMaskHSV x="0.891666651" y="0.2" z="0.05" />
```

- `x` = H / 360 (0..1). Пример: H=321° → x=0.8917
- `y` = saturation в диапазоне -1..1
- `z` = value в диапазоне -1..1

## Формат paint_block API

```python
g.paint_block(block_id, hsv=[H, S, V])
```

- H: 0-360 (прямое значение, нормализуется делением на 360)
- S: 0-1 (проходит через `_normalize_unit`, 0-1 остаётся как есть)
- V: 0-1 (аналогично)

## Формула конвертации

```python
api_S = (colorMask_y + 1) / 2
api_V = (colorMask_z + 1) / 2
```

## Примеры из сессии 2026-05-16

### Железный блок (разбирается наносборщиком)

| Поле | XML значение | API значение |
|------|-------------|-------------|
| x (H) | 0.891666651 | 321 |
| y (S) | 0.2 | 0.6 |
| z (V) | 0.05 | 0.525 |

```python
g.paint_block(block_id, hsv=[321, 0.6, 0.525])
# → ColorMaskHSV: x=0.891666651, y=0.200000048, z=0.0499999523
# Float-шум ~5e-8, не влияет на gameplay
```

### Блоки по умолчанию

| Поле | XML значение | API значение |
|------|-------------|-------------|
| x (H) | 0 | 0 |
| y (S) | -0.8 | 0.1 |
| z (V) | 0 | 0.5 |

## НЕПРАВИЛЬНЫЕ формулы (не использовать!)

```python
# ❌ НЕПРАВИЛЬНО: game_S / 100
hsv=[321, 100/100, 50/100]  # → ColorMaskHSV y=1.0, z=0.0 — НЕ то что нужно!

# ❌ НЕПРАВИЛЬНО: RGB покраска
paint_block(block_id, rgb=[127, 0, 82])  # → ColorMaskHSV y=1.0, z=-0.004 — другой результат!

# ✅ ПРАВИЛЬНО: из ColorMaskHSV через формулу
api_S = (0.2 + 1) / 2  # = 0.6
api_V = (0.05 + 1) / 2  # = 0.525
paint_block(block_id, hsv=[321, 0.6, 0.525])
```

## Важно: формат терминала игры ≠ ColorMaskHSV

Игровой терминал показывает HSV в своём формате (H=0-360, S и V могут быть 0-100 или другой шкалы).
Этот формат **не совпадает** напрямую с ColorMaskHSV в XML. Нельзя брать S/V из терминала
и делить на 100 — результат будет неправильным.

**Единственный надёжный способ:** экспорт блюпринта → чтение ColorMaskHSV из XML → пересчёт.

## Верификация

```python
proj.request_grid_blueprint(include_connected=False)
time.sleep(10)
snap = proj.blueprint_snapshot()
import xml.etree.ElementTree as ET
root = ET.fromstring(snap['xml'])
for cb in root.iter('MyObjectBuilder_CubeBlock'):
    color = cb.find('ColorMaskHSV')
    if color is not None:
        x, y, z = color.get('x'), color.get('y'), color.get('z')
        # Точные строки без float-конвертации
        print(f"  {cb.findtext('SubtypeName')}: x={x}  y={y}  z={z}")
```
