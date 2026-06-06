# Nanobot mining v20 — real LeftRight axis fix

This patch fixes the case where the Python log reports `actual_center_error=0`,
but the visible Nanobot Drill area cube is mirrored into deep space after the
ship is turned or slightly repositioned.

Root cause:

- The old helper/plugin telemetry computed `area.center` with
  `WorldMatrix.Left * AreaOffsetLeftRight`.
- Live game tests showed the real Nanobot terminal X / LeftRight slider moves
  the visible cube along `WorldMatrix.Right`.
- Because the Python closed-loop trusted the helper `area.center`, it could be
  perfectly self-consistent while aiming the real cube to the wrong side.

Changes:

- `auto` axis mode now means `right-up-forward` for the real mod behavior.
- Normal mining no longer auto-calibrates axes from `area.center`.
- Normal mining no longer recovers the origin from `area.center` by default.
- Closed-loop correction against `area.center` is disabled by default.
- Sparse scan filtering from v19 is kept.
- GPS marker creation remains disabled by default.

Optional diagnostics:

```powershell
$env:NANODRILL_ENABLE_AREA_TELEMETRY_AUTOCALIBRATION = "1"
$env:NANODRILL_TRUST_REPORTED_AREA_CENTER_ORIGIN = "1"
$env:NANODRILL_AREA_CLOSED_LOOP = "1"
```

Do not enable these for normal mining unless the DedicatedPlugin telemetry is
updated to v20+ and reports `nanodrillAreaAxisMappingVersion=right_up_forward_v20_2026_06_06`.
