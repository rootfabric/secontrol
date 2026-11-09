# Opt-in SE2 backend

`from secontrol.se2 import Client` selects the experimental local SE2 Redis Bridge.
Existing `secontrol.Grid`, SE1 devices, registration and command protocol are unchanged.

```python
from secontrol.se2 import Client

with Client() as bridge:
    lamps = bridge.lamps(grid_name="Concordia Research Station", name="Interior Light 0.5 m")
    result = lamps[0].set_enabled(True)
    assert result.status == "confirmed"
    print(result.actual_state, result.latency_ms)
```

Supported: `enable`, `disable`, `set_enabled`, `toggle`, `refresh`, cached `telemetry`.
Results are confirmed command receipts, not SE1's Redis subscriber counts.
`Client.devices()` constructs typed adapters; `lamps()` and `doors()` filter them.
`LampDevice` and `DoorDevice` share `FunctionalDevice` switch methods. Door adds
`open()`, `close()` and `toggle_door()`; `toggle()` still means power. Opening is
confirmed only at final Open, closing at Closed. Use a sufficient timeout for motion.
Capabilities: switch.enabled and door.open; no implicit color/intensity/radius support.
Protocol v2 exposes devices with individual measuredAtMs and typed properties;
the legacy lamps view remains available. refresh() rejects stale device telemetry.
`goto(..., align_course=True)` keeps the grid nose aligned with the direction to
the target during flight (mutually exclusive with `forward`, not in ground mode).
By default a player entering a seat does not cancel an active mission
(`keepControlOnPlayer`); pass `cancel_on_player=True` to yield control to the
player as before.

Development adapters added after 0.0.6: `LampDevice.set_brightness(0..10)`,
`ThrusterDevice.set_thrust_override(0..1)`, `GravityDevice.set_gravity(-9.81..9.81)`,
`LandingGearDevice.lock()/unlock()/set_auto_lock(bool)`,
`AntennaDevice.set_broadcast(bool)`, `ConverterDevice.set_processing(bool)`,
and `BatteryDevice`/`TankDevice.set_mode("auto"|"charge"|"discharge")`.
Telemetry includes inventories on powered blocks when present, seat occupancy,
production activity and weapon continuous fire state. These new operations have
API/build/contract checks; in-game actuation tests are intentionally scheduled
for purpose-built grids. Limits are conservative until compared with the game UI.
One shared Client uses pooled Redis connections and no per-device subscription threads.

Connection defaults to `redis://127.0.0.1:6379/0`, prefix `se2:local`. The corresponding
plugin currently targets this fixed local Redis endpoint. Do not expose the test
Redis publicly; multi-user authentication and control leases are not implemented.

Each device handle is bound to an epoch. Rediscover devices after a game/session restart.
Telemetry has an age check. On command timeout the result is unknown; do not blindly
retry a toggle. Command IDs are deduplicated by the plugin, but crash-safe exactly-once
execution is not promised. `Client.command(..., expected_revision=N)` enables an
optimistic conflict check. FIFO ordering is not exclusive ownership of a device.

Unit tests: `python -m pytest tests/test_se2.py tests/test_grid_rebind_compat.py`.
Flight usage guide (align_course, precise return, player control): [SE2_NAVIGATION.md](SE2_NAVIGATION.md).
Live tests and performance evidence are in the SE2GameAPI plugin project:
https://github.com/rootfabric/SE2GameAPI (transport and protocol implementation;
this Python backend is the reference client).
