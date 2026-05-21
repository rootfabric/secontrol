# Docking System — Maintenance & Validation

## Summary

Automated docking for SE grids: ship flies to approach point, rotates connector to face target,
approaches along connector axis, auto-locks when in range.

## Reality snapshot (2026-05-18)

### Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| Combined script | `se-data/scripts/docking/dock.py` | ✅ production |
| Phase 1+2 script | `se-data/scripts/docking/01_approach_point.py` | ✅ working |
| Phase 3 script | `se-data/scripts/docking/03_connector_approach.py` | ✅ working |
| Skill | `~/.hermes/skills/gaming/se-docking/SKILL.md` | ✅ created |

### Known grid IDs

| Grid | ID | Notes |
|------|----|-------|
| skynet-baza2 | 104571351454649539 | Ship to dock |
| Static Grid 6422 (ex skynet-farpost0) | 84360909276756422 | Target base |
| skynet-baza0 | 137791301601271852 | Other base |

### Runtime requirements

- Python 3.10+, secontrol pip-installed
- `.env` at `/workspace/.env` with `REDIS_USERNAME`, `REDIS_PASSWORD`, `REDIS_URL`
- Both grids must be online (gridinfo key non-empty in Redis)
- Ship needs: RemoteControlDevice, ConnectorDevice, ≥1 GyroDevice
- Target needs: ≥1 ConnectorDevice

## Validation scorecard

| Dimension | Score | Evidence |
|-----------|-------|----------|
| Entry point quality | 4/5 | Skill has usage, examples, pitfalls. `dock.py --help` embedded in docstring. |
| Knowledge store | 3/5 | Skill exists; no ARCHITECTURE.md or workflow index yet. |
| Plans as artifacts | 3/5 | Iterative development log exists in session memory; no formal exec plan doc. |
| Mechanical enforcement | 2/5 | No CI, no lint, no automated tests for docking scripts. |
| Drift control | 3/5 | Skill maintained manually; grid IDs in memory and doc may drift. |

## Design decisions

### D1: Connector-centric movement, not ship-centric

The connector can be 7-8m from the ship center. `rc.goto()` moves the ship center.
Solution: compute `ship_target = connector_target - offset` where offset = `ship_center → connector` in world space.

**Trade-off**: offset changes slightly as ship rotates. Acceptable for 2.5m precision.

### D2: atan2-based gyro P-controller (not projection difference)

Original: `pitch_err = dot(desired, ship_up) - dot(conn_fwd, ship_up)` — oscillated at large angles.
Fixed: `atan2(component, forward_component)` for both pitch and yaw — stable at all angles.

**Validated**: 104° rotation in 6s, no overshoot.

### D3: Three-phase speed ramp

| Phase | Distance | Step | Speed |
|-------|----------|------|-------|
| FAST | >20m | 15m | 3 m/s |
| SLOW | 5-20m | 5m | 1 m/s |
| CREEP | <5m | 1m | 0.5 m/s |

### D4: connectorIsConnected for lock detection

Connector telemetry exposes:
- `connectorIsConnected: bool` — ground truth for lock
- `connectorStatus: str` — "Connectable" when in range
- `otherConnectorId: int` — partner connector ID

Script calls `connect()` when status is "Connectable", checks `connectorIsConnected` after 2s.

### E5: Gyros stay enabled after docking

Never `g.disable()` post-dock — only `g.clear_override()`. Player needs gyros for manual control.

## Known issues / tech debt

| Issue | Severity | Action |
|-------|----------|--------|
| Stuck at ~2.5m via RC goto | Low | Mitigated: auto-connect when status=Connectable |
| Grid ID drift (renames change ID) | Medium | Script accepts IDs as args; skill docs list current IDs |
| No CI/tests for docking scripts | Medium | Add smoke test: mock secontrol, verify phase flow |
| .env \r\n parsing | Low | Manual load in each script; consider dotenv in secontrol |
| Offset changes with rotation | Low | Accept 2.5m precision; could cache offset at phase 2 end |

## Remediation priorities

1. **Add `--dry-run` flag** — compute all waypoints without moving, validate positions
2. **Parametric skill** — skill should query active grid IDs from Redis at runtime, not hardcode
3. **CI smoke test** — import dock.py, mock prepare_grid, verify function calls
4. **Document connector telemetry fields** in secontrol API reference
