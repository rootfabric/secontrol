from __future__ import annotations

from secontrol.tools import navigation_tools as nav_tools


class FakeRemote:
    name = "Fake Remote"

    def __init__(self):
        self.telemetry = {
            "worldPosition": [0.0, 0.0, 0.0],
            "autopilotEnabled": False,
        }
        self.commands: list[str] = []
        self.enabled = False
        self.update_count = 0

    def update(self):
        self.update_count += 1
        if self.enabled and self.update_count >= 2:
            self.telemetry["worldPosition"] = [10.0, 0.0, 0.0]

    def handbrake_off(self):
        self.commands.append("handbrake_off")
        return 1

    def set_mode(self, mode):
        self.commands.append("set_mode")
        return 1

    def set_collision_avoidance(self, enabled):
        self.commands.append("collision")
        return 1

    def goto(self, *args, **kwargs):
        self.commands.append("goto")
        return 1

    def enable(self):
        self.commands.append("enable")
        self.enabled = True
        self.telemetry["autopilotEnabled"] = True
        return 1

    def disable(self):
        self.commands.append("disable")
        self.enabled = False
        self.telemetry["autopilotEnabled"] = False
        return 1


def test_fly_to_point_enables_after_goto_and_disables_on_arrival(monkeypatch):
    monkeypatch.setattr(nav_tools.time, "sleep", lambda _seconds: None)
    remote = FakeRemote()

    final_pos = nav_tools.fly_to_point(
        remote,
        (10.0, 0.0, 0.0),
        arrival_distance=1.0,
        check_interval=0.01,
    )

    assert final_pos == (10.0, 0.0, 0.0)
    assert remote.commands.index("enable") > remote.commands.index("goto")
    assert remote.commands[-1] == "disable"
