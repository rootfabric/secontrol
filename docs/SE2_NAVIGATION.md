# SE2 навигация: полёты через виртуальный автопилот

Практические сценарии использования `secontrol.se2_navigation.AutopilotDevice`.
Общая архитектура бэкенда: [SE2_BACKEND.md](SE2_BACKEND.md). Математика и
ограничения контура управления: `SpaceEngineers2-RedisBridge/docs/AUTOPILOT.md`.

## Базовый полёт

```python
from secontrol.se2 import Client

with Client(timeout=9) as bridge:
    ap, = [d for d in bridge.devices(device_type="autopilot") if d._state["gridName"] == "Blue Fighter"]
    state = ap.refresh()["properties"]
    print(state["position"], state["velocity"])

    r = ap.goto([250725.0, 8885.9, -12656.5], max_speed=5.0, position_tolerance=2.0, timeout=180.0)
    arrival = ap.wait(r.actual_state["properties"]["missionId"], timeout=200.0)
    print(arrival["properties"]["distance"])   # ошибка позиции на цели
```

`goto` подтверждает только принятие миссии; прибытие — отдельный статус `Arrived`
(удержание в допуске 0.5 с: позиция, угол, скорость ≤ 0.25 м/с).

## Нос по курсу: `align_course=True`

Грид постоянно доворачивает нос по вектору к цели. Взаимоисключим с `forward`
и не работает в ground-режиме. Проверено в игре: доворот от ~178°, в
установившемся полёте отклонение носа от курса 0.0–0.5°.

```python
ap.goto(target, mode="flight", max_speed=5.0, align_course=True)
```

## Игрок в кресле: `cancel_on_player=False` (по умолчанию)

По умолчанию вход игрока в кресло не отменяет миссию — контроллер продолжает
подавать ввод. Передайте `cancel_on_player=True`, чтобы вернуть старое
поведение (миссия отменяется, игрок получает управление).

## Точное возвращение в зафиксированную позу

Сценарий «запомнить точку, отлететь, вернуться точно»: перед стартом capture
позиции, `forward` и `up` из телеметрии; возврат — с жёсткими допусками и
конечной ориентацией равной зафиксированной. Измеренная в игре точность
возврата: позиция 0.12–0.14 м, нос 0.03°, крен 0.01°.

```python
s0 = ap.refresh()["properties"]
home, fwd, up = s0["position"], s0["forward"], s0["up"]

ap.goto([home[0] + 80, home[1], home[2]], max_speed=5.0,
        position_tolerance=2.0, align_course=True)          # отлёт

ap.goto(home, max_speed=3.0, position_tolerance=0.2,        # точный возврат
        heading_tolerance_deg=0.5, forward=fwd, up=up)
```

Советы по точности: снижайте `max_speed` возврата (1–3 м/с — меньше перелёт
на торможении); минимальные допуски плагина — `position_tolerance=0.2` м и
`heading_tolerance_deg=0.5°`. Живой пример: `tmp/se2_precise_return.py`
(временные файлы живут в `tmp/`, паттерн копируйте отсюда).

## Парковка на коннектор: `park()` / `unpark()`

Модуль `secontrol.se2_parking` выполняет полный цикл стыковки с коннектором
станции. Телеметрия коннектора содержит мировой стыковочный пивот
(`pivotPosition`/`pivotForward`/`pivotUp`), по которому вычисляется поза грида
для совмещения пивотов (конвенция движка: пивоты при стыковке антипараллельны,
up совпадает).

```python
from secontrol.se2 import Client
from secontrol.se2_parking import park, unpark

with Client(timeout=9) as bridge:
    # dock_id можно не указывать, если детектор уже видит коннектор станции
    report = park(bridge, "Blue Fighter", dock_id="8935:1")
    assert report["connected"]
    ...
    unpark(bridge, "Blue Fighter", backoff=40.0)   # disconnect + отлет назад
```

Цикл: waypoint в 15 м перед доком → точный подлёт к совмещению пивотов
(допуск 0.05 м — движковый лимит стыковки ~0.1 м, жёстче SE1-магнитов) →
`TryConnect` движка с подтверждением `Connected`. Проверено в игре:
Blue Fighter отстыковался, отлетел на 40 м, вернулся и состыковался с
Concordia Research Station (`connected: true`).

После стыковки можно переносить предметы между коннекторами (или карго):
`own_connector.transfer_item(base_connector, item_index, amount)` — движок сам
проверяет фильтры инвентаря. Проверено в игре: инструмент (WelderMk1) из
коннектора корабля перенесён в коннектор базы после автопарковки.

## Буры: `collect` / `extend` / `off`

`Client.drills(grid_name=...)` возвращает буры грида. Движок даёт буру два
действия с разными формами кисти: **primary = сбор породы**, **secondary =
расширение/разработка** (широкая форма).

```python
drill.start_collect()   # режим сбора породы (primary)
drill.start_extend()    # режим расширения (secondary, широкая кисть)
drill.stop()            # выключить бур
drill.mode              # "collect" | "extend" | "off"
drill.drilling_voxels   # фактически бурит воксели прямо сейчас
```

Проверено в игре на гриде Bullfrog SM-31 Miner (2 × Drill 3.5 m): все три
режима подтверждаются квитанциями и отражаются в телеметрии
(`isPrimaryActionEnabled` / `isSecondaryActionEnabled`).

## Правила безопасности

- Наблюдайте прибытие по `wait()`/телеметрии, а не только по ACK `goto`.
- Нет obstacle avoidance: маршрут — прямая. Перед полётом убедитесь, что
  коридор свободен (в тестовом мире вылет станции ловил корабли на ~95 м).
- `stop()` — немедленное прерывание с гашением скорости.
- После рестарта игры/сессии переоткрывайте устройства (epoch меняется).
