from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from WorkerApi import WorkerApiClient


PROGRAM_UUID = "9c98a55443a94a7087f09d401ed67054"
FILES = [
    Path("scout2_orbit_earth.py"),
    Path("orbit_earth.py"),
]


def main() -> None:
    client = WorkerApiClient(max_retries=1, retry_delay=1.0, timeout=60.0)

    for f in FILES:
        if not f.exists():
            print(f"LOCAL MISSING: {f}")
            continue
        size = f.stat().st_size
        print(f"uploading {f} ({size} bytes)")
        ok = client.upload_files(PROGRAM_UUID, [str(f)])
        print(f"  -> ok={ok}")

    time.sleep(2)
    listing = client.list_program_files(PROGRAM_UUID) or []
    print()
    print("relevant files on worker:")
    for entry in listing:
        if "orbit" in entry.get("name", "") or "scout2" in entry.get("name", ""):
            print(f"  {entry}")


if __name__ == "__main__":
    main()
