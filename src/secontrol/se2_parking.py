"""Docking helper: park a ship grid onto a counterpart connector via the autopilot."""
from __future__ import annotations

import math
import time
from typing import Any

from .se2 import BridgeError, Client, ConnectorDevice
from .se2_navigation import AutopilotDevice

STANDOFF = 0.05      # final gap between pivots, metres (engine alignment limit ~0.1 m)
APPROACH = 15.0      # waypoint distance in front of the dock, metres


# --- minimal quaternion helpers (w, x, y, z) ---------------------------------
def quat_multiply(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return (aw*bw - ax*bx - ay*by - az*bz,
            aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw)


def quat_conjugate(q):
    return (q[0], -q[1], -q[2], -q[3])


def quat_rotate(q, v):
    qv = (0.0, v[0], v[1], v[2])
    r = quat_multiply(quat_multiply(q, qv), quat_conjugate(q))
    return [r[1], r[2], r[3]]


def quat_from_orientation(forward, up):
    """Rotation matching plugin NavigationMath.Orientation: -Z maps to forward, +Y to up."""
    def norm(v):
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]

    def cross(a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    f = norm(forward); u = norm(up)
    r = cross(f, u)
    if abs(dot(r, r)) < 1e-6:
        raise ValueError("parallel forward/up")
    r = norm(r); u = cross(r, f)
    # rotation matrix columns: right (X), up (Y), -forward (Z)
    m = [[r[0], u[0], -f[0]],
         [r[1], u[1], -f[1]],
         [r[2], u[2], -f[2]]]
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = (0.25*s, (m[2][1]-m[1][2])/s, (m[0][2]-m[2][0])/s, (m[1][0]-m[0][1])/s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = ((m[2][1]-m[1][2])/s, 0.25*s, (m[0][1]+m[1][0])/s, (m[0][2]+m[2][0])/s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][2]-m[2][0])/s, (m[0][1]+m[1][0])/s, 0.25*s, (m[1][2]+m[2][1])/s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[1][0]-m[0][1])/s, (m[0][2]+m[2][0])/s, (m[1][2]+m[2][1])/s, 0.25*s)
    n = math.sqrt(sum(x * x for x in q))
    return tuple(x / n for x in q)


def park_pose(grid, own, dock, standoff=STANDOFF, mating_flip=True):
    """Compute (position, forward, up) the grid must take so its connector mates the dock."""
    gp, gf, gu = grid["position"], grid["forward"], grid["up"]
    pp, pf, pu = own["pivotPosition"], own["pivotForward"], own["pivotUp"]
    dp, df, du = dock["pivotPosition"], dock["pivotForward"], dock["pivotUp"]
    q_grid = quat_from_orientation(gf, gu)
    inv = quat_conjugate(q_grid)
    offset_local = quat_rotate(inv, [a - b for a, b in zip(pp, gp)])
    q_pivot_local = quat_from_orientation(quat_rotate(inv, pf), quat_rotate(inv, pu))
    fwd_des = [-x for x in df] if mating_flip else list(df)
    q_pivot_des = quat_from_orientation(fwd_des, du)
    q_target = quat_multiply(q_pivot_des, quat_conjugate(q_pivot_local))
    forward = quat_rotate(q_target, [0.0, 0.0, -1.0])
    up = quat_rotate(q_target, [0.0, 1.0, 0.0])
    position = [a - b for a, b in zip(dp, quat_rotate(q_target, offset_local))]
    # keep a small gap: pull the ship back along the dock mating axis
    back = [x * standoff for x in df] if mating_flip else [-x * standoff for x in df]
    position = [a + b for a, b in zip(position, back)]
    return position, forward, up


def _props(device) -> dict[str, Any]:
    return device.refresh()["properties"] if hasattr(device, "refresh") else device._state["properties"]


