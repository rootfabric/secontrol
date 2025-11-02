"""Examples of interacting with AI offensive/defensive task blocks."""

from __future__ import annotations

from secontrol.common import prepare_grid

TARGET_POINT = (50.0, 0.0, 50.0)


def main() -> None:
    grid = prepare_grid()
    task_devices = grid.find_devices_by_type("ai_offensive") or grid.find_devices_by_type(
        "ai_defensive"
    )
    if not task_devices:
        print("No AI task blocks found on grid", grid.name)
        return

    device = task_devices[0]
    print(f"Using AI task block: {device.name or device.device_id}")

    device.clear_target()
    device.set_target(position=TARGET_POINT)
    device.set_mode("Patrol")
    print("Target position assigned and mode set to Patrol.")


if __name__ == "__main__":
    main()
