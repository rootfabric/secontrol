"""Worker program: voxel scanner for skynet-baza1.

Scans surrounding space for voxels once per minute using the ore detector radar.
Uses raw OreDetectorDevice.scan() directly for maximum compatibility.
"""

import datetime
import time

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice


SCAN_INTERVAL = 60  # seconds between scans


class App:
    def __init__(self, params):
        grid_id = params.get("grid_id", "skynet-baza1")
        self.grid = prepare_grid(grid_id)
        self.counter = 0
        self.last_scan_time = 0.0

        # Find ore detector
        detectors = self.grid.find_devices_by_type(OreDetectorDevice)
        if not detectors:
            print("[scanner] ERROR: No ore detector found on grid!")
            self.radar = None
            return

        self.radar = detectors[0]
        print(f"[scanner] Found radar: {self.radar.name} (id={self.radar.device_id})")

    def start(self):
        print(f"[scanner] Started on grid '{self.grid.name}' (id={self.grid.grid_id})")
        print(f"[scanner] Scan interval: {SCAN_INTERVAL}s")
        self.last_scan_time = 0.0

    def _do_scan(self):
        if self.radar is None:
            print("[scanner] No radar available")
            return

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[scanner] === Scan at {ts} ===")

        try:
            # Send voxel scan command
            seq = self.radar.scan(
                include_players=True,
                include_grids=True,
                include_voxels=True,
                radius=300,
                cell_size=2,
                voxel_step=2,
                boundingBoxX=500,
                boundingBoxY=500,
                boundingBoxZ=500,
            )
            print(f"[scanner] Scan sent, seq={seq}")

            # Wait for radar data (up to 90s)
            deadline = time.time() + 90
            last_rev = self.radar.revision()
            while time.time() < deadline:
                self.radar.update()
                time.sleep(1.0)
                new_rev = self.radar.revision()
                if new_rev is not None and new_rev != last_rev:
                    print(f"[scanner] Radar revision changed: {last_rev} -> {new_rev}")
                    break
            else:
                print("[scanner] Timeout waiting for radar update")

            # Get results
            snapshot = self.radar.radar_snapshot()
            if not snapshot:
                print("[scanner] No radar snapshot available")
                return

            contacts = snapshot.get("contacts", [])
            ore_cells = snapshot.get("oreCells", [])
            raw = snapshot.get("raw", {})
            solid_points = raw.get("solidPoints", [])
            size = raw.get("size", "?")
            origin = raw.get("origin", "?")
            cell_size = raw.get("cellSize", "?")
            rev = raw.get("rev", "?")

            grids = [c for c in contacts if isinstance(c, dict) and c.get("type") == "grid"]
            players = [c for c in contacts if isinstance(c, dict) and c.get("type") == "player"]

            print(f"[scanner] Rev: {rev}, Grid size: {size}, Origin: {origin}, Cell: {cell_size}")
            print(f"[scanner] Solid voxels: {len(solid_points)}")
            print(f"[scanner] Contacts: {len(contacts)} (grids={len(grids)}, players={len(players)})")
            print(f"[scanner] Ore cells: {len(ore_cells)}")

            if grids:
                print("[scanner] Nearby grids:")
                for g in grids:
                    name = g.get("name", "?")
                    pos = g.get("position", "?")
                    dist = g.get("distance", "?")
                    print(f"  - {name} dist={dist} pos={pos}")

            if players:
                print("[scanner] Nearby players:")
                for p in players:
                    name = p.get("name", "?")
                    pos = p.get("position", "?")
                    dist = p.get("distance", "?")
                    print(f"  - {name} dist={dist} pos={pos}")

            if ore_cells:
                print("[scanner] Ore hits:")
                for cell in ore_cells[:10]:
                    material = cell.get("material") or cell.get("ore") or "?"
                    content = cell.get("content", "N/A")
                    position = cell.get("position", "N/A")
                    print(f"  - {material}: content={content}, pos={position}")
                if len(ore_cells) > 10:
                    print(f"  ... and {len(ore_cells) - 10} more")

            print(f"[scanner] Scan complete")

        except Exception as e:
            print(f"[scanner] Scan failed: {e}")
            import traceback
            traceback.print_exc()

    def step(self):
        now = time.time()
        if now - self.last_scan_time < SCAN_INTERVAL:
            return
        self.last_scan_time = now
        self.counter += 1
        self._do_scan()


if __name__ == "__main__":
    app = App({"grid_id": "skynet-baza1"})
    app.start()
    try:
        while True:
            app.step()
            time.sleep(1)
    except KeyboardInterrupt:
        print("[scanner] Stopped by user")
