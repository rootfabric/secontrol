# Flight failure anti-pattern

Do not report a flight hard-block from static telemetry only.

Warning signals, not hard blockers:

- `Remote Control enabled=false`;
- `Remote Control isFunctional=false`;
- `Remote Control isWorking=false`;
- `autopilotEnabled=false`;
- `player online=false`;
- `0 players online`;
- `Redis publish result = 1 subscriber`;
- generic `block_enable` did not update RC telemetry;
- thruster subtype looks atmospheric or unknown.

Before saying `grid cannot fly`, run safe diagnostics and guarded movement verification when possible.

Source of truth:

- position delta;
- speed delta;
- successful navigation output;
- actual return-to-start or arrival result.

Known correction: small-grid `SmallBlockSmallThrust` has moved a scout grid in the current environment. Do not reject a flight only by subtype memory.
