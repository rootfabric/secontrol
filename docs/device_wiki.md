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

### Батарея

**Телеметрия:** базовый класс не добавляет специализированных полей — доступны стандартные флаги `enabled` и др. через `BaseDevice`.

**Команды:**

* `battery_mode` — принимает `mode` (`"auto"`, `"recharge"`, `"discharge"`). При ошибке режим отклоняется валидатором клиента.【F:src/secontrol/devices/battery_device.py†L8-L19】

### Кокпит

**Телеметрия:**

* `enabled`, `isUnderControl`, `hasPilot` — флаги включения и захвата управления.【F:src/secontrol/devices/cockpit_device.py†L29-L37】
* `pilot` — словарь с `entityId`, `identityId`, именем и уровнями кислорода/энергии/водорода пилота, если он присутствует.【F:src/secontrol/devices/cockpit_device.py†L38-L48】
* `shipMass` — масса корабля (`total`, `base`, `physical`).【F:src/secontrol/devices/cockpit_device.py†L51-L60】
* `linearVelocity` и `angularVelocity` — вектор скорости с компонентами и длиной.【F:src/secontrol/devices/cockpit_device.py†L62-L66】
* `gravity` — вложенные векторы `natural`, `artificial`, `total` для гравитации.【F:src/secontrol/devices/cockpit_device.py†L68-L77】
* `inventories` — список инвентарей кокпита (каждый элемент — словарь из телеметрии).【F:src/secontrol/devices/cockpit_device.py†L79-L84】

**Команды:**

* `enable`/`disable`/`toggle` — стандартное управление питанием.【F:src/secontrol/devices/cockpit_device.py†L87-L92】
* `handbrake` с параметром `handBrake` (bool).【F:src/secontrol/devices/cockpit_device.py†L93-L95】
* `dampeners` с параметром `dampeners` (bool).【F:src/secontrol/devices/cockpit_device.py†L96-L98】
* `control_thrusters` (`controlThrusters`).【F:src/secontrol/devices/cockpit_device.py†L99-L101】
* `control_wheels` (`controlWheels`).【F:src/secontrol/devices/cockpit_device.py†L102-L103】
* `set_main` (`isMain`). Используется для назначения главного кокпита.【F:src/secontrol/devices/cockpit_device.py†L104-L106】

### Коннектор

**Телеметрия:** стандартные флаги `enabled`, `locked` в теле устройства.

**Команды:**

* `connector_state` — принимает `locked` и/или `enabled` в `state`. Обе опции необязательны и передаются как булевы значения.【F:src/secontrol/devices/connector_device.py†L13-L21】

### Контейнер

**Телеметрия:**

* `items` — список предметов с полями `type`, `subtype`, `amount`, при наличии `displayName`; данные нормализуются клиентом.【F:src/secontrol/devices/container_device.py†L19-L49】
* `capacity` — агрегированные показатели объёма и массы (`currentVolume`, `maxVolume`, `currentMass`, `fillRatio`).【F:src/secontrol/devices/container_device.py†L51-L64】

**Команды переноса:**

* `transfer_items` — `state` содержит JSON-строку с `fromId`, `toId`, `items`. Каждый элемент `items` может задавать `type`, `subtype`, `amount`. Команда используется во всех вспомогательных методах.【F:src/secontrol/devices/container_device.py†L66-L118】
* `move_items` — переносит список предметов в другой инвентарь (составляет нагрузку для `transfer_items`).【F:src/secontrol/devices/container_device.py†L120-L133】
* `move_subtype` — перенос одного сабтайпа с опциональным типом и количеством.【F:src/secontrol/devices/container_device.py†L134-L143】
* `move_all` — переносит все предметы, кроме перечисленных в `blacklist`. Использует телеметрию контейнера для построения списка.【F:src/secontrol/devices/container_device.py†L145-L167】
* `drain_to` — передаёт конкретные сабтайпы целиком.【F:src/secontrol/devices/container_device.py†L169-L193】

### Сортировщик конвейера

**Телеметрия:**

* Режим (`mode` и флаг `isWhitelist`), параметр `drainAll`, список фильтров `filters` (каждый содержит `type`, `subtype`, `allSubtypes`).【F:src/secontrol/devices/conveyor_sorter_device.py†L33-L57】

**Команды:**

* `enable`/`disable`/`toggle` — питание сортировщика.【F:src/secontrol/devices/conveyor_sorter_device.py†L60-L64】
* `set_whitelist`, `set_blacklist` — переключение режима фильтрации (первый вариант принимает булев `whitelist`).【F:src/secontrol/devices/conveyor_sorter_device.py†L65-L69】
* `set_drain_all` — управляет вытягиванием всех предметов (булев `drainAll`).【F:src/secontrol/devices/conveyor_sorter_device.py†L70-L72】
* `clear_filters`, `add_filters`, `remove_filters`, `set_filters` — управление фильтрами; значения нормализуются функцией `_normalize_filter` и упаковываются в `state.filters`. Параметр `whitelist` в `set_filters` задаёт режим сразу.【F:src/secontrol/devices/conveyor_sorter_device.py†L73-L96】【F:src/secontrol/devices/conveyor_sorter_device.py†L1-L31】

