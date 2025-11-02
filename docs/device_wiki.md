# Wiki по устройствам плагина se-grid-controller

Эта страница описывает телеметрию и команды, которые предоставляет плагин `se-grid-controller` на выделенном сервере Space Engineers. Документация основана на классах устройств в клиентской библиотеке `secontrol`, которые повторяют протокол взаимодействия с плагином.

## Общие сведения

* Каждый блок на гриде представлен экземпляром `BaseDevice` с собственным `device_id`, типом (`device_type`) и ключом телеметрии. При создании устройство подписывается на обновления Redis и сразу подтягивает текущий срез данных.\
  Ключи и имя заполняются из метаданных, а также кэшируются при появлении телеметрии.【F:src/secontrol/base_device.py†L887-L943】
* Если ожидаемого ключа телеметрии нет, клиент сканирует Redis по шаблону `se:{owner}:grid:{grid}:*:{device}:telemetry`, чтобы подключиться к существующему ключу.【F:src/secontrol/base_device.py†L944-L963】
* Все команды публикуются в канал `se.{player}.commands.device.{deviceId}`. Перед отправкой клиент автоматически добавляет идентификаторы грида, устройства и пользователя, а также метаданные об инициаторе и временную метку.【F:src/secontrol/base_device.py†L1005-L1031】【F:src/secontrol/base_device.py†L1214-L1238】
* Базовые методы `enable`, `disable`, `toggle_enabled` доступны для большинства устройств и обновляют кэш флагов при успехе.【F:src/secontrol/base_device.py†L1005-L1031】
* Инвентарные устройства наследуются от `ContainerDevice`, которая нормализует содержимое `items` и реализует перенос предметов между инвентарями через команду `transfer_items` с JSON в поле `state`. Есть удобные обёртки `move_subtype`, `move_all` и `drain_to`.【F:src/secontrol/devices/container_device.py†L1-L114】【F:src/secontrol/devices/container_device.py†L116-L193】

## Список устройств

