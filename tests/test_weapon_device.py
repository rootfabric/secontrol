from secontrol.devices.weapon_device import InteriorTurretDevice, WeaponDevice


def _make_device(cls, telemetry):
    device = cls.__new__(cls)
    device.telemetry = telemetry
    issued = {}

    def _fake_send(payload):
        issued["payload"] = payload
        return payload

    device.send_command = _fake_send  # type: ignore[attr-defined]
    return device, issued


def test_weapon_device_telemetry_helpers():
    telemetry = {
        "isFunctional": True,
        "isWorking": True,
        "isShooting": False,
        "isReloading": True,
        "useConveyorSystem": True,
        "currentAmmo": 12,
        "maxAmmo": 20,
        "magazineCount": 3,
        "heatRatio": 0.5,
        "rateOfFire": 600,
        "reloadTimeRemaining": 1.5,
        "timeSinceLastShot": 0.2,
    }
    device, _ = _make_device(WeaponDevice, telemetry)

    assert device.is_functional() is True
    assert device.is_working() is True
    assert device.is_shooting() is False
    assert device.is_reloading() is True
    assert device.use_conveyor() is True

    ammo = device.ammo_status()
    assert ammo == {"current": 12.0, "maximum": 20.0, "magazines": 3.0}
    assert device.heat_ratio() == 0.5
    assert device.rate_of_fire() == 600.0
    assert device.reload_time_remaining() == 1.5
    assert device.time_since_last_shot() == 0.2


def test_weapon_device_command_helpers():
    device, issued = _make_device(WeaponDevice, {})

    device.shoot_once()
    assert issued["payload"] == {"cmd": "shoot_once"}

    device.set_shooting(True)
    assert issued["payload"] == {"cmd": "shoot_on"}

    device.set_shooting(False)
    assert issued["payload"] == {"cmd": "shoot_off"}

    device.set_use_conveyor(True)
    assert issued["payload"] == {
        "cmd": "use_conveyor",
        "state": {"useConveyor": True},
    }


def test_interior_turret_specific_helpers():
    telemetry = {
        "aiEnabled": True,
        "idleRotation": False,
        "range": 350,
        "target": {"type": "enemy", "distance": 150},
    }
    device, issued = _make_device(InteriorTurretDevice, telemetry)

    assert device.ai_enabled() is True
    assert device.idle_rotation() is False
    assert device.range() == 350.0
    assert device.target() == telemetry["target"]

    device.set_idle_rotation(True)
    assert issued["payload"] == {
        "cmd": "idle_rotation",
        "state": {"idleRotation": True},
    }

    device.set_range(200)
    assert issued["payload"] == {"cmd": "set_range", "state": {"range": 200.0}}

    device.reset_target()
    assert issued["payload"] == {"cmd": "reset_target"}
