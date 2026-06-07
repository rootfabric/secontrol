# Flight failure anti-pattern prompt

Вставляй этот блок в system/developer prompt агента, который управляет гридами Space Engineers через `secontrol`.

```text
Do not declare a Space Engineers grid unable to fly based only on static block telemetry.

Remote Control enabled=false, isFunctional=false, isWorking=false, autopilotEnabled=false, player online=false, 0 players online, Redis publish result=1 subscriber, generic block_enable failure, or suspicious thruster subtype are warning signals only. They are not hard blockers.

Redis publish subscriber count is not game execution ACK.

Before reporting fleet paralysis or refusing to run a flight script, run a guarded movement check unless it is unsafe:
1. Resolve grid and Remote Control.
2. Check docking status first.
3. If connected, use the canonical undock playbook before any thrust.
4. Prefer RC-specific commands: handbrake_off, thrusters_on, gyro_control_on, enable, goto.
5. Observe position and speed for 5-15 seconds.
6. If position changed by more than 2 m or speed exceeded 0.5 m/s, the grid can move.
7. Only report a real flight blocker after command attempts plus observed no movement, or when the movement test is unsafe or impossible.

Do not use old memory, online status, generic block_enable, or thruster subtype as a substitute for measured movement.
```
