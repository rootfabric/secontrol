# Рекомендуемый набор скриптов Nanobot Drill Automation Fix v12

> Index: `AGENTS.md` — Добыча ресурсов | Agent instructions: `nanodrill_agent.md`

Основной набор:

- `mine_ore_robot_safe_live_move.py` — основной универсальный добывающий скрипт.
- `mine_platinum_simple_v11_safe.py` — проверенный простой сценарий для Platinum.
- `scan_probe_mine_ore.py` — общий helper/fallback; нужен `mine_platinum_simple_v11_safe.py`.
- `configure_ore_only.py` — безопасная настройка фильтра Ore + выбранная руда без добычи.
- `stop_drill.py` — аварийная остановка.
- `set_nanodrill_area.py` — диагностика/расчет области, не использовать перед добывающим скриптом.
- `check_nanodrill_strict_patch.py` — диагностика активного patch/mod.
- `clear_until_platinum_visible.py`, `sweep_clear_until_ore_visible.py` — специальные сценарии вскрытия, не обычная добыча.
- `nanodrill_agent.md` — инструкция агенту.

Папка `deprecated/` содержит старые или опасные варианты. Агент не должен использовать их по умолчанию.

## Исправление ориентации Nanobot Drill

Добавлен общий helper `nanodrill_area_frame.py`. Все скрипты, которые двигают `Drill.AreaOffset*`, теперь считают смещения в локальной системе самого Nanobot-блока:

- `Drill.AreaOffsetLeftRight` считается по `Nanobot.WorldMatrix.Right`;
- `Drill.AreaOffsetUpDown` считается по `Nanobot.WorldMatrix.Up`;
- `Drill.AreaOffsetFrontBack` считается по `Nanobot.WorldMatrix.Backward`.

Это убирает старую ошибку, когда скрипты были заточены под один конкретный монтаж нанобура на гриде. Теперь Nanobot может стоять на корабле с другим поворотом, а зона сбора всё равно должна попадать в world target.

Для старого плагина без `position/orientation` в telemetry оставлен legacy fallback, но правильная работа ожидается с плагином, который отдаёт Nanobot block transform.

## Rotation-safe AreaOffset v2

For Nanobot AreaOffset calculations the scripts now require Nanobot transform telemetry from the DedicatedPlugin:

- `position`
- `orientation.forward/up/left/right`
- optionally `area.axis.frontBack/upDown/leftRight` and `area.center`

If this telemetry is missing, mining scripts stop instead of silently using the old fixed axis map. The old map is unsafe for ships where the Nanobot block is mounted with a different rotation.

For manual diagnostics only, legacy fallback can be enabled with:

```powershell
$env:NANODRILL_ALLOW_LEGACY_AREA_MAP = "1"
```

Do not use this fallback for automatic mining.

## v18 near-density selection fix

The normal mining script now uses `--min-point-density 6` by default and the `nearest` strategy applies the density tier before exact distance. This avoids a failure mode where a ship rotated 180 degrees selected a sparse density=2 detector cell a few meters closer than the real density=6 ore cluster.

GPS marker export and in-game GPS marker creation are disabled by default. Enable them only when debugging with `--scan-gps-markers` and `--scan-gps-create-ingame`.

## v19 sparse scan point filter

Mining now excludes scan cells below `--min-point-density` while any viable cells
exist. This prevents a barely-nearer `density=2` detector island from being tried
before the real nearby `density=6+` ore cluster. Real in-game GPS marker creation
is off by default; enable it only with `--scan-gps-markers --scan-gps-create-ingame`.

## v20: real Nanobot X/LeftRight axis fix

If the log shows `actual_center_error=0` but the visible cube is in deep space,
do not trust old `area.center` telemetry. v20 treats the real terminal axes as:

- `AreaOffsetLeftRight` / terminal X -> block/grid RIGHT axis
- `AreaOffsetUpDown` -> UP axis
- `AreaOffsetFrontBack` -> FORWARD axis

The default `--area-axis-mode auto` now resolves to `right-up-forward`. Axis
auto-calibration from `area.center`, origin recovery from `area.center`, and
closed-loop correction are disabled by default because older plugin telemetry
mirrors LeftRight.

## Nanobot Drill v22: FrontBack/Z sign fix

Live screenshots showed a miss proportional to `2 * abs(AreaOffsetFrontBack)`:
small FB values looked almost correct, while large FB values placed the visible
cube far into open space. This means the remaining sign error was on Z/FrontBack.

Default `auto` mapping is now:

- `AreaOffsetLeftRight` -> block/grid LEFT
- `AreaOffsetUpDown` -> block/grid UP
- `AreaOffsetFrontBack` -> block/grid BACKWARD

Do not enable `NANODRILL_ENABLE_AREA_TELEMETRY_AUTOCALIBRATION` during normal
mining. Older plugin telemetry can report a self-consistent `area.center` even
when the visible cube is mirrored on Z/FrontBack.
