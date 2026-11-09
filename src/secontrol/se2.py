"""Opt-in Redis backend for Space Engineers 2."""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
import redis

class BridgeError(RuntimeError):
    pass

STATE_CHANNEL = "se2:local:state"
REPLY_CHANNEL = "se2:local:replies"

@dataclass(frozen=True)
class CommandResult:
    request_id: str
    status: str
    actual_state: dict[str, Any]
    latency_ms: float

class Client:
    _ENQUEUE = """
if redis.call('LLEN', KEYS[1]) >= 256 then return 0 end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], 15)
return 1
"""
    def __init__(self, url: str = "redis://127.0.0.1:6379/0", *, prefix: str = "se2:local", timeout: float = 3.0):
        if not .1 <= timeout <= 9:
            raise ValueError("timeout must be 0.1..9 seconds")
        self.redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
        self.prefix, self.timeout = prefix, timeout
        self._snapshot: dict[str, Any] | None = None
        self._read_at = 0.0

    def snapshot(self, *, fresh: bool = False) -> dict[str, Any]:
        if fresh or self._snapshot is None or time.monotonic() - self._read_at > .1:
            raw = self.redis.get(f"{self.prefix}:state")
            if raw is None:
                raise BridgeError("Bridge is offline or its state expired")
            self._snapshot = json.loads(raw)
            self._read_at = time.monotonic()
        value = self._snapshot
        if value["state"] != "READY":
            raise BridgeError(f"World is not ready: {value['state']}")
        age = time.time() * 1000 - value["sampledAtMs"]
        if age < -1000 or age > 3000:
            raise BridgeError("Stale game telemetry or clock mismatch")
        if value.get("error"):
            raise BridgeError(value["error"])
        return value

    def devices(self, *, device_type: str | None = None, grid_name: str | None = None,
                name: str | None = None) -> list[Device]:
        from .se2_navigation import AutopilotDevice
        factories = {"lamp": LampDevice, "door": DoorDevice, "connector": ConnectorDevice,
                     "cargo": CargoDevice, "autopilot": AutopilotDevice, "thruster": ThrusterDevice,
                     "gravity_generator": GravityDevice, "antenna": AntennaDevice,
                     "landing_gear": LandingGearDevice, "drill": DrillDevice,
                     "Reactor": ConverterDevice,
                     "O2H2Generator": ConverterDevice, "Battery": BatteryDevice,
                     "tank": TankDevice}
        snapshot = self.snapshot(fresh=True)
        return [factories.get(item.get("type", "lamp"), FunctionalDevice)(self, snapshot["epoch"], item)
                for item in snapshot.get("devices", snapshot.get("lamps", []))
                if (device_type is None or item.get("type", "lamp") == device_type)
                and (grid_name is None or item["gridName"] == grid_name)
                and (name is None or item["name"].replace("\u00a0", " ") == name.replace("\u00a0", " "))]

    def lamps(self, **filters) -> list[LampDevice]:
        return self.devices(device_type="lamp", **filters)
    def doors(self, **filters) -> list[DoorDevice]:
        return self.devices(device_type="door", **filters)
    def connectors(self, **filters) -> list[ConnectorDevice]:
        return self.devices(device_type="connector", **filters)
    def drills(self, **filters) -> list[DrillDevice]:
        return self.devices(device_type="drill", **filters)
    def containers(self, **filters) -> list[CargoDevice]:
        return self.devices(device_type="cargo", **filters)

    def command(self, device: Device, cmd: str, *, enabled: bool | None = None,
                expected_revision: int | None = None, target_id: str | None = None,
                item_index: int | None = None, amount: float | None = None,
                navigation: dict[str, Any] | None = None, mode: str | None = None) -> CommandResult:
        if cmd not in device.commands:
            raise BridgeError(f"Unsupported capability: {cmd}")
        snapshot = self.snapshot(fresh=True)
        if snapshot["epoch"] != device.epoch:
            raise BridgeError("Session changed; rediscover devices before writing")
        request_id = uuid.uuid4().hex
        payload = {"requestId": request_id, "epoch": device.epoch, "gridId": device.grid_id,
                   "deviceId": device.device_id, "cmd": cmd, "enabled": enabled,
                   "expectedRevision": expected_revision, "targetId": target_id,
                   "itemIndex": item_index, "amount": amount, "navigation": navigation,
                   "mode": mode,
                   "expiresAtMs": int((time.time() + self.timeout) * 1000)}
        started = time.monotonic()
        if not self.redis.eval(self._ENQUEUE, 1, f"{self.prefix}:commands", json.dumps(payload)):
            raise BridgeError("Command queue is full")
        while time.monotonic() - started < self.timeout + .5:
            raw = self.redis.get(f"{self.prefix}:reply:{request_id}")
            if raw:
                result = json.loads(raw)
                if result["status"] != "confirmed":
                    raise BridgeError(f"{result['status']}: {result.get('error')}")
                device._state = result["actualState"]
                self._snapshot = None
                return CommandResult(request_id, result["status"], result["actualState"],
                                     (time.monotonic() - started) * 1000)
            time.sleep(.01)
        raise TimeoutError(f"Unknown command outcome: {request_id}; read telemetry before retrying")

    def subscribe(self):
        """Open a pub/sub subscription to bridge notifications.

        Yields ("state", snapshot) every publish tick and ("reply", receipt)
        for every completed command. Plain Redis PUBLISH/SUBSCRIBE: no server
        configuration is required. Close the returned PubSub to stop.
        """
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(STATE_CHANNEL, REPLY_CHANNEL)
        return pubsub

    def listen(self, callback, *, timeout: float | None = None):
        """Blocking event loop: calls callback(kind, payload) for each notification."""
        import time as _time
        pubsub = self.subscribe()
        deadline = None if timeout is None else _time.monotonic() + timeout
        try:
            for message in pubsub.listen():
                channel = message.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode()
                kind = {STATE_CHANNEL: "state", REPLY_CHANNEL: "reply"}.get(channel)
                if kind is None:
                    continue
                payload = json.loads(message["data"])
                callback(kind, payload)
                if deadline is not None and _time.monotonic() > deadline:
                    break
        finally:
            pubsub.close()

    def close(self) -> None:
        self.redis.close()
    def __enter__(self) -> Client:
        return self
    def __exit__(self, *_: object) -> None:
        self.close()

