# dock.py miss recovery update

This update improves the final docking phase.

## What changed

- Detects a missed final push early when the ship is near the connector and lateral error or angle starts growing.
- Stops pushing forward when the connector passes the target plane.
- Backs out to a stable point 14 m in front of the target connector.
- Uses the fixed target connector axis for recovery/backoff, not the dynamic ship-to-target vector that can flip after a miss.
- Re-aligns the ship connector and lets Phase 3 retry the approach.
- Keeps the existing physical port occupancy check.

## Install

Copy `dock.py` to the legacy path:

```powershell
Copy-Item .\dock.py C:\secontrol\examples\organized\parking\dock.py -Force
```

If you also use the new commands layout:

```powershell
Copy-Item .\dock.py C:\secontrol\commands\docking\dock.py -Force
```

## Run

```powershell
python examples/organized/parking/dock.py skynet-agent1 skynet-farpost0
```

## New behavior in logs

When the script sees a miss, you should see lines like:

```text
MISS RECOVERY: miss detected near connector: axial=2.78m, angle=11.9° > 10.0°
MISS RECOVERY: backing out to stable line 14.0m in front of target connector
MISS RECOVERY: ready for retry, axial=14.0m, lateral=..., angle=...
```
