# Nanobot Drill v22 — FrontBack/Z sign fix

## Problem confirmed by live logs

v21 fixed the large LeftRight/X mirror, but the visible cube still missed when
FrontBack/Z was large. The miss scaled as approximately `2 * abs(FB)`:

- `FB=-37.9` => visual miss around 75 m, cube still looked close to the asteroid.
- `FB=-194` => visual miss around 388 m, cube moved far into open space.

That pattern means the remaining axis sign is mirrored on FrontBack/Z.
The old plugin `area.center` could still report `actual_center_error < 1m`,
because that helper used the same wrong Forward sign internally. It was
self-consistent, but it did not match the visible Nanobot area.

## Fix

Default Python mapping for `NANODRILL_AREA_AXIS_MODE=auto` is now:

```text
AreaOffsetLeftRight  -> block/grid LEFT
AreaOffsetUpDown     -> block/grid UP
AreaOffsetFrontBack  -> block/grid BACKWARD
```

The script prints:

```text
Nanobot effective area axis mode: auto -> left-up-backward (X/LR=left, Y/UD=up, Z/FB=backward)
```

`area.center` auto-calibration is no longer enabled by default in ship-local
mode, because old telemetry can re-select the wrong FrontBack sign.

## Optional DedicatedPlugin telemetry update

The plugin telemetry helper is updated to report `area.center` and
`area.axis.frontBack` using `WorldMatrix.Backward`, so debug telemetry should
match the visible cube after rebuilding the plugin.

Marker:

```text
nanodrillTransformTelemetryVersion=dynamic_area_axes_v22_2026_06_06_fb_backward
```

## Diagnostic override

Only for experiments:

```powershell
$env:NANODRILL_AREA_AXIS_MODE = "left-up-forward"
$env:NANODRILL_ENABLE_AREA_TELEMETRY_AUTOCALIBRATION = "1"
```

For normal mining, leave both unset.