class Device:
    device_type = "device"
    commands = frozenset()
    capabilities = frozenset()
    def __init__(self, client: Client, epoch: str, state: dict[str, Any]):
        self.client, self.epoch, self._state = client, epoch, state
        self.device_id, self.grid_id, self.name = state["id"], state["gridId"], state["name"]
    def refresh(self) -> dict[str, Any]:
        snapshot = self.client.snapshot(fresh=True)
        if snapshot["epoch"] != self.epoch:
            raise BridgeError("Session changed; rediscover devices")
        for state in snapshot.get("devices", snapshot.get("lamps", [])):
            if state["id"] == self.device_id and state["gridId"] == self.grid_id:
                if time.time() * 1000 - state.get("measuredAtMs", snapshot["sampledAtMs"]) > 3000:
                    raise BridgeError("Stale device telemetry")
                self._state = state
                return state
        raise BridgeError("Device was removed or moved to another grid")
    @property
    def telemetry(self) -> dict[str, Any]:
        return self._state

class FunctionalDevice(Device):
    device_type = "functional"
    commands = frozenset({"enable", "disable", "set_enabled", "toggle"})
    capabilities = frozenset({"switch.enabled"})
    def is_enabled(self) -> bool:
        return bool(self._state["enabled"])
    def enable(self) -> CommandResult:
        return self.client.command(self, "enable")
    def disable(self) -> CommandResult:
        return self.client.command(self, "disable")
    def set_enabled(self, enabled: bool) -> CommandResult:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        return self.client.command(self, "set_enabled", enabled=enabled)
    def toggle(self) -> CommandResult:
        return self.client.command(self, "toggle")

