# Управление конструкторами Space Engineers

Инструкция рассчитана на запуск из корня проекта:

```powershell
cd C:\secontrol
```

Все команды ниже выполняются из `C:\secontrol`. В примерах используется грид `farpost0`. Для другого грида поменяй значение после `--grid`.

## Что умеют скрипты

Основной скрипт для ручного управления очередью:

```text
examples/organized/assembler/intermediate/assembler_queue_control.py
```

Он умеет:

- смотреть состояние конструктора и очередь;
- добавлять задания на сборку;
- добавлять задания на разбор;
- удалять задание из очереди полностью или частично;
- очищать очередь;
- переключать режим сборка/разбор;
- включать/выключать конвейер.

Скрипт для автоматического поддержания запаса компонентов:

```text
examples/organized/assembler/basic/maintain_components.py
```

Он читает целевые количества из:

```text
examples/organized/assembler/basic/production_targets.json
```

и добавляет недостающие компоненты в очередь конструктора.

## Важное отличие от старого поведения

Сообщение вида:

```text
command sent, result: 1
```

не означает, что конструктор реально добавил задачу. Это только подтверждение, что Redis доставил сообщение одному подписчику.

Новые скрипты после команды ждут изменение телеметрии конструктора. Если очередь не изменилась, команда считается неподтверждённой.

## Быстрая проверка

Сначала проверь, что грид доступен и конструктор виден:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
```

Ожидаемый смысл вывода:

```text
Грид: skynet-farpost0
Выбран конструктор: Assembler (...)
enabled=True conveyor=True disassemble=False ...
```

Если конструкторов несколько, можно выбрать конкретный по части имени:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 --name Assembler view
```

Или по ID блока:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 --assembler-id 104442163700550022 view
```

## Посмотреть доступные чертежи

Короткий список производимых предметов по категориям:

```powershell
python examples/organized/assembler/basic/grid_production.py --grid farpost0
```

Полный список с материалами для каждого чертежа:

```powershell
python examples/organized/assembler/basic/grid_production.py --grid farpost0 --full
```

Сырой список blueprint-ов из телеметрии конструктора:

```powershell
python examples/organized/assembler/intermediate/assembler_blueprints_viewer.py --grid farpost0 --limit 50
```

Если нужного предмета нет в списке, конструктор не сможет поставить его в очередь через этот blueprint.

## Посмотреть очередь

Рекомендуемый способ:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
```

С полной телеметрией:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view --full
```

Старый просмотрщик тоже оставлен:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_viewer.py --grid farpost0
```

## Добавить задание на сборку

Добавить 100 стальных пластин:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 add SteelPlate 100
```

Добавить 50 внутренних пластин:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 add InteriorPlate 50
```

Добавить 20 моторов:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 add MotorComponent 20
```

Перед добавлением обычной сборки скрипт сам переводит конструктор в режим:

```text
DisassembleEnabled=False
```

Это защищает от ситуации, когда предыдущая команда включила режим разбора, и новая задача случайно ушла бы на разбор.

## Добавить задание на разбор

Разобрать 10 стальных пластин:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 disassemble SteelPlate 10
```

Разобрать 5 моторов:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 disassemble MotorComponent 5
```

Перед добавлением задачи на разбор скрипт сам включает режим:

```text
DisassembleEnabled=True
```

После этого режим разбора останется включённым в самом конструкторе. Если дальше нужно собирать предметы вручную или другим скриптом, переключи обратно:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode assemble
```

## Переключить режим сборка/разбор вручную

Включить обычную сборку:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode assemble
```

Включить разбор:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode disassemble
```

## Удалить задание из очереди

Сначала посмотри индексы очереди:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
```

Удалить всю позицию с индексом `0`:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 remove 0
```

Убрать только 5 штук из позиции с индексом `0`:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 remove 0 --amount 5
```

Важно: индекс берётся из текущей очереди конструктора. После удаления или добавления заданий индексы могут измениться, поэтому перед следующим удалением лучше снова выполнить `view`.

## Очистить всю очередь

Рекомендуемый способ:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 clear
```

Отдельный короткий скрипт для очистки:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_clear.py --grid farpost0
```

## Включить или выключить конвейер

Включить Use Conveyor System:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 conveyor on
```

Выключить Use Conveyor System:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 conveyor off
```

Переключить текущее состояние:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 conveyor toggle
```

Python отправляет команду плагину как:

```text
cmd=conveyor
```

Это важно: плагин ждёт именно `conveyor`, а не `use_conveyor`.

## Автоматически поддерживать запас компонентов

`maintain_components.py` теперь считает не только склад, но и уже поставленные задания в очереди конструктора.

Формула расчёта:

```text
надо добавить = цель - количество_на_складе - количество_в_очереди_сборки
```

Например, если цель `SteelPlate=100`, на складе уже `10`, а в очереди конструктора уже стоит `82`, скрипт добавит только `8`. Если запустить скрипт второй раз подряд, он не поставит дубль, потому что очередь уже закрывает дефицит.

Проверить расчёт без отправки команд:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --dry-run
```

Добавить только реально недостающие компоненты в очередь:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0
```

Ожидаемый вид расчёта:

```text
Стальная пластина: склад 10 + очередь 82 = 92/100 — добавить 8
Внутренняя пластина: склад 0 + очередь 50 = 50/50 — OK
```

