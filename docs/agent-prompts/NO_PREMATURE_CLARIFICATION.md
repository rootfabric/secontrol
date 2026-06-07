# No premature clarification stop

When operating `secontrol`, do not replace safe read-only diagnostics with clarification questions.

If a user request is ambiguous, first run safe diagnostics that can reduce ambiguity:

- grid report;
- docking status;
- cargo/inventory status;
- device/block availability;
- script `--help`;
- SharedMap report;
- flight readiness report;
- repository playbook/mission lookup.

Ask only after diagnostics, and ask one concrete question.

For mining requests, never start destructive mining immediately when ship/base/amount are ambiguous. But always inspect candidate grids first.

For flight requests, never report `grid cannot fly` based only on `enabled=false`, `isFunctional=false`, `online=false`, `1 subscriber`, or thruster subtype. Run guarded flight diagnostics when safe.

Bad:

```text
I will not run anything and will ask which ship/base to use.
```

Good:

```text
I will first inspect agent/rover status, cargo capacity, Nanobot Drill availability, docking state, and script support. Then I will ask only the missing decision if needed.
```
