---
name: se-projector-save-blueprint
description: Сохранить blueprint XML грида через проектор (`projector.request_grid_blueprint`). Пишет в канонический `Blueprints/local/<grid>/bp.sbc` и/или дополнительные пути через `--also-copy` (например, репо `C:\secontrol\blueprints\<grid>-raw.sbc`). Используй, когда оператор говорит "сохрани схему с грида", "экспортируй чертёж", "save blueprint of scout4", "копируй blueprint в сейвы". Требует, чтобы на гриде был Projector — это не альтернатива игровому "Save", а обёртка над on-board projector plugin.
---

# SE Projector — сохранение чертежа с грида

Один шаг: `projector.request_grid_blueprint(include_connected=True)` → плагин сериализует грид (и прицепленные subgrids) в `MyObjectBuilder_ShipBlueprintDefinition` XML, складывает в Redis-ключ `…:projector:<eid>:blueprint` → скрипт забирает XML и пишет в файл.

> **Важно:** это **не** игровое сохранение в мир-сейв (`Saves/<steamid>/<save>/`), а выгрузка XML чертежа через проектор. Если нужен именно мир-сейв — нажми "Save" в Info-панели Control Panel/Cockpit в игре.

---

## 1. Самый быстрый путь — CLI

```bash
# В канонический Blueprints/local/<grid>/bp.sbc
python docs/agent-skills/gaming/se-projector-save-blueprint/scripts/save_grid_blueprint.py skynet-scout4

# Одновременно в репо (для бэкапа и сравнения)
python docs/agent-skills/gaming/se-projector-save-blueprint/scripts/save_grid_blueprint.py skynet-scout4 \
    --also-copy "C:\secontrol\blueprints\skynet-scout4-raw.sbc"

# Только хост-грид, без прицепленных subgrids
python docs/agent-skills/gaming/se-projector-save-blueprint/scripts/save_grid_blueprint.py skynet-scout4 \
    --no-include-connected

# Сухой прогон: проверить, что проектор есть, но не запрашивать экспорт
python docs/agent-skills/gaming/se-projector-save-blueprint/scripts/save_grid_blueprint.py skynet-scout4 --dry-run

# Кастомный путь и таймаут
python docs/agent-skills/gaming/se-projector-save-blueprint/scripts/save_grid_blueprint.py skynet-scout4 \
    --output D:/backups/scout4.sbc --timeout 60
```

Скрипт:
1. `prepare_grid(<grid>)` — резолв по подстроке имени или числовому `grid_id`.
2. `refresh_devices()` + поиск Projector.
3. `set_enabled(True)`, если проектор выключен (с verify через `wait_for_telemetry` 5 с).
4. `request_grid_blueprint(include_connected=…)` → polling snapshot до 30 с.
5. `Path.write_text(xml, encoding='utf-8')` в основной путь.
6. Sanity-check: `MyObjectBuilder_ShipBlueprintDefinition` + подсчёт `<CubeGrid>` / `<MyObjectBuilder_CubeBlock>`.
7. Копирование во все `--also-copy` пути (создаёт родительские директории).

Exit code 0 = записано и проверено; 1 = нет проектора / таймаут / sanity провалился.

---

## 2. Куда попадает файл

| Флаг | Путь |
|---|---|
| (по умолчанию) | `%APPDATA%/SpaceEngineers/Blueprints/local/<gridname>/bp.sbc` |
| `--output PATH` | любой `.sbc` файл (создаст родительские директории) |
| `--also-copy PATH` | дополнительная копия (повторяемый флаг) |
| `--also-copy ... --also-copy ...` | несколько зеркал одной операцией |

Канонический путь совпадает с тем, что использует `align_clone_projection.py:1885` (`%APPDATA%/SpaceEngineers/Blueprints/local/<grid>/bp.sbc`) — после экспорта через этот skill файл сразу готов как input для clone-миссии.

### 2.1 Конвенция имён в `C:\secontrol\blueprints\`

В репо лежат "raw" выгрузки больших гридов:

| Файл | Что внутри |
|---|---|
| `skynet-baza0-raw.sbc` | сырая выгрузка `skynet-baza0` |
| `skynet-baza0-clone.sbc` | тот же blueprint, модифицированный под клон |
| `skynet-baza0-second-ship.sbc` | второй корабль, экспортированный отдельно |
| `skynet-baza0-second-ship-shifted.sbc` | со сдвигом по контактной паре |

Конвенция: `<grid>-raw.sbc` для "как есть" выгрузки через проектор. Имя скриптом не навязывается — оператор выбирает явно через `--also-copy`.

---

## 3. Из Python — три строки

