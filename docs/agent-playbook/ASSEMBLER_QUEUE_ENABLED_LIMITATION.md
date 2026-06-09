# Assembler: `queueEnabled` (Use Production Queue) не переключается из Python

**Статус:** открытое ограничение текущей обвязки
**Затрагивает:** все ассемблеры, грид `skynet-farpost0` и любые другие
**Команда для воспроизведения:** `python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost view --full`
**Дата фиксации:** 2026-06-09

## Симптом

Ассемблер выглядит рабочим:

- `enabled` в телеметрии не сообщается (норма для Assembler в SE);
- `useConveyorSystem = true`;
- `isQueueEmpty = false` (если очередь есть);
- очередь видна в `view` и `view --full`, например 19 заданий на ~3700 компонентов;
- на базе есть все материалы (Cobalt, Iron, Nickel, Platinum, Silicon, Mg, Gold);
- Input/Output ассемблера не забиты, jam-скрипт пишет `No cleanup actions required`.

Но при этом:

- `isProducing = false`;
- `currentProgress = 0.000`;
- `queueEnabled = false` (см. полную телеметрию `view --full`).

Очередь не обрабатывается, ничего не производится.

## Корневая причина

В Space Engineers у блока Assembler в терминале на вкладке **Production** есть тоггл **"Use Production Queue"** (рус. "Использовать очередь производства"). Когда он выключен:

- сама очередь отображается и редактируется;
- блок не потребляет материалы;
- `isProducing` остаётся `false`, `currentProgress = 0`.

Именно это состояние мы видим в телеметрии: поле `queueEnabled = false`. У `Assembler 2` на `skynet-farpost0` это и было причиной простоя.

## Что уже проверено (read-after-write)

Все варианты отправки команды через Python-обёртку `secontrol.devices.assembler_device.AssemblerDevice` были протестированы с проверкой телеметрии через 1.0-1.5 сек:

| Команда | Метод / payload | Результат (`queueEnabled`) |
|---|---|---|
| `assembler.set_enabled(True)` | `{"cmd": "enable"}` | не изменился, остался `false` |
| `assembler.toggle_enabled()` | `{"cmd": "toggle"}` | не изменился |
| Сырая `{"cmd": "queue_enable"}` | direct | `false` |
| Сырая `{"cmd": "use_queue"}` | direct | `false` |
| Сырая `{"cmd": "production_queue"}` | direct | `false` |
| Сырая `{"cmd": "queue_toggle"}` | direct | `false` |
| Сырая `{"cmd": "queue_on"}` | direct | `false` |
| Сырая `{"cmd": "use_production_queue"}` | direct | `false` |

Все эти команды возвращали `result: 1` от Redis-транспорта — это **только подтверждение, что сообщение доставлено подписчику**, а не ACK от плагина SE (см. `AGENTS.md` §1 "Observe → command → verify"). Телеметрия не изменилась ни в одном случае.

## Что нужно для исправления

Требуется доработка **SE-плагина** (C# на стороне dedicated server) — добавить обработку команды, которая дёргает `MyAssembler.UseProductionQueue` (или эквивалент в текущей версии Space Engineers). После этого в Python-обёртке `src/secontrol/devices/assembler_device.py` можно добавить метод по аналогии с `set_use_conveyor` / `set_repeat` / `set_cooperative`:

```python
def set_queue_enabled(self, enabled: bool | None = None) -> int:
    """Toggle the 'Use Production Queue' switch in the assembler terminal."""
    result = self._send_bool_command("queue_enabled", enabled, "QueueEnabled", "queueEnabled")
    print(f"Assembler {self.name} ({self.device_id}): set_queue_enabled({enabled}) -> sent {result} messages")
    return result
```

Имя команды в payload (`queue_enabled` / `queue_toggle` / `use_production_queue`) зависит от того, как плагин решит маршалить. Пока имя не зафиксировано — никакая сырая команда из Python не сработает.

## Обходное решение (оператор)

Пока плагин не допилен, обходной путь один: **включить тоггл вручную в игре**.

1. Подойти к конструктору (или открыть его через дистанционный доступ).
2. Открыть терминал блока → вкладка **Production** (рус. **Производство**).
3. Нажать кнопку **Use Production Queue** (рус. **Использовать очередь производства**) — должен загореться индикатор.
4. Закрыть терминал. Очередь начнёт обрабатываться, `isProducing` в телеметрии сменится на `true`.

После этого `maintain_components.py` и другие скрипты в `examples/organized/assembler/` будут работать как ожидается.

## Как отличить эту проблему от других

Другие типовые причины, по которым ассемблер не производит, даже когда `queueEnabled = true`:

| Симптом | Где смотреть |
|---|---|
| `isFunctional = false` | блок повреждён или обесточен |
| Input забит чужим предметом | `assembler_unjam.py --grid <g> --all-assemblers --dry-run` |
| `disassembleEnabled = true` | идёт разбор, а не сборка; переключить `assembler_queue_control.py --grid <g> mode assemble` |
| Очередь пуста | `maintain_components.py --grid <g>` или `add` |
| Нет материалов в подключённых контейнерах | `containers_show.py --grid <g>` + рефайнери / добыча |
| Conveyor выключен | `assembler_queue_control.py --grid <g> conveyor on` |

`queueEnabled = false` — отдельный случай, который из телеметрии виден только в `view --full` (поле `queueEnabled` в JSON).

## Связанные файлы

- Python-обёртка: `src/secontrol/devices/assembler_device.py:178-233` (команды устройства)
- Документация устройства: `docs/DEVICE_REFERENCE.md:182-199` (методы AssemblerDevice)
- Фильтр по гриду: `examples/organized/assembler/basic/assembler_multi_common.py:101` (`find_assemblers`, `device_belongs_to_grid`)
- Subgrid-агрегация: `src/secontrol/grids.py:1407` (`_aggregate_devices_from_subgrids`)
- Playbook: `docs/agent-playbook/PLAYBOOK.md` (раздел "Производство и инвентарь")
- AGENTS.md §1: правило read-after-write
- AGENTS.md §2: безопасная диагностика до уточнения