### Генератор газа

**Телеметрия:** коэффициент заполнения `filledRatio`, производительность (`productionCapacity`, `currentOutput`, `maxOutput`), флаги `useConveyorSystem`, `autoRefill`, а также сводная структура `functional_status` с флагами `enabled`, `isFunctional`, `isWorking`.【F:src/secontrol/devices/gas_generator_device.py†L12-L30】

**Команды:**

* `enable`/`disable`/`toggle` — питание.【F:src/secontrol/devices/gas_generator_device.py†L33-L36】
* `use_conveyor` (`useConveyor`).【F:src/secontrol/devices/gas_generator_device.py†L37-L38】
* `auto_refill` (`autoRefill`).【F:src/secontrol/devices/gas_generator_device.py†L39-L40】
* `refill_bottles` — немедленно пополняет баллоны в инвентаре.【F:src/secontrol/devices/gas_generator_device.py†L41-L42】

### Гироскоп

**Телеметрия:** базовые поля через `BaseDevice`.

**Команды:**

* `override` — строка CSV c тремя значениями (pitch, yaw, roll) в диапазоне `[-1;1]`, опционально дополняется `power`. Клиент сам нормализует значения и формирует строку. 【F:src/secontrol/devices/gyro_device.py†L12-L28】
* `enable`, `disable`, `clear_override` — переключают режимы гироскопа.【F:src/secontrol/devices/gyro_device.py†L30-L36】

### Лампа

**Телеметрия:** флаги `enabled`, `intensity`, `radius`, текущий цвет `color` (RGB в формате 0–1). Клиент предоставляет геттеры с преобразованием типов.【F:src/secontrol/devices/lamp_device.py†L69-L115】

**Команды:**

* `enable`/`disable` и удобный `set_enabled`.【F:src/secontrol/devices/lamp_device.py†L43-L58】
* `color` — принимает массив из трёх компонентов (0–1). Клиент умеет парсить строки, словари и последовательности, конвертируя их к нормализованному RGB.【F:src/secontrol/devices/lamp_device.py†L5-L41】【F:src/secontrol/devices/lamp_device.py†L59-L67】

### Большая турель

**Телеметрия:**

* Флаги `enabled`, `aiEnabled`, `idleRotation`, дальность `range`, текущая цель `target` (словарь или `None`).【F:src/secontrol/devices/large_turret_device.py†L12-L28】

**Команды:**

* `enable`/`disable`/`toggle` — питание.【F:src/secontrol/devices/large_turret_device.py†L30-L33】
* `idle_rotation` (`idleRotation`).【F:src/secontrol/devices/large_turret_device.py†L34-L35】
* `set_range` (`range`).【F:src/secontrol/devices/large_turret_device.py†L36-L37】
* `shoot_once`, `shoot_on`, `shoot_off`, `reset_target` — управление стрельбой и сбросом цели.【F:src/secontrol/devices/large_turret_device.py†L38-L43】

### Проектор

**Телеметрия:**

* Количество оставшихся блоков (`remainingBlocks`), число собираемых блоков (`buildableBlocks`), название проецируемого грида (`projectedGridName`).【F:src/secontrol/devices/projector_device.py†L64-L84】
* При экспорте блюпринта данные сохраняются в Redis-ключ, который вычисляется методом `blueprint_key`; клиент умеет читать снапшот и XML из этого ключа.【F:src/secontrol/devices/projector_device.py†L114-L155】

**Команды:**

* `set_state` — переключение питания (`enabled`).【F:src/secontrol/devices/projector_device.py†L18-L23】
* `projector_state` — флаги: `keepProjection`, `showOnlyBuildable`, `instantBuild`, `alignGrids`, `projectionLocked`, `useAdaptiveOffsets`, `useAdaptiveRotation`. Требует хотя бы один параметр.【F:src/secontrol/devices/projector_device.py†L24-L46】
* `set_scale`, `set_offset`, `nudge_offset`, `set_rotation`, `nudge_rotation` — управление масштабом, смещением и вращением проекции.【F:src/secontrol/devices/projector_device.py†L47-L63】
* `reset_projection`, `lock_projection`, `unlock_projection` — служебные действия с текущей проекцией.【F:src/secontrol/devices/projector_device.py†L59-L63】
* `load_prefab` — загрузка префаба по идентификатору; опционально сохраняет текущую проекцию (`keep`).【F:src/secontrol/devices/projector_device.py†L86-L101】
* `load_blueprint_xml` — загрузка блюпринта из XML (`ShipBlueprintDefinition`).【F:src/secontrol/devices/projector_device.py†L102-L113】
* `export_grid_blueprint` — сериализация текущего грида в Redis (`includeConnected` управляет захватом присоединённых гридов).【F:src/secontrol/devices/projector_device.py†L118-L127】

### Реактор

**Телеметрия:** текущая и максимальная мощность (`currentOutput`, `maxOutput`), отношение загрузки (`outputRatio`), флаг использования конвейера и статус работы (`enabled`, `isFunctional`, `isWorking`).【F:src/secontrol/devices/reactor_device.py†L12-L28】

