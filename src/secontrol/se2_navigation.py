"""Virtual SE2 grid autopilot. The flight loop runs inside the game plugin."""
import math
import time
from .se2 import Device, BridgeError


class AutopilotDevice(Device):
    device_type = "autopilot"
    commands = frozenset({"autopilot_goto", "autopilot_stop"})
    capabilities = frozenset({"navigation.flight", "navigation.ground.experimental", "navigation.stop"})

    def goto(self, target, *, forward=None, up=None, mode="flight", max_speed=5.0,
             position_tolerance=1.0, heading_tolerance_deg=3.0, timeout=120.0,
             align_course=False, cancel_on_player=False, eject_pilot=False):
        """Start a mission; ACK confirms acceptance. Use wait() to observe arrival.

        target is a world position in metres; forward is world direction of grid -Z.
        align_course=True keeps the nose aligned with the direction to the target
        during the whole flight; it is mutually exclusive with forward.
        cancel_on_player=False (default): a player entering a seat does not cancel
        the mission; the controller keeps commanding. Set True to restore the old
        yield-to-player behaviour.
        eject_pilot=True: the pilot is unseated at mission start (and re-ejected if
        they sit back down) so their zero input cannot override the controller.
        Ground final-heading control is not yet supported. No obstacle avoidance.
        """
        if align_course:
            if forward is not None:
                raise ValueError("align_course cannot be combined with forward")
            if mode == "ground":
                raise ValueError("align_course is not supported in ground mode")

        def vector(value):
            if value is None:
                return None
            result = list(value)
            if len(result) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in result):
                raise ValueError("Expected three finite coordinates")
            return result
        return self.client.command(self, "autopilot_goto", navigation={
            "target": vector(target), "forward": vector(forward), "up": vector(up), "mode": mode,
            "maxSpeed": max_speed, "positionTolerance": position_tolerance,
            "headingToleranceDeg": heading_tolerance_deg, "timeoutSeconds": timeout,
            "alignCourse": align_course, "keepControlOnPlayer": not cancel_on_player,
            "ejectPilot": eject_pilot})

    def stop(self):
        return self.client.command(self, "autopilot_stop")

    def wait(self, mission_id, *, timeout=130.0):
        """Observe one mission. Caller timeout does not cancel the game mission."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.refresh()
            info = state["properties"]
            if info["missionId"] != mission_id:
                time.sleep(.1)
                continue
            if state["status"] == "Arrived":
                return state
            if state["status"] in {"Failed", "Stopped", "Cancelled"}:
                raise BridgeError(f"{state['status']}: {info['error']}")
            time.sleep(.2)
        raise TimeoutError("Mission wait expired; inspect telemetry or call stop()")
