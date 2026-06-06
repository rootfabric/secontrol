# Nanobot Drill mining v21: AreaOffset axis sign autodetect

This patch fixes the v20 regression where `AreaOffsetLeftRight` was inverted.
The visible Nanobot area could jump hundreds of meters into empty space even
though the log contained a mathematically correct `estimated_center`.

## What changed

- `auto` mapping is back to the observed safe default: `left-up-forward`.
- The script no longer uses `area.center` to recover a drifting RC-local origin.
- The script uses the current `area.center + current AreaOffset` only as an axis
  sign sanity check. This detects whether LR/UD/FB signs reproduce the current
  visible area from the live Nanobot origin before aiming at ore.
- If the sign check is ambiguous or stale, the script keeps the v21 default
  instead of silently switching to a bad axis.

Expected startup line:

```text
Nanobot effective area axis mode: auto -> left-up-forward, verified from current area telemetry when possible
```

Expected transform diagnostic when current offsets are non-zero:

```text
Auto axis calibration from current Nanobot area telemetry:
  #1: error=0.000m LR=left,UD=up,FB=forward ...
```

If you need to disable the sign sanity check for diagnostics:

```powershell
$env:NANODRILL_DISABLE_AREA_TELEMETRY_AUTOCALIBRATION = "1"
```