**Команды:**

* `enable`/`disable`/`toggle` — питание.【F:src/secontrol/devices/reactor_device.py†L31-L34】
* `use_conveyor` (`useConveyor`).【F:src/secontrol/devices/reactor_device.py†L35-L36】

### Перерабатывающий завод

**Телеметрия:**

* `useConveyorSystem`, `isProducing`, `isQueueEmpty`, `currentProgress` — основные флаги и прогресс.【F:src/secontrol/devices/refinery_device.py†L26-L39】
* `inputInventory` и `outputInventory` — вложенные структуры с объёмом, массой и списком предметов; клиент нормализует их через `_parse_inventory`.【F:src/secontrol/devices/refinery_device.py†L8-L23】【F:src/secontrol/devices/refinery_device.py†L40-L48】
* `queue` — текущее содержимое производственной очереди (список словарей).【F:src/secontrol/devices/refinery_device.py†L49-L52】

**Команды:**

* `enable`/`disable`/`toggle` — питание.【F:src/secontrol/devices/refinery_device.py†L55-L58】
* `use_conveyor` — принимает `useConveyor`. Параметр опционален, команда отправляется даже без него для синхронизации состояний.【F:src/secontrol/devices/refinery_device.py†L59-L63】
* `queue_clear` — очистка очереди.【F:src/secontrol/devices/refinery_device.py†L64-L65】
* `queue_remove` — удаление элемента по индексу с опциональным `amount`.【F:src/secontrol/devices/refinery_device.py†L66-L70】
* `queue_add` — добавление блюпринта (поддерживаются строки, словари, кортежи; нормализует `_normalize_queue_item`). Есть метод `add_queue_items` для массового добавления.【F:src/secontrol/devices/refinery_device.py†L24-L25】【F:src/secontrol/devices/refinery_device.py†L71-L80】

### Пульт дистанционного управления

**Телеметрия:** стандартные поля состояния (включение, координаты, режим пилота) через `BaseDevice`.

**Команды:**

* `remote_control` — включает автопилот для блока (отправляет `targetId`, `targetName`).【F:src/secontrol/devices/remote_control_device.py†L12-L18】
* `remote_goto` — строит GPS-строку и отправляет цель. Поддерживает строки формата `GPS:...` или три координаты, а также опцию `speed=` через `state`.【F:src/secontrol/devices/remote_control_device.py†L19-L44】

### Корабельный бур

**Телеметрия:** `harvestRatio`, `cutOutDepth`, `drillRadius`, `drillPowerConsumption`, `collectStone`. Клиент возвращает числовые значения и булев флаг сбора камня.【F:src/secontrol/devices/ship_drill_device.py†L9-L21】

**Команды:**

* `collect_stone` (`collectStone`).【F:src/secontrol/devices/ship_drill_device.py†L22-L23】
* `cut_depth` (`cutDepth`).【F:src/secontrol/devices/ship_drill_device.py†L24-L25】
* `drill_radius` (`drillRadius`).【F:src/secontrol/devices/ship_drill_device.py†L26-L27】

### Корабельный гриндер

**Телеметрия:** множители `grindingMultiplier`, `grindSpeedMultiplier`, флаг `helpOthers`. 【F:src/secontrol/devices/ship_grinder_device.py†L9-L17】

**Команды:**

* `help_others` (`helpOthers`).【F:src/secontrol/devices/ship_grinder_device.py†L18-L19】

### Корабельный сварщик

**Телеметрия:** множители `weldingMultiplier`, `weldSpeedMultiplier`, флаги `helpOthers`, `showArea`. 【F:src/secontrol/devices/ship_welder_device.py†L9-L20】

**Команды:**

* `help_others` (`helpOthers`).【F:src/secontrol/devices/ship_welder_device.py†L21-L22】
* `show_area` (`showArea`).【F:src/secontrol/devices/ship_welder_device.py†L23-L24】

### Двигатель (трастер)

**Телеметрия:** базовые флаги через `BaseDevice`.

**Команды:**

* `thruster_control` — поддерживает поля `override` (число тяги) и `enabled` (bool); оба параметра опциональны.【F:src/secontrol/devices/thruster_device.py†L11-L23】

### Базовый корабельный инструмент

Эту роль выполняет `ShipToolDevice`, от которого наследуются бур, гриндер и сварщик.

**Телеметрия:** `useConveyorSystem`, `requiredPowerInput`, `powerConsumptionMultiplier`, а также общий статус `enabled`/`isFunctional`/`isWorking`.【F:src/secontrol/devices/ship_tool_device.py†L9-L23】

**Команды:**

* `enable`/`disable`/`toggle` — стандартные операции.【F:src/secontrol/devices/ship_tool_device.py†L24-L28】
* `use_conveyor` (`useConveyor`).【F:src/secontrol/devices/ship_tool_device.py†L29-L30】
* За счёт вспомогательных `_send_boolean_command` и `_send_float_command` наследники реализуют собственные дополнительные опции (см. разделы выше).【F:src/secontrol/devices/ship_tool_device.py†L31-L34】