```python
from secontrol.common import prepare_grid, close
from pathlib import Path

grid = prepare_grid("skynet-scout4")
proj = grid.find_devices_by_type("projector")[0]
proj.request_grid_blueprint(include_connected=True)
# poll projector.blueprint_xml() или projector.blueprint_snapshot()["xml"]
```

Низкоуровневый API живёт в `src/secontrol/devices/projector_device.py:176`:

- `request_grid_blueprint(*, include_connected: bool = True) -> int` — отправляет `cmd: "export_grid_blueprint"` в Redis.
- `blueprint_key() -> str` — `…:projector:<eid>:blueprint` (где лежит snapshot).
- `blueprint_snapshot() -> dict | None` — весь JSON, ключи: `ok`, `xml`, `gridId`, `gridName`, `gridCount`, `deviceId`, `ownerId`, `timestamp`, `includeConnected`, `blueprintName`.
- `blueprint_xml() -> str | None` — только XML строка (или `None`, если snapshot не пришёл).

---

## 4. Что лежит в snapshot

Из реального прогона на `skynet-scout4`:

```python
{
  "ok": True,
  "gridId": 80038600480686266,
  "deviceId": 106422666481729834,
  "ownerId": 144115188075855919,
  "timestamp": "2026-06-10T13:47:29.2563241Z",
  "gridName": "skynet-scout4",
  "includeConnected": True,
  "gridCount": 1,
  "blueprintName": "skynet-scout4",
  "xml": "<?xml version=\"1.0\" encoding=\"utf-16\"?>\r\n<MyObjectBuilder_ShipBlueprintDefinition ..."
}
```

- `xml` — UTF-16 declared, реально UTF-8 content. Это особенность SE projector-плагина, не баг скрипта.
- `gridCount` — сколько CubeGrid внутри. Для `include_connected=True` может быть > 1, если грид приварен merge-блоками.
- `blueprintName` — обычно равен `gridName`, но плагин может подставить другое.

---

## 5. Формат XML: в чём отличие от игрового "Save"

Игровое "Save" (через Info-панель Control Panel) пишет:

```xml
<?xml version="1.0"?>
<Definitions xmlns:xsd="…" xmlns:xsi="…">
  <ShipBlueprints>
    <ShipBlueprint xsi:type="MyObjectBuilder_ShipBlueprintDefinition">
      <Id …/> <DisplayName>…</DisplayName> <CubeGrids>…</CubeGrids>
    </ShipBlueprint>
  </ShipBlueprints>
</Definitions>
```

Projector export пишет "сырой" `ShipBlueprintDefinition` без `<Definitions>` обёртки:

```xml
<?xml version="1.0" encoding="utf-16"?>
<MyObjectBuilder_ShipBlueprintDefinition xmlns:xsd="…" xmlns:xsi="…">
  <Id …/> <DisplayName>…</DisplayName> <CubeGrids>…</CubeGrids>
</MyObjectBuilder_ShipBlueprintDefinition>
```

**Оба формата валидны для SE.** Projector style принимается напрямую через `load_blueprint_xml(xml)` (проверка на наличие `MyObjectBuilder_ShipBlueprintDefinition` строки в `projector_device.py:164`). `align_clone_projection.py:442` (`parse_blueprint`) умеет нормализовать оба варианта в общий dict.

Если нужно скормить XML инструменту, который ждёт `<Definitions>` обёртку (например, vanilla SE Save), оберни вручную:

```python
inner = path.read_text(encoding="utf-8")
stripped = inner[inner.index("<MyObjectBuilder_ShipBlueprintDefinition"):]
wrapped = (
    '<?xml version="1.0"?>\n'
    '<Definitions xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    f'{stripped}\n</Definitions>'
)
Path("wrapped.sbc").write_text(wrapped, encoding="utf-8")
```

---

## 6. Граблей (из реальной сессии)

### 6.1 Нет проектора на гриде

Самая частая причина фейла. Проверка:

```bash
python -c "
from secontrol.common import prepare_grid
g = prepare_grid('skynet-scout4')
g.refresh_devices()
for d in g.find_devices_by_type('projector'):
    print('OK:', d.name)
else:
    print('NO PROJECTOR')
"
```

Если проектора нет — скрипт не поможет. Либо построй проектор на гриде, либо используй игровое "Save" через Info-панель Control Panel/Cockpit.

### 6.2 Таймаут `blueprint_snapshot` (30 с по умолчанию)

Симптом: `ERROR: blueprint XML did not appear within 30s`. Причины по убыванию вероятности:

