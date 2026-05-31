# Docking with free target connector selection

Запуск из корня проекта:

```powershell
cd C:\secontrol
```

Обычная команда остаётся совместимой:

```powershell
python examples/organized/parking/dock.py agent1 farpost0 80
```

Перед парковкой скрипт теперь выбирает только свободный целевой коннектор. Коннектор считается доступным, если он:

- включён;
- functional/working, если эти поля есть в телеметрии;
- имеет position и orientation.forward;
- не `Connected`;
- не имеет `otherConnectorId`;
- не находится в неоднозначном `Connectable` без подтверждения, что это коннектор текущего корабля.

Посмотреть коннекторы без парковки:

```powershell
python examples/organized/parking/dock.py agent1 farpost0 80 --list-connectors
```

Выбрать конкретный свободный целевой коннектор по ID:

```powershell
python examples/organized/parking/dock.py agent1 farpost0 80 --target-connector-id 111724613137081403
```

Выбрать целевой коннектор по части имени:

```powershell
python examples/organized/parking/dock.py agent1 farpost0 80 --target-connector-name Dock-A
```

Выбрать коннектор корабля:

```powershell
python examples/organized/parking/dock.py agent1 farpost0 80 --ship-connector-name Connector
```

Если выбранный целевой коннектор занял другой корабль во время манёвра, скрипт останавливает парковку защитой:

```text
ERROR: target connector is not available during Phase 3 step ...
```

В этом случае запусти команду заново: скрипт снова просканирует список и выберет другой свободный порт.
