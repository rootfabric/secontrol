from __future__ import annotations

from pathlib import Path
import time

from WorkerApi import WorkerApiClient


PROGRAM_NAME = "scout2_orbit_earth"
PROGRAM_FILE = "scout2_orbit_earth.py"
TARGET_GRID = "skynet-scout2"

RUN_PARAMS = {
    "grid": TARGET_GRID,
    "center_distance_km": 90,
    "marker_step_km": 5,
}


def find_program_uuid(client: WorkerApiClient, program_name: str) -> str | None:
    programs = client.get_programs()
    if not programs:
        return None

    for item in programs.get("items", []) or []:
        if item.get("name") == program_name:
            return item.get("uuid") or item.get("id") or item.get("worker_id")

    return None


def main() -> None:
    if not Path(PROGRAM_FILE).exists():
        raise FileNotFoundError(f"Program file not found: {PROGRAM_FILE}")

    client = WorkerApiClient()

    program_uuid = find_program_uuid(client, PROGRAM_NAME)
    if not program_uuid:
        created = client.create_program(PROGRAM_NAME)
        if not created:
            raise RuntimeError("Failed to create worker program")
        program_uuid = created.get("uuid") or created.get("id") or created.get("worker_id")

    if not program_uuid:
        raise RuntimeError("Failed to resolve worker program UUID")

    print(f"Program: {PROGRAM_NAME}")
    print(f"UUID:    {program_uuid}")

    uploaded = client.upload_files(program_uuid, [PROGRAM_FILE])
    if not uploaded:
        raise RuntimeError("Failed to upload program file")

    run_info = client.run_program(
        program_uuid=program_uuid,
        filename=PROGRAM_FILE,
        grid_id=TARGET_GRID,
        params=RUN_PARAMS,
    )
    if not run_info:
        raise RuntimeError("Failed to start program")

    print("Started:", run_info)

    time.sleep(5)

    logs = client.get_program_logs(program_uuid, tail_bytes=12000)
    print("\n=== Logs ===")
    print(logs or "")


if __name__ == "__main__":
    main()