def park(bridge: Client, grid_name: str, dock_id: str | None = None, *,
         standoff: float = STANDOFF, approach: float = APPROACH, max_speed: float = 3.0,
         timeout: float = 240.0, poll: float = 0.5) -> dict[str, Any]:
    """Fly the grid to its dock connector and connect. Returns docking report."""
    autopilot: AutopilotDevice
    autopilot, = [d for d in bridge.devices(device_type="autopilot") if d._state["gridName"] == grid_name]
    own: ConnectorDevice
    candidates = [d for d in bridge.connectors(grid_name=grid_name)]
    if not candidates:
        raise BridgeError(f"no connector on grid {grid_name!r}")
    own = candidates[0]
    own_props = _props(own)
    if dock_id is None:
        dock_id = own_props.get("nearbyCounterpartId") or own_props.get("counterpartId")
    if dock_id is None:
        docks = [f"{d._state['id']} ({d._state['gridName']})" for d in bridge.connectors()]
        raise BridgeError("dock_id required; available connectors: " + ", ".join(docks))
    dock, = [d for d in bridge.connectors() if d._state["id"] == dock_id]
    dock_props = _props(dock)
    if dock._state["gridName"] == grid_name:
        raise BridgeError("dock connector is on the same grid")

    grid_props = autopilot.refresh()["properties"]
    position, forward, up = park_pose(grid_props, own_props, dock_props, standoff=standoff)
    # waypoint in front of the dock along its mating axis
    out = [x * approach for x in dock_props["pivotForward"]]
    waypoint = [a + b for a, b in zip(position, out)]

    r = autopilot.goto(waypoint, forward=forward, up=up, mode="flight",
                       max_speed=max_speed, position_tolerance=1.0, timeout=timeout)
    autopilot.wait(r.actual_state["properties"]["missionId"], timeout=timeout + 30)
    # final mating approach: the engine alignment limit is ~0.1 m, so creep in slowly
    r = autopilot.goto(position, forward=forward, up=up, mode="flight",
                       max_speed=min(1.0, max_speed), position_tolerance=0.05,
                       heading_tolerance_deg=1.0, timeout=timeout)
    autopilot.wait(r.actual_state["properties"]["missionId"], timeout=timeout + 30)

    deadline = time.monotonic() + 90
    last_error = None
    while time.monotonic() < deadline:
        props = _props(own)
        if props.get("isConnected"):
            break
        try:
            own.connect()
        except BridgeError as e:
            last_error = str(e)
        time.sleep(poll)
    connected = _props(own).get("isConnected")
    if not connected:
        raise BridgeError(f"docking failed: {last_error or 'not aligned within limits'}")
    return {"grid": grid_name, "dock": dock_id, "connected": connected,
            "position": [round(x, 2) for x in autopilot.refresh()["properties"]["position"]]}


def unpark(bridge: Client, grid_name: str, backoff: float = 40.0, *, max_speed: float = 3.0,
           timeout: float = 180.0) -> dict[str, Any]:
    """Disconnect and back the grid away along the dock axis."""
    autopilot, = [d for d in bridge.devices(device_type="autopilot") if d._state["gridName"] == grid_name]
    own, = [d for d in bridge.connectors(grid_name=grid_name)]
    props = _props(own)
    if props.get("isConnected"):
        own.disconnect()
        time.sleep(1)
    dock_id = props.get("counterpartId") or props.get("nearbyCounterpartId")
    grid_props = autopilot.refresh()["properties"]
    if dock_id:
        dock, = [d for d in bridge.connectors() if d._state["id"] == dock_id]
        dock_props = _props(dock)
        away = [x * backoff for x in dock_props["pivotForward"]]
        target = [a + b for a, b in zip(grid_props["position"], away)]
    else:
        fwd = grid_props["forward"]
        target = [a - f * backoff for a, f in zip(grid_props["position"], fwd)]
    # No forward/up and no align_course: keep the docking orientation, fly straight out.
    r = autopilot.goto(target, mode="flight", max_speed=max_speed,
                       position_tolerance=2.0, timeout=timeout)
    autopilot.wait(r.actual_state["properties"]["missionId"], timeout=timeout + 30)
    return {"grid": grid_name, "connected": _props(own).get("isConnected"),
            "position": [round(x, 2) for x in autopilot.refresh()["properties"]["position"]],
            "heading": [round(x, 3) for x in autopilot.refresh()["properties"]["forward"]]}
