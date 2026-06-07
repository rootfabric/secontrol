from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)

from WorkerApi import WorkerApiClient


PROGRAM_UUID = "9c98a55443a94a7087f09d401ed67054"


def upload_raw(client: WorkerApiClient, name: str, content: bytes) -> bool:
    url = f"{client.api_url}/programs/{PROGRAM_UUID}/files"
    files = {"files": (name, content, "text/x-python")}
    try:
        r = client.session.post(url, files=files, timeout=120)
        print(f"  status={r.status_code} body[:200]={r.text[:200]!r}")
        return 200 <= r.status_code < 300
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return False


def main() -> None:
    client = WorkerApiClient()

    files_to_upload = [
        ("scout2_orbit_earth.py", Path("scout2_orbit_earth.py").read_bytes()),
        ("orbit_earth.py", Path("orbit_earth.py").read_bytes()),
    ]

    for name, content in files_to_upload:
        print(f"uploading {name} ({len(content)} bytes)")
        ok = upload_raw(client, name, content)
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