* [Батарея](#батарея)
* [Кокпит](#кокпит)
* [Коннектор](#коннектор)
* [Контейнер](#контейнер)
* [Сортировщик конвейера](#сортировщик-конвейера)
* [Генератор газа](#генератор-газа)
* [Гироскоп](#гироскоп)
* [Лампа](#лампа)
* [Большая турель](#большая-турель)
* [Проектор](#проектор)
* [Реактор](#реактор)
* [Перерабатывающий завод](#перерабатывающий-завод)
* [Пульт дистанционного управления](#пульт-дистанционного-управления)
* [Корабельный бур](#корабельный-бур)
* [Корабельный гриндер](#корабельный-гриндер)
* [Корабельный сварщик](#корабельный-сварщик)
* [Двигатель (трастер)](#двигатель-трастер)
* [Базовый корабельный инструмент](#базовый-корабельный-инструмент)
* [AI автопилоты](#ai-автопилоты)
* [AI задачи](#ai-задачи)
* [AI поведение](#ai-поведение)
* [AI рекордер](#ai-рекордер)

### Батарея

#### Телеметрия

* Использует только базовые поля `BaseDevice` (`enabled`, `isWorking`, `isFunctional` и т. п.). Дополнительных показателей батарея не добавляет.【F:src/secontrol/devices/battery_device.py†L8-L19】

#### Команды

| Команда        | Параметры                              | Описание |
| -------------- | --------------------------------------- | -------- |
| `battery_mode` | `mode` ∈ {`"auto"`, `"recharge"`, `"discharge"`} | Переключает режим работы батареи; проверка допустимого значения выполняется на клиенте до отправки сообщения в Redis.【F:src/secontrol/devices/battery_device.py†L8-L19】|

### Кокпит

#### Телеметрия

* `enabled`, `isUnderControl`, `hasPilot` — флаги включения и захвата управления.【F:src/secontrol/devices/cockpit_device.py†L29-L37】
* `pilot` — словарь с `entityId`, `identityId`, именем и уровнями кислорода/энергии/водорода пилота, если он присутствует.【F:src/secontrol/devices/cockpit_device.py†L38-L48】
* `shipMass` — масса корабля (`total`, `base`, `physical`).【F:src/secontrol/devices/cockpit_device.py†L51-L60】
* `linearVelocity` и `angularVelocity` — вектор скорости с компонентами и длиной.【F:src/secontrol/devices/cockpit_device.py†L62-L66】
* `gravity` — вложенные векторы `natural`, `artificial`, `total` для гравитации.【F:src/secontrol/devices/cockpit_device.py†L68-L77】
* `inventories` — список инвентарей кокпита (каждый элемент — словарь из телеметрии).【F:src/secontrol/devices/cockpit_device.py†L79-L84】

#### Команды

| Команда             | Параметры                | Описание |
| ------------------- | ------------------------- | -------- |
| `enable` / `disable` / `toggle` | — | Включает или выключает питание кокпита, синхронизирует локальный кэш флагов.【F:src/secontrol/devices/cockpit_device.py†L87-L92】|
| `handbrake`         | `handBrake`: bool         | Устанавливает состояние ручного тормоза.【F:src/secontrol/devices/cockpit_device.py†L93-L95】|
| `dampeners`         | `dampeners`: bool         | Управляет инерционными демпферами.【F:src/secontrol/devices/cockpit_device.py†L96-L98】|
| `control_thrusters` | `controlThrusters`: bool  | Разрешает или запрещает управление трастерами из кокпита.【F:src/secontrol/devices/cockpit_device.py†L99-L101】|
| `control_wheels`    | `controlWheels`: bool     | Разрешает или запрещает управление колесами.【F:src/secontrol/devices/cockpit_device.py†L102-L103】|
| `set_main`          | `isMain`: bool            | Назначает блок главным кокпитом грида.【F:src/secontrol/devices/cockpit_device.py†L104-L106】|

### Коннектор

#### Телеметрия

* Стандартные флаги `enabled` и `locked` присутствуют в телеметрии устройства через `BaseDevice` и метаданные Redis.【F:src/secontrol/devices/connector_device.py†L13-L21】

#### Команды

| Команда           | Параметры                         | Описание |
| ----------------- | ---------------------------------- | -------- |
| `connector_state` | `enabled`: bool?, `locked`: bool?  | Переключает питание и/или замок коннектора; оба параметра необязательны и передаются только при необходимости изменить состояние.【F:src/secontrol/devices/connector_device.py†L13-L21】|

### Контейнер

#### Телеметрия

* `inventories()` — возвращает список `InventorySnapshot` с нормализованными предметами и показателями объёма/массы для каждого контейнера блока.【F:src/secontrol/devices/container_device.py†L13-L205】
* `items(inventory=None)` — объединяет содержимое всех инвентарей (или выбранного) в список объектов `InventoryItem` с полями `type`, `subtype`, `amount`, `display_name`.【F:src/secontrol/devices/container_device.py†L23-L64】
* `capacity(inventory=None)` — возвращает текущий объём, массу и заполненность для выбранного инвентаря или суммарно по всем。【F:src/secontrol/devices/container_device.py†L26-L64】

#### Команды переноса

| Команда          | Параметры | Описание |
| ---------------- | ---------- | -------- |
| `transfer_items` | `state`: JSON-строка с `fromId`, `toId`, `items[]`, `fromInventoryIndex?`, `toInventoryIndex?` | Базовая команда Redis-плагина, используемая для любых операций перемещения инвентаря.【F:src/secontrol/devices/container_device.py†L66-L120】|
| `move_items`     | `items`: Iterable, `destination`, `source_inventory?`, `destination_inventory?` | Высокоуровневый метод клиента: нормализует предметы и автоматически подставляет индексы инвентарей по объектам или ключам телеметрии.【F:src/secontrol/devices/container_device.py†L122-L205】|
| `move_subtype`   | `subtype`, `amount?`, `type?`, `source_inventory?`, `destination_inventory?` | Перемещает один сабтайп с опциональным ограничением по количеству и типу предмета, поддерживает явный выбор инвентарей источника и получателя.【F:src/secontrol/devices/container_device.py†L206-L235】|
| `move_all`       | `destination`, `blacklist?`, `source_inventory?`, `destination_inventory?` | Переносит все предметы, кроме перечисленных в `blacklist`, автоматически читая выбранный инвентарь контейнера.【F:src/secontrol/devices/container_device.py†L236-L266】|
| `drain_to`       | `destination`, `subtypes`: Iterable, `source_inventory?`, `destination_inventory?` | Передает указанные сабтайпы полностью из выбранного инвентаря в целевой контейнер или конкретный инвентарь назначения.【F:src/secontrol/devices/container_device.py†L268-L290】|

### Сортировщик конвейера

#### Телеметрия

* `mode`, `isWhitelist`, `drainAll` — режим работы, состояние списка и глобальное вытягивание ресурсов.【F:src/secontrol/devices/conveyor_sorter_device.py†L33-L57】
* `filters[]` — список фильтров с полями `type`, `subtype`, `allSubtypes`, нормализованных клиентом.【F:src/secontrol/devices/conveyor_sorter_device.py†L1-L31】【F:src/secontrol/devices/conveyor_sorter_device.py†L33-L57】

#### Команды

| Команда        | Параметры | Описание |
| -------------- | ---------- | -------- |
| `enable` / `disable` / `toggle` | — | Управляет питанием сортировщика, поддерживая локальный кэш состояния.【F:src/secontrol/devices/conveyor_sorter_device.py†L60-L64】|
| `set_whitelist` / `set_blacklist` | `whitelist`: bool? | Переключают режим работы; `set_whitelist` принимает булев параметр, `set_blacklist` отправляет фиксированное значение.【F:src/secontrol/devices/conveyor_sorter_device.py†L65-L69】|
| `set_drain_all` | `drainAll`: bool | Активирует или отключает вытягивание всех предметов через сеть конвейеров.【F:src/secontrol/devices/conveyor_sorter_device.py†L70-L72】|
| `clear_filters` | — | Полностью очищает список фильтров блока.【F:src/secontrol/devices/conveyor_sorter_device.py†L73-L81】|
| `add_filters` / `remove_filters` | `filters[]` | Добавляют или удаляют фильтры; значения нормализуются вспомогательной функцией клиента.【F:src/secontrol/devices/conveyor_sorter_device.py†L73-L96】【F:src/secontrol/devices/conveyor_sorter_device.py†L1-L31】|
| `set_filters` | `filters[]`, `whitelist`? | Заменяет весь список фильтров и при необходимости переключает режим списка.【F:src/secontrol/devices/conveyor_sorter_device.py†L82-L96】【F:src/secontrol/devices/conveyor_sorter_device.py†L1-L31】|

### Генератор газа

#### Телеметрия

* `filledRatio` и производственные показатели `productionCapacity`, `currentOutput`, `maxOutput`.【F:src/secontrol/devices/gas_generator_device.py†L12-L30】
* Флаги `useConveyorSystem`, `autoRefill`, а также агрегированная структура `functional_status` (`enabled`, `isFunctional`, `isWorking`).【F:src/secontrol/devices/gas_generator_device.py†L12-L30】

#### Команды

| Команда        | Параметры | Описание |
| -------------- | ---------- | -------- |
| `enable` / `disable` / `toggle` | — | Управляет питанием генератора и отражает новое состояние в кэше устройства.【F:src/secontrol/devices/gas_generator_device.py†L33-L36】|
| `use_conveyor` | `useConveyor`: bool | Включает использование конвейерной сети для подачи льда.【F:src/secontrol/devices/gas_generator_device.py†L37-L38】|
| `auto_refill`  | `autoRefill`: bool | Автоматически пополняет баллоны, подключенные к блоку.【F:src/secontrol/devices/gas_generator_device.py†L39-L40】|
| `refill_bottles` | — | Мгновенно заправляет баллоны в инвентаре генератора.【F:src/secontrol/devices/gas_generator_device.py†L41-L42】|

### Гироскоп

#### Телеметрия

* Использует стандартные поля `BaseDevice` (`enabled`, `isFunctional`, `isWorking`). Специализированных показателей нет.【F:src/secontrol/devices/gyro_device.py†L12-L36】

#### Команды

| Команда         | Параметры | Описание |
| --------------- | ---------- | -------- |
| `override`      | `pitch`, `yaw`, `roll` ∈ [-1;1], `power`? | Клиент нормализует значения и формирует CSV-строку для установки ручного управления гироскопом.【F:src/secontrol/devices/gyro_device.py†L12-L28】|
| `enable` / `disable` | — | Включает или выключает блок; доступны обертки `enable` и `disable`.【F:src/secontrol/devices/gyro_device.py†L30-L36】|
| `clear_override` | — | Сбрасывает ручные установки и возвращает гироскоп в автоматический режим.【F:src/secontrol/devices/gyro_device.py†L30-L36】|

### Лампа

#### Телеметрия

* `enabled`, `intensity`, `radius` — стандартные поля состояния лампы.【F:src/secontrol/devices/lamp_device.py†L69-L115】
* `color` — текущий RGB в диапазоне 0–1 с удобными геттерами для преобразования к целочисленному цвету.【F:src/secontrol/devices/lamp_device.py†L69-L115】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `enable` / `disable` / `set_enabled` | `enabled`: bool | Управление питанием лампы; `set_enabled` принимает булево значение и вызывает соответствующую команду.【F:src/secontrol/devices/lamp_device.py†L43-L58】|
| `color`      | `color`: Sequence/str/dict | Принимает цвет в различных форматах, нормализует его к трем компонентам 0–1 перед отправкой в Redis.【F:src/secontrol/devices/lamp_device.py†L5-L41】【F:src/secontrol/devices/lamp_device.py†L59-L67】|

### Большая турель

#### Телеметрия

* `enabled`, `aiEnabled`, `idleRotation`, `range` и `target` (структура с текущей целью или `null`).【F:src/secontrol/devices/large_turret_device.py†L12-L28】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `enable` / `disable` / `toggle` | — | Управление питанием и синхронизация локального состояния турели.【F:src/secontrol/devices/large_turret_device.py†L30-L33】|
| `idle_rotation` | `idleRotation`: bool | Включает пассивное вращение турели при отсутствии целей.【F:src/secontrol/devices/large_turret_device.py†L34-L35】|
| `set_range`     | `range`: float      | Устанавливает дистанцию обнаружения и стрельбы.【F:src/secontrol/devices/large_turret_device.py†L36-L37】|
| `shoot_once`    | — | Производит одиночный выстрел.【F:src/secontrol/devices/large_turret_device.py†L38-L43】|
| `shoot_on` / `shoot_off` | — | Постоянно включает или выключает стрельбу турели.【F:src/secontrol/devices/large_turret_device.py†L38-L43】|
| `reset_target` | — | Сбрасывает текущую цель, позволяя турели выбрать новую.【F:src/secontrol/devices/large_turret_device.py†L38-L43】|

### Проектор

#### Телеметрия

* `remainingBlocks`, `buildableBlocks`, `projectedGridName` — ключевые показатели текущей проекции.【F:src/secontrol/devices/projector_device.py†L64-L84】
* Методы `blueprint_key`, `load_blueprint_snapshot` и `load_blueprint_xml` позволяют считывать сохранённые префабы из Redis-ключа, который формируется самим устройством.【F:src/secontrol/devices/projector_device.py†L114-L155】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `set_state`  | `enabled`: bool | Включает или выключает питание проектора.【F:src/secontrol/devices/projector_device.py†L18-L23】|
| `projector_state` | Любая комбинация флагов `keepProjection`, `showOnlyBuildable`, `instantBuild`, `alignGrids`, `projectionLocked`, `useAdaptiveOffsets`, `useAdaptiveRotation` | Обновляет внутреннее состояние проекции; требуется хотя бы один параметр.【F:src/secontrol/devices/projector_device.py†L24-L46】|
| `set_scale` / `set_offset` / `set_rotation` | `scale`: float, `offset`: Vector3, `rotation`: Vector3 | Полностью задают масштаб, смещение и ориентацию проекции.【F:src/secontrol/devices/projector_device.py†L47-L63】|
| `nudge_offset` / `nudge_rotation` | Инкрементальные смещения/повороты | Добавляют указанные дельты к текущему положению или вращению.【F:src/secontrol/devices/projector_device.py†L47-L63】|
| `reset_projection` / `lock_projection` / `unlock_projection` | — | Управляют сохранением и фиксацией текущей проекции.【F:src/secontrol/devices/projector_device.py†L59-L63】|
| `load_prefab` | `prefabId`, `keep`? | Загружает заранее сохранённый префаб; опция `keep` сохраняет текущую проекцию в списке последних.【F:src/secontrol/devices/projector_device.py†L86-L101】|
| `load_blueprint_xml` | `xml`: str | Поднимает проекцию из XML `ShipBlueprintDefinition`.【F:src/secontrol/devices/projector_device.py†L102-L113】|
| `export_grid_blueprint` | `includeConnected`: bool? | Экспортирует текущий грид в Redis и возвращает ключ со снапшотом/блюпринтом.【F:src/secontrol/devices/projector_device.py†L118-L127】|

### Реактор

#### Телеметрия

* `currentOutput`, `maxOutput`, `outputRatio` — показатели мощности реактора.【F:src/secontrol/devices/reactor_device.py†L12-L28】
* Флаги `useConveyorSystem`, `enabled`, `isFunctional`, `isWorking` — состояние подачи топлива и функциональности блока.【F:src/secontrol/devices/reactor_device.py†L12-L28】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `enable` / `disable` / `toggle` | — | Управляет питанием реактора.【F:src/secontrol/devices/reactor_device.py†L31-L34】|
| `use_conveyor` | `useConveyor`: bool | Включает или отключает использование конвейерной сети для подачи топлива.【F:src/secontrol/devices/reactor_device.py†L35-L36】|

### Перерабатывающий завод

#### Телеметрия

* `useConveyorSystem`, `isProducing`, `isQueueEmpty`, `currentProgress` — состояние и прогресс переработки.【F:src/secontrol/devices/refinery_device.py†L26-L39】
* `inputInventory`, `outputInventory` — вложенные структуры объема, массы и предметов, нормализованные `_parse_inventory`.【F:src/secontrol/devices/refinery_device.py†L8-L23】【F:src/secontrol/devices/refinery_device.py†L40-L48】
* `queue` — список элементов очереди производства с типом, сабтайпом и количеством.【F:src/secontrol/devices/refinery_device.py†L49-L52】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `enable` / `disable` / `toggle` | — | Управляет питанием перерабатывающего завода.【F:src/secontrol/devices/refinery_device.py†L55-L58】|
| `use_conveyor` | `useConveyor`: bool? | Синхронизирует использование конвейерной сети, даже если параметр не передан (используется для актуализации состояния).【F:src/secontrol/devices/refinery_device.py†L59-L63】|
| `queue_clear` | — | Полностью очищает очередь производства.【F:src/secontrol/devices/refinery_device.py†L64-L65】|
| `queue_remove` | `index`: int, `amount`: int? | Удаляет элемент очереди по индексу, опционально уменьшая его количество.【F:src/secontrol/devices/refinery_device.py†L66-L70】|
| `queue_add` | `blueprint`: str/tuple/dict, `amount`: int? | Добавляет чертёж в очередь; клиент нормализует запись `_normalize_queue_item`. Доступен метод `add_queue_items` для массовых операций.【F:src/secontrol/devices/refinery_device.py†L24-L25】【F:src/secontrol/devices/refinery_device.py†L71-L80】|

### Пульт дистанционного управления

#### Телеметрия

* Наследует базовые поля (`enabled`, `isWorking`, координаты) из `BaseDevice`; отдельная телеметрия реализована на стороне плагина и приходит в виде стандартных флагов.【F:src/secontrol/devices/remote_control_device.py†L12-L44】

#### Команды

| Команда          | Параметры | Описание |
| ---------------- | ---------- | -------- |
| `remote_control` | `targetId`: int?, `targetName`: str? | Включает автопилот и назначает цель по идентификатору или имени.【F:src/secontrol/devices/remote_control_device.py†L12-L18】|
| `remote_goto`    | `gps`: str / координаты, `speed`: float? | Строит GPS-строку (`GPS:...`) или принимает координаты и отправляет блок на указанную позицию; параметр `speed` задаётся в `state`.【F:src/secontrol/devices/remote_control_device.py†L19-L44】|

### Корабельный бур

#### Телеметрия

* `harvestRatio`, `cutOutDepth`, `drillRadius`, `drillPowerConsumption`, `collectStone` — показатели добычи и настройки радиуса бурения.【F:src/secontrol/devices/ship_drill_device.py†L9-L21】

#### Команды

| Команда        | Параметры | Описание |
| -------------- | ---------- | -------- |
| `collect_stone` | `collectStone`: bool | Управляет сбором камня буром.【F:src/secontrol/devices/ship_drill_device.py†L22-L23】|
| `cut_depth`     | `cutDepth`: float   | Задает глубину реза инструмента.【F:src/secontrol/devices/ship_drill_device.py†L24-L25】|
| `drill_radius`  | `drillRadius`: float | Изменяет радиус бурения.【F:src/secontrol/devices/ship_drill_device.py†L26-L27】|

### Корабельный гриндер

#### Телеметрия

* `grindingMultiplier`, `grindSpeedMultiplier`, `helpOthers` — параметры скорости разборки и помощи союзникам.【F:src/secontrol/devices/ship_grinder_device.py†L9-L17】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `help_others` | `helpOthers`: bool | Разрешает помогать союзным персонажам при разборке блоков.【F:src/secontrol/devices/ship_grinder_device.py†L18-L19】|

### Корабельный сварщик

#### Телеметрия

* `weldingMultiplier`, `weldSpeedMultiplier`, `helpOthers`, `showArea` — настройки скорости сварки и визуализации зоны действия.【F:src/secontrol/devices/ship_welder_device.py†L9-L20】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `help_others` | `helpOthers`: bool | Разрешает обслуживать союзников при сварке.【F:src/secontrol/devices/ship_welder_device.py†L21-L22】|
| `show_area`   | `showArea`: bool   | Отображает область действия инструмента.【F:src/secontrol/devices/ship_welder_device.py†L23-L24】|

### Двигатель (трастер)

#### Телеметрия

* Использует базовые поля `BaseDevice` (`enabled`, `isFunctional`, `isWorking`). Специфических показателей нет.【F:src/secontrol/devices/thruster_device.py†L11-L23】

#### Команды

| Команда            | Параметры | Описание |
| ------------------ | ---------- | -------- |
| `thruster_control` | `override`: float?, `enabled`: bool? | Устанавливает тягу и/или включает блок. Метод клиента `set_thrust` заполняет только переданные поля.【F:src/secontrol/devices/thruster_device.py†L11-L23】|

### Базовый корабельный инструмент

`ShipToolDevice` — базовый класс для бора, гриндера и сварщика, предоставляющий общую логику.

#### Телеметрия

* `useConveyorSystem`, `requiredPowerInput`, `powerConsumptionMultiplier` и агрегированный статус `enabled`/`isFunctional`/`isWorking`.【F:src/secontrol/devices/ship_tool_device.py†L9-L23】

#### Команды

| Команда      | Параметры | Описание |
| ------------ | ---------- | -------- |
| `enable` / `disable` / `toggle` | — | Управляют питанием любого корабельного инструмента.【F:src/secontrol/devices/ship_tool_device.py†L24-L28】|
| `use_conveyor` | `useConveyor`: bool | Включает использование конвейеров для подачи ресурсов.【F:src/secontrol/devices/ship_tool_device.py†L29-L30】|
| `_send_boolean_command`, `_send_float_command` | Внутренние параметры наследников | Вспомогательные методы, которые используют устройства-наследники для отправки специализированных команд (см. конкретные разделы).【F:src/secontrol/devices/ship_tool_device.py†L31-L34】|

### AI автопилоты

`AiMoveGroundDevice` и `AiFlightAutopilotDevice` реализуют команды миссий и автопилота новых AI-блоков Space Engineers. Общие методы предоставляются базовым классом `AiMissionBlockDevice`.

#### Команды

| Команда | Параметры | Описание |
| ------- | ---------- | -------- |
| `mission_select` | `missionId`: int | Выбирает миссию для выполнения блоком.【F:src/secontrol/devices/ai_device.py†L73-L82】|
| `mission_enable` / `mission_disable` / `mission_reset` | — | Запускает, останавливает или сбрасывает выбранную миссию.【F:src/secontrol/devices/ai_device.py†L84-L92】|
| `autopilot_enable` / `autopilot_disable` / `autopilot_pause` / `autopilot_resume` | — | Управляют состоянием встроенного автопилота.【F:src/secontrol/devices/ai_device.py†L94-L102】|
| `clear_waypoints` | — | Очищает очередь точек маршрута.【F:src/secontrol/devices/ai_device.py†L104-L105】|
| `add_waypoint` | `position`: vector, `speed`: float?, `name`: str? | Добавляет новую точку маршрута и опционально ограничивает скорость движения.【F:src/secontrol/devices/ai_device.py†L107-L118】|
| `set_speed_limit` | `value`: float | Устанавливает глобальное ограничение скорости для блока.【F:src/secontrol/devices/ai_device.py†L120-L121】|
| `set_collision_avoidance` / `set_terrain_follow` | `value`: bool | Включает обход препятствий и следование рельефу соответственно.【F:src/secontrol/devices/ai_device.py†L123-L126】|
| `set_mode` | `mode`: str | Переключает режим выполнения миссии/автопилота (например, Patrol/OneWay).【F:src/secontrol/devices/ai_device.py†L128-L131】|

### AI задачи

`AiOffensiveDevice` и `AiDefensiveDevice` наследуют `AiTaskDevice` и предназначены для установки целей и режимов поведения боевых AI-блоков.

#### Команды

| Команда | Параметры | Описание |
| ------- | ---------- | -------- |
| `set_target` | `entityId`: int?, `position`: vector?, `value`: str? | Назначает цель по идентификатору сущности либо по координатам. Можно передать готовую GPS-строку в `value`.【F:src/secontrol/devices/ai_device.py†L139-L154】|
| `clear_target` | — | Сбрасывает текущую цель блока.【F:src/secontrol/devices/ai_device.py†L156-L157】|
| `set_mode` | `mode`: str | Переключает режим поведения (например, Patrol, Assault).【F:src/secontrol/devices/ai_device.py†L159-L162】|

### AI поведение

`AiBehaviorDevice` управляет профилями поведения, которые подключаются к AI задачам или автопилотам.

#### Команды

| Команда | Параметры | Описание |
| ------- | ---------- | -------- |
| `set_behavior` | `behavior`: str | Устанавливает активный профиль поведения блока.【F:src/secontrol/devices/ai_device.py†L168-L173】|
| `behavior_start` / `behavior_stop` | — | Включает или отключает выполнение выбранного профиля.【F:src/secontrol/devices/ai_device.py†L175-L179】|

### AI рекордер

`AiRecorderDevice` позволяет записывать и проигрывать траектории движения для AI блоков.

#### Команды

| Команда | Параметры | Описание |
| ------- | ---------- | -------- |
| `recorder_start` / `recorder_stop` | — | Начинает или завершает запись пути блока.【F:src/secontrol/devices/ai_device.py†L185-L191】|
| `recorder_play` | — | Запускает воспроизведение записанного маршрута.【F:src/secontrol/devices/ai_device.py†L193-L194】|
| `recorder_clear` | — | Очищает текущую запись траектории.【F:src/secontrol/devices/ai_device.py†L196-L197】|

