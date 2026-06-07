## Flight safety correction for ore collection missions

Перед шагами `Fly to ore GPS` и `Fly back to base` агент обязан помнить:

1. Не объявлять `fleet paralyzed` только по `RC enabled=false`, `isFunctional=false`, `online=false`, `0 players online` или `Redis publish result = 1 subscriber`.
2. `1 subscriber` не является ACK от игры. Это только наличие подписчика Redis.
3. Generic `block_enable` на Remote Control не доказывает, что RC-specific command path не работает.
4. Если корабль не пристыкован и есть безопасное пространство, перед отказом выполнить guarded flight check.
5. Для Remote Control использовать RC-specific path или canonical navigator.
6. Если короткий тест показал speed/position delta, продолжить миссию: грид способен лететь.
7. Если тест не запускался, в отчёте обязательно указать точную причину, почему он был небезопасен или невозможен.

Канонический источник правил:

```text
docs/agent-playbook/FLIGHT_DIAGNOSTIC_RULES.md
```