class LampDevice(FunctionalDevice):
    device_type = "lamp"
    commands = FunctionalDevice.commands | {"set_brightness"}
    capabilities = FunctionalDevice.capabilities | {"light.brightness"}
    def set_brightness(self, value: float) -> CommandResult:
        if not isinstance(value, (int, float)) or not 0 <= value <= 10:
            raise ValueError("brightness must be within 0..10")
        return self.client.command(self, "set_brightness", amount=float(value))

class DoorDevice(FunctionalDevice):
    device_type = "door"
    capabilities = FunctionalDevice.capabilities | {"door.open"}
    commands = FunctionalDevice.commands | {"open", "close", "toggle_door"}
    def open(self) -> CommandResult:
        return self.client.command(self, "open")
    def close(self) -> CommandResult:
        return self.client.command(self, "close")
    def toggle_door(self) -> CommandResult:
        return self.client.command(self, "toggle_door")

class DrillDevice(FunctionalDevice):
    """Ship drill: primary action collects ore, secondary action excavates wider (extend)."""
    device_type = "drill"
    capabilities = FunctionalDevice.capabilities | {"drill.mode"}
    commands = FunctionalDevice.commands | {"drill_mode"}
    def start_collect(self) -> CommandResult:
        """Ore collection mode (primary brush)."""
        return self.client.command(self, "drill_mode", mode="collect")
    def start_extend(self) -> CommandResult:
        """Extension/excavation mode (secondary, wider brush)."""
        return self.client.command(self, "drill_mode", mode="extend")
    def stop(self) -> CommandResult:
        return self.client.command(self, "drill_mode", mode="off")
    @property
    def mode(self) -> str:
        return {"Collect": "collect", "Extend": "extend"}.get(self._state.get("status"), "off")
    @property
    def drilling_voxels(self) -> bool:
        return bool((self._state.get("properties") or {}).get("isDrillingVoxels"))
    @property
    def detected_content(self) -> bool:
        return bool((self._state.get("properties") or {}).get("hasDetectedDrillableContent"))


class ConnectorDevice(FunctionalDevice):
    device_type = "connector"
    capabilities = FunctionalDevice.capabilities | {"connector.connect", "inventory.transfer"}
    commands = FunctionalDevice.commands | {"connect", "disconnect", "transfer_item"}
    @property
    def connected(self) -> bool:
        return self._state.get("status") == "Connected"
    @property
    def counterpart_id(self) -> str | None:
        return (self._state.get("properties") or {}).get("counterpartId")
    @property
    def nearby_counterpart_id(self) -> str | None:
        return (self._state.get("properties") or {}).get("nearbyCounterpartId")
    @property
    def ready_to_connect(self) -> bool:
        return bool((self._state.get("properties") or {}).get("readyToConnect"))
    @property
    def pivot(self) -> dict:
        """World-space mating pivot: position/forward/up arrays, if exposed by the bridge."""
        props = self._state.get("properties") or {}
        return {"position": props.get("pivotPosition"), "forward": props.get("pivotForward"),
                "up": props.get("pivotUp")}
    @property
    def inventories(self) -> list[dict[str, Any]]:
        return self._state.get("inventories") or []
    def items(self) -> list[dict[str, Any]]:
        inventory = self.inventories[0] if self.inventories else {}
        return inventory.get("items") or []
    def connect(self) -> CommandResult:
        return self.client.command(self, "connect")
    def disconnect(self) -> CommandResult:
        return self.client.command(self, "disconnect")
    def transfer_item(self, target, item_index: int, amount: float) -> CommandResult:
        """Move items to another inventory-bearing device (connector/cargo) on a connected conveyor system."""
        if not isinstance(target, (ConnectorDevice, CargoDevice)) or target.client is not self.client:
            raise ValueError("target must be a connector or cargo device of the same client")
        if not isinstance(item_index, int) or item_index < 0:
            raise ValueError("item_index must be nonnegative")
        return self.client.command(self, "transfer_item", target_id=target.device_id,
                                   item_index=item_index, amount=float(amount))