1. **Projector выключен** — `set_enabled(True)` уже шлётся автоматически, но проверь, что после `set_enabled` `enabled=True` в телеметрии. Если grid_report показывает `enabled=false` сразу после команды — питания нет (см. skill `se-grid-creation`, грабли 4.3).
2. **Projector functional=False** — повреждён. Почини в игре.
3. **Grid не "проснулся"** — `prepare_grid(..., auto_wake=True)` делает это по умолчанию, но в редких случаях плагин не реагирует. Перезайди в игру или перезапусти server.
4. **Plugin не зарегистрирован** — проверь `redis-cli ping` и `.env` (`REDIS_USERNAME` / `REDIS_PASSWORD`).

Подними `--timeout 60` для больших гридов (>200 блоков). Для гридов >1000 блоков может потребоваться несколько вызовов с retry — добавь внешний retry-loop.

### 6.3 XML записался, но sanity-check ругается

`Sanity` в скрипте проверяет только наличие `MyObjectBuilder_ShipBlueprintDefinition` строки. Если её нет — плагин вернул что-то странное. Возможные причины:

- Плагин вернул `ok=false` (проверь `proj.blueprint_snapshot()` руками).
- Сторонний блок с malformed XML (очень редко).
- Битый Redis-канал — перезапусти плагин.

### 6.4 Snapshot не очищается между вызовами

Если вызвать `request_grid_blueprint` дважды подряд, **первый snapshot остаётся** в Redis до прихода нового. Скрипт всегда забирает свежий `ok=True` snapshot, так что эта особенность безопасна — но если ты читаешь `blueprint_xml()` руками, фильтруй по `ok=True` и свежему `timestamp`.

### 6.5 `include_connected=False` всё равно тащит merge-locked subgrids

По наблюдениям: `include_connected=False` экспортирует **только хост-грид**, на котором стоит проектор. Merge-locked subgrids игнорируются. Это полезно для "снять схему именно этого корабля, без приваренных модулей".

Если нужно включить subgrids — оставь `--include-connected` (по умолчанию). Тогда `gridCount` в snapshot станет > 1, и `CubeGrid`-блоков в XML будет несколько.

### 6.6 `utf-16` declared, реально `utf-8`

`xml.etree.ElementTree` падает на парсинге (`Document labelled UTF-16 but has UTF-8 content`). Это нормально для SE projector XML. Если нужно распарсить из Python — используй `lxml.etree` или читай руками:

```python
text = path.read_bytes().decode("utf-8")  # реально utf-8
import re
subtypes = re.findall(r"<SubtypeName>([^<]+)</SubtypeName>", text)
```

### 6.7 Grid rename после экспорта

Имя в `gridName` snapshot берётся из текущего имени грида. Если ты переименовал грид между экспортами, новый файл ляжет в `Blueprints/local/<новое_имя>/bp.sbc`. Старая директория останется как артефакт — удаляй руками, если мешает.

### 6.8 Projector на subgrid (приварен ротором)

Если projector стоит на subgrid (rotor/piston), скрипт увидит его через `grid.find_devices_by_type("projector")`, но `request_grid_blueprint` сериализует **весь механически слитый грид целиком**, включая rotor-host. Чтобы экспортировать только subgrid — нужна отдельная логика с фильтрацией по `EntityId` родительского грида. Текущий скрипт этого не делает, считай `gridCount` в snapshot.

---

## 7. Verify-чек-лист оператора

- [ ] На гриде есть Projector? `find_devices_by_type("projector")` не пусто.
- [ ] Projector `enabled=true`? (Скрипт сам починит, но verify после.)
- [ ] Projector `functional=true`? Если нет — `enabled` будет откатываться.
- [ ] `grid_report.py <grid>` показывает power > 0? Без питания `enable()` через 1-2 тика откатится (см. `se-grid-creation` §4.3).
- [ ] После экспорта sanity прошёл: `Sanity: {'size_bytes': …, 'grid_count': 1, 'block_count': 27}`.
- [ ] Файл существует по ожидаемому пути и ненулевой.

---

## 8. Связанные skills / скрипты

| Что | Где |
|---|---|
| Mission: выровненный клон через merge/connector | `docs/agents-missions/se-projector-clone-mission.md` |
| Mass enable devices (если projector не включился) | `docs/agent-skills/gaming/se-grid-enable-devices/SKILL.md` |
| Grid wakeup (если power grid лежит) | `docs/agent-skills/gaming/se-grid-creation/SKILL.md` §4 |
| Find grid by name | `docs/agent-skills/gaming/se-grid-find-by-name/SKILL.md` |
| API reference: Projector | `docs/DEVICE_REFERENCE.md` (строки 240-258) |
| Примеры: `grid_blueprint_loader.py` (обратный путь, load XML → projector) | `examples/organized/projector/grid_blueprint_loader.py` |
| Примеры: `align_clone_projection.py` / `..._small.py` (clone + alignment) | `examples/organized/projector/` |
