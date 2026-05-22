#!/usr/bin/env python3
"""Fly skynet-baza0 to the second farthest asteroid and scan for resources."""
from __future__ import annotations

import math
import time
import json
import os
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)

import redis

from secontrol.grids import Grid
from secontrol.tools.navigation_tools import get_world_position, fly_to_point, _dist


def create_admin_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD")
    return redis.Redis.from_url(url, username=admin_user, password=admin_pass, decode_responses=True)


def main():
    owner_id = "144115188075855921"
    grid_id = "100628801218667230"

    print("Connecting to skynet-baza0 via admin Redis...")
    admin_r = create_admin_client()

    from secontrol.redis_client import RedisEventClient
    client = RedisEventClient.__new__(RedisEventClient)
    client.client = admin_r
    client._subscriptions = {}

    grid = Grid(client, owner_id, grid_id, owner_id, auto_wake=True)
    time.sleep(3)

    print(f"Grid: {grid.state.name}")
    print(f"Devices: {len(grid.devices)}")

    pos = None
    for dev in grid.devices.values():
        tel = dev.telemetry or {}
        wp = tel.get("worldPosition") or tel.get("position")
        if wp:
            try:
                if isinstance(wp, dict):
                    pos = (float(wp.get("x", 0)), float(wp.get("y", 0)), float(wp.get("z", 0)))
                elif isinstance(wp, (list, tuple)):
                    pos = (float(wp[0]), float(wp[1]), float(wp[2]))
                if pos and any(abs(p) > 1 for p in pos):
                    print(f"Ship position from {dev.name}: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")
                    break
            except:
                pass

    if not pos:
        print("ERROR: Could not get ship position")
        grid.close()
        return

    from secontrol.devices.ore_detector_device import OreDetectorDevice
    from secontrol.devices.remote_control_device import RemoteControlDevice

    ore_detectors = [d for d in grid.devices.values() if isinstance(d, OreDetectorDevice)]
    remote_controls = [d for d in grid.devices.values() if isinstance(d, RemoteControlDevice)]

    if not ore_detectors:
        print("ERROR: No ore detector found")
        grid.close()
        return
    if not remote_controls:
        print("ERROR: No remote control found")
        grid.close()
        return

    radar = ore_detectors[0]
    remote = remote_controls[0]
    print(f"Ore detector: {radar.name} (id={radar.device_id})")
    print(f"Remote control: {remote.name} (id={remote.device_id})")

    print("\nScanning for asteroids...")
    radar.update()
    seq = radar.scan(
        include_players=True,
        include_grids=True,
        include_voxels=True,
        radius=5000,
        cell_size=50,
        boundingBoxX=5000,
        boundingBoxY=5000,
        boundingBoxZ=5000,
        fullSolidScan=False,
        voxel_step=5,
    )
    print(f"Scan sent, seq={seq}")

    start = time.time()
    while time.time() - start < 120:
        time.sleep(1)
        radar.update()
        tel = radar.telemetry or {}
        scan = tel.get("scan", {})
        if isinstance(scan, dict):
            progress = scan.get("progressPercent", 0)
            in_progress = scan.get("inProgress", False)
            done = scan.get("done", False)
            if done or (not in_progress and progress > 50):
                print(f"Scan done: {progress}%")
                break
            elif progress > 0:
                print(f"Scan progress: {progress:.1f}%")

    time.sleep(2)
    radar.update()
    contacts = radar.contacts()
    print(f"\nTotal contacts: {len(contacts)}")

    asteroids = []
    for c in contacts:
        ctype = c.get("type", "")
        if ctype in ("voxel", "asteroid", "voxelAsteroid"):
            asteroids.append(c)

    if not asteroids:
        for c in contacts:
            pos_check = c.get("position") or c.get("center") or c.get("pos")
            if pos_check and c.get("type") not in ("grid", "player"):
                asteroids.append(c)

    print(f"Asteroids from contacts: {len(asteroids)}")

    if not asteroids:
        print("Using solid points to find asteroids...")
        radar_data = (radar.telemetry or {}).get("radar", {})
        raw = radar_data.get("raw", {})
        solid = raw.get("solidPoints", [])
        if solid:
            print(f"Solid points: {len(solid)}")
            clusters = cluster_points(solid, threshold=200)
            for i, cluster in enumerate(clusters):
                center = centroid(cluster)
                asteroids.append({
                    "type": "voxel",
                    "position": center,
                    "name": f"Asteroid_{i}",
                    "point_count": len(cluster),
                })
            print(f"Estimated asteroids: {len(asteroids)}")
        else:
            print("No solid points either")
            print("Radar raw keys:", sorted(raw.keys()) if raw else "none")
            grid.close()
            return

    if not asteroids:
        print("ERROR: No asteroids found")
        grid.close()
        return

    asteroid_distances = []
    for a in asteroids:
        apos = get_asteroid_position(a)
        if apos:
            dist = _dist(pos, apos)
            name = a.get("name", a.get("label", "Unknown"))
            asteroid_distances.append((dist, name, apos, a))

    asteroid_distances.sort(key=lambda x: x[0])

    print(f"\nAsteroids sorted by distance:")
    for i, (dist, name, apos, _) in enumerate(asteroid_distances):
        marker = " <-- TARGET" if i == 1 else ""
        print(f"  {i+1}. {name}: {dist:.0f}m at ({apos[0]:.0f}, {apos[1]:.0f}, {apos[2]:.0f}){marker}")

    if len(asteroid_distances) < 2:
        print("ERROR: Less than 2 asteroids found")
        grid.close()
        return

    target_dist, target_name, target_pos, _ = asteroid_distances[1]
    print(f"\nTarget: {target_name} at {target_dist:.0f}m")

    print(f"\nFlying to {target_name}...")
    result = fly_to_point(
        remote,
        target_pos,
        waypoint_name=target_name,
        speed_far=20.0,
        speed_near=5.0,
        arrival_distance=100.0,
        stop_tolerance=2.0,
        max_flight_time=600.0,
    )

    if result:
        print(f"Arrived near {target_name}!")
        print(f"Final position: ({result[0]:.1f}, {result[1]:.1f}, {result[2]:.1f})")
    else:
        print("Flight did not complete normally")

    time.sleep(2)

    print(f"\nScanning for resources at {target_name}...")
    radar.update()
    scan_seq = radar.scan(
        include_players=False,
        include_grids=False,
        include_voxels=True,
        radius=500,
        cell_size=10,
        boundingBoxX=500,
        boundingBoxY=500,
        boundingBoxZ=500,
        ore_only=True,
        voxel_step=2,
    )
    print(f"Resource scan sent, seq={scan_seq}")

    start = time.time()
    while time.time() - start < 60:
        time.sleep(1)
        radar.update()
        tel = radar.telemetry or {}
        scan = tel.get("scan", {})
        if isinstance(scan, dict):
            progress = scan.get("progressPercent", 0)
            in_progress = scan.get("inProgress", False)
            done = scan.get("done", False)
            if done or (not in_progress and progress > 50):
                print(f"Resource scan done: {progress}%")
                break

    time.sleep(2)
    radar.update()
    ore_cells = radar.ore_cells()
    print(f"\nResources found: {len(ore_cells)} ore deposits")

    resources = {}
    for cell in ore_cells:
        material = cell.get("material") or cell.get("ore") or "Unknown"
        if material not in resources:
            resources[material] = []
        resources[material].append(cell)

    print("\n=== Resources on asteroid ===")
    for material, cells in sorted(resources.items()):
        total = sum(c.get("content", 0) if isinstance(c.get("content"), (int, float)) else 0 for c in cells)
        print(f"  {material}: {len(cells)} deposits, total content: {total}")

    if not resources:
        print("  (no valuable ores detected - may need closer scan)")

    grid.close()