class CargoDevice(Device):
    device_type = "cargo"
    capabilities = frozenset({"inventory.read", "inventory.transfer"})
    commands = frozenset({"transfer_item"})
    @property
    def items(self) -> list[dict[str, Any]]:
        return self._state["properties"]["items"]
    def transfer_item(self, target: CargoDevice, item_index: int, amount: float) -> CommandResult:
        if not isinstance(target, CargoDevice) or target.client is not self.client:
            raise TypeError("target must be a cargo device from the same client")
        if not isinstance(item_index, int) or item_index < 0:
            raise ValueError("item_index must be nonnegative")
        if not isinstance(amount, (int, float)) or not 0 < amount < float("inf"):
            raise ValueError("amount must be finite and positive")
        if target.epoch != self.epoch or target.grid_id != self.grid_id:
            raise BridgeError("Target must be on the same grid and session")
        return self.client.command(self, "transfer_item", target_id=target.device_id,
                                   item_index=item_index, amount=float(amount))

class ScalarDevice(FunctionalDevice):
    scalar_command = ""
    minimum, maximum = 0.0, 1.0
    def set_value(self, value: float) -> CommandResult:
        if not isinstance(value, (int, float)) or not self.minimum <= value <= self.maximum:
            raise ValueError(f"value must be within {self.minimum}..{self.maximum}")
        return self.client.command(self, self.scalar_command, amount=float(value))

class ThrusterDevice(ScalarDevice):
    device_type = "thruster"
    scalar_command = "set_thrust_override"
    commands = FunctionalDevice.commands | {scalar_command}
    capabilities = FunctionalDevice.capabilities | {"thruster.override"}
    def set_thrust_override(self, fraction: float) -> CommandResult:
        return self.set_value(fraction)

class GravityDevice(ScalarDevice):
    device_type = "gravity_generator"
    scalar_command = "set_gravity"
    minimum, maximum = -9.81, 9.81
    commands = FunctionalDevice.commands | {scalar_command}
    capabilities = FunctionalDevice.capabilities | {"gravity.acceleration"}
    def set_gravity(self, acceleration: float) -> CommandResult:
        return self.set_value(acceleration)

class BooleanPropertyDevice(FunctionalDevice):
    property_command = ""
    def set_property(self, enabled: bool) -> CommandResult:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        return self.client.command(self, self.property_command, enabled=enabled)

class AntennaDevice(BooleanPropertyDevice):
    device_type = "antenna"
    property_command = "set_broadcast"
    commands = FunctionalDevice.commands | {property_command}
    capabilities = FunctionalDevice.capabilities | {"antenna.broadcast"}
    def set_broadcast(self, enabled: bool) -> CommandResult:
        return self.set_property(enabled)

class ConverterDevice(BooleanPropertyDevice):
    property_command = "set_processing"
    commands = FunctionalDevice.commands | {property_command}
    capabilities = FunctionalDevice.capabilities | {"converter.processing"}
    def set_processing(self, enabled: bool) -> CommandResult:
        return self.set_property(enabled)

class LandingGearDevice(FunctionalDevice):
    device_type = "landing_gear"
    commands = FunctionalDevice.commands | {"lock", "unlock", "set_auto_lock"}
    capabilities = FunctionalDevice.capabilities | {"landing_gear.lock", "landing_gear.auto_lock"}
    def lock(self) -> CommandResult:
        return self.client.command(self, "lock")
    def unlock(self) -> CommandResult:
        return self.client.command(self, "unlock")
    def set_auto_lock(self, enabled: bool) -> CommandResult:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        return self.client.command(self, "set_auto_lock", enabled=enabled)

class ResourceMode:
    def set_mode(self, mode: str) -> CommandResult:
        if not isinstance(mode, str) or mode.lower() not in {"auto", "charge", "discharge"}:
            raise ValueError("mode must be auto, charge or discharge")
        return self.client.command(self, "set_mode", mode=mode.lower())

class BatteryDevice(ResourceMode, FunctionalDevice):
    device_type = "Battery"
    commands = FunctionalDevice.commands | {"set_mode"}
    capabilities = FunctionalDevice.capabilities | {"resource.charge", "resource.mode"}

class TankDevice(ResourceMode, Device):
    device_type = "tank"
    commands = frozenset({"set_mode"})
    capabilities = frozenset({"state.read", "resource.charge", "resource.mode"})