Вернуть старое поведение и не учитывать очередь:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --ignore-queue
```

Если конструктор сейчас в режиме разбора, очередь по умолчанию не считается как производство. Это защита от ошибки, когда задания на разбор были бы приняты за задания на сборку. Если ты точно знаешь, что текущая очередь всё равно относится к сборке, можно принудительно учесть её:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --count-queue-in-disassemble-mode
```

Дольше ждать подтверждения после каждой команды:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --verify-timeout 5
```

Уменьшить паузу между командами:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --delay 0.1
```

Отключить проверку телеметрией не рекомендуется, но возможно:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --no-verify
```

## Настроить целевые запасы

Файл целей:

```text
examples/organized/assembler/basic/production_targets.json
```

Пример содержимого:

```json
{
  "SteelPlate": 100,
  "InteriorPlate": 50,
  "ConstructionComponent": 50,
  "SmallTube": 20,
  "LargeTube": 10,
  "MotorComponent": 20,
  "ComputerComponent": 20,
  "MetalGrid": 10,
  "Display": 5,
  "BulletproofGlass": 5
}
```

После изменения файла можно проверить расчёт без добавления задач:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --dry-run
```

Можно использовать другой файл целей:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --config examples/organized/assembler/basic/production_targets.json
```

## Частые blueprint subtype

Компоненты:

```text
SteelPlate
InteriorPlate
ConstructionComponent
SmallTube
LargeTube
MotorComponent
ComputerComponent
MetalGrid
Display
BulletproofGlass
PowerCell
RadioCommunicationComponent
DetectorComponent
MedicalComponent
ReactorComponent
ThrustComponent
GravityGeneratorComponent
SolarCell
Superconductor
GirderComponent
ExplosivesComponent
Canvas
```

Инструменты:

```text
AngleGrinder
AngleGrinder2
AngleGrinder3
AngleGrinder4
HandDrill
HandDrill2
HandDrill3
HandDrill4
Welder
Welder2
Welder3
Welder4
```

Перед использованием редких предметов лучше проверить точный blueprint:

```powershell
python examples/organized/assembler/intermediate/assembler_blueprints_viewer.py --grid farpost0 --limit 5000
```

## Как понять, что команда реально сработала

Успешное добавление выглядит по смыслу так:

```text
Добавляю на сборку: SteelPlate -> MyObjectBuilder_BlueprintDefinition/SteelPlate x100
...
Очередь:
  [0] SteelPlate x100
```

Для `maintain_components.py` успешная команда выглядит так:

```text
[>] SteelPlate -> MyObjectBuilder_BlueprintDefinition/SteelPlate x100
    подтверждено телеметрией очереди
```

Если написано:

```text
НЕ подтверждено: команда ушла, но очередь в телеметрии не изменилась
```

значит Python отправил команду, но плагин или игра не изменили очередь. Тогда нужно смотреть лог dedicated server/plugin.

## Диагностика проблем

### Конструктор не найден

Проверь, что на гриде есть рабочий Assembler и что телеметрия плагина видит этот блок:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view --full
```

Если грид найден, но конструктора нет, проблема не в очереди, а в обнаружении устройств на стороне телеметрии.

### Команда отправляется, но очередь не меняется

Проверь логи плагина на сервере. Особенно строки вида:

```text
CommandProcessor: command 'queue_add' for device ... was not handled
```

или ошибки blueprint. Для проверки blueprint используй:

```powershell
python examples/organized/assembler/intermediate/assembler_blueprints_viewer.py --grid farpost0 --limit 5000
```

### Задание ушло на разбор вместо сборки

Верни режим сборки:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode assemble
```

После этого добавляй обычные задания через `add` или запускай `maintain_components.py`.

### Конструктор не берёт материалы

Проверь конвейер:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
```

Если `conveyor=False`, включи:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 conveyor on
```

Также проверь в игре, что конструктор подключён к контейнерам и есть нужные ingot/materials.

### Очередь меняется нестабильно

Увеличь timeout:

```powershell
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 --timeout 8 add SteelPlate 100
```

Для автоматического поддержания запасов:

```powershell
python examples/organized/assembler/basic/maintain_components.py --grid farpost0 --verify-timeout 8 --delay 0.3
```

Не ставь слишком маленькую задержку между командами: в плагине есть лимит обработки команд на устройство.

## Какие скрипты использовать

Рекомендуемые:

```text
examples/organized/assembler/intermediate/assembler_queue_control.py
examples/organized/assembler/basic/maintain_components.py
examples/organized/assembler/basic/grid_production.py
examples/organized/assembler/intermediate/assembler_blueprints_viewer.py
```

Допустимые, но дублируют часть возможностей:

```text
examples/organized/assembler/intermediate/assembler_queue_viewer.py
examples/organized/assembler/intermediate/assembler_queue_clear.py
```

Legacy/старый пример:

```text
examples/organized/assembler/advanced/assembler_produce.py
```

Для проверки нормальной работы ассемблера его лучше не использовать: он отправляет старый прямой payload и не проверяет изменение очереди телеметрией.

## Минимальный рабочий сценарий после правок

```powershell
cd C:\secontrol
python -m pip install -e C:\secontrol
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 conveyor on
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode assemble
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 add SteelPlate 10
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 remove 0 --amount 5
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 disassemble SteelPlate 5
python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 clear
```