def get_asteroid_position(asteroid):
    for key in ("position", "center", "pos"):
        val = asteroid.get(key)
        if val:
            if isinstance(val, dict):
                return (float(val.get("x", 0)), float(val.get("y", 0)), float(val.get("z", 0)))
            elif isinstance(val, (list, tuple)) and len(val) >= 3:
                return (float(val[0]), float(val[1]), float(val[2]))
            elif isinstance(val, str):
                parts = val.split(",")
                if len(parts) == 3:
                    return (float(parts[0].strip()), float(parts[1].strip()), float(parts[2].strip()))
    return None


def cluster_points(points, threshold=200):
    if not points:
        return []
    clusters = []
    used = [False] * len(points)
    for i in range(len(points)):
        if used[i]:
            continue
        cluster = [points[i]]
        used[i] = True
        for j in range(i + 1, len(points)):
            if used[j]:
                continue
            p1 = points[i] if isinstance(points[i], (list, tuple)) else [0, 0, 0]
            p2 = points[j] if isinstance(points[j], (list, tuple)) else [0, 0, 0]
            if len(p1) >= 3 and len(p2) >= 3:
                d = math.sqrt(
                    (float(p1[0]) - float(p2[0])) ** 2 +
                    (float(p1[1]) - float(p2[1])) ** 2 +
                    (float(p1[2]) - float(p2[2])) ** 2
                )
                if d < threshold:
                    cluster.append(points[j])
                    used[j] = True
        clusters.append(cluster)
    return clusters


def centroid(points):
    if not points:
        return (0, 0, 0)
    sx, sy, sz = 0, 0, 0
    for p in points:
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            sx += float(p[0])
            sy += float(p[1])
            sz += float(p[2])
    n = len(points)
    return (sx / n, sy / n, sz / n)


if __name__ == "__main__":
    main()
