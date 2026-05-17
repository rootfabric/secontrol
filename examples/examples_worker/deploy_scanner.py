"""Deploy and run voxel_scanner.py on the worker controller.

Usage:
    python deploy_scanner.py              # Upload + run on skynet-baza1
    python deploy_scanner.py --stop       # Stop running scanner
    python deploy_scanner.py --logs       # Show logs
"""

import argparse
import json
import sys
import time
import requests

BASE_URL = "https://www.outenemy.ru/se/worker-controller/instance/28f8784e-dbe4-5f5e-b294-c1c87df4b712"
GRID_ID = "118163643286714656"  # skynet-baza1
PROGRAM_NAME = "voxel_scanner"
SCANNER_FILE = "voxel_scanner.py"


def api(method, path, **kwargs):
    url = f"{BASE_URL}/api{path}"
    r = requests.request(method, url, timeout=30, **kwargs)
    if not r.ok:
        print(f"ERROR {r.status_code}: {r.text[:500]}")
        return None
    try:
        return r.json()
    except Exception:
        return r.text


def find_program(name):
    data = api("GET", "/programs")
    if not data or "items" not in data:
        return None
    for item in data["items"]:
        if item.get("name") == name:
            return item
    return None


def find_running():
    data = api("GET", "/programs/running")
    if not data or "items" not in data:
        return []
    return [
        item for item in data["items"]
        if item.get("name") == PROGRAM_NAME
    ]


def deploy():
    # Stop any existing instance
    running = find_running()
    for r in running:
        wid = r.get("worker_id") or r.get("uuid")
        print(f"Stopping existing program {wid}...")
        api("POST", f"/programs/{wid}/stop")
        time.sleep(2)

    # Find or create program
    prog = find_program(PROGRAM_NAME)
    if prog:
        wid = prog.get("worker_id") or prog.get("uuid")
        print(f"Found existing program: {wid}")
    else:
        print(f"Creating program '{PROGRAM_NAME}'...")
        result = api("POST", "/programs", json={"name": PROGRAM_NAME})
        if not result:
            print("Failed to create program")
            sys.exit(1)
        wid = result.get("worker_id") or result.get("uuid")
        print(f"Created program: {wid}")

    # Upload file
    print(f"Uploading {SCANNER_FILE}...")
    with open(SCANNER_FILE, "rb") as f:
        files = {"files": (SCANNER_FILE, f, "text/x-python")}
        result = api("POST", f"/programs/{wid}/files", files=files)
    if result is None:
        print("Upload failed")
        sys.exit(1)
    print("Upload OK")

    # List files to confirm
    files = api("GET", f"/programs/{wid}/files")
    print(f"Program files: {files}")

    # Run on skynet-baza1
    print(f"Starting on grid skynet-baza1 (id={GRID_ID})...")
    result = api("POST", f"/programs/{wid}/run", json={
        "filename": SCANNER_FILE,
        "grid_id": GRID_ID,
        "params": {"grid_id": "skynet-baza1"},
    })
    if result is None:
        print("Failed to start program")
        sys.exit(1)
    print(f"Started: {json.dumps(result, indent=2)}")

    # Wait and show logs
    print("\nWaiting 10s for startup...")
    time.sleep(10)
    show_logs(wid)


def show_logs(wid=None):
    if wid is None:
        running = find_running()
        if not running:
            print("No running voxel_scanner program found")
            return
        wid = running[0].get("worker_id") or running[0].get("uuid")

    result = api("GET", f"/programs/{wid}/logs", params={"tail_bytes": 5000})
    if result is None:
        return

    if isinstance(result, dict):
        print(f"=== Logs for {wid} ===")
        print(result.get("log", json.dumps(result, indent=2)))
    else:
        print(result)


def stop():
    running = find_running()
    if not running:
        print("No running voxel_scanner program found")
        return
    for r in running:
        wid = r.get("worker_id") or r.get("uuid")
        print(f"Stopping {wid}...")
        api("POST", f"/programs/{wid}/stop")
        print("Stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy voxel scanner to worker")
    parser.add_argument("--stop", action="store_true", help="Stop running scanner")
    parser.add_argument("--logs", action="store_true", help="Show logs")
    args = parser.parse_args()

    if args.stop:
        stop()
    elif args.logs:
        show_logs()
    else:
        deploy()
