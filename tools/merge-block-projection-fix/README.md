# MergeBlockProjectionFix R2

Server-only experimental compatibility fix for the Space Engineers 1.210 projected Merge Block regression.

## What changed from R1

R1 forced structural permission while a Merge Block was not yet functional. The observed server test showed that this was insufficient: the projected Merge Block could remain in place briefly, then lose structural attachment about a second later.

R2 instead patches the exact regression path described in the Keen bug report:

1. MyShipMergeBlock.UpdateOnceBeforeFrame() begins.
2. R2 records the Merge Block's IsWorking value.
3. Vanilla performs its state update.
4. Vanilla reaches the two new UpdateBlockNeighbours() calls.
5. If IsWorking did not actually change during this UpdateOnceBeforeFrame call, R2 suppresses those two neighbour refreshes.
6. If IsWorking really changed false->true or true->false, R2 allows the vanilla neighbour refresh.

This matches the proposed fix: refresh merge neighbours only after a real IsWorking transition rather than unconditionally.

Normal grid neighbour updates outside MyShipMergeBlock.UpdateOnceBeforeFrame are never changed.

## Why this should preserve normal release

- unfinished projected merge: false -> false, refresh suppressed, block remains structurally supported
- merge becomes working: false -> true, refresh allowed, normal merge logic runs
- later Merge Block is switched OFF: true -> false, refresh allowed, normal disconnect runs

## Files required

- MergeBlockProjectionFix.dll
- 0Harmony.dll

Clients do not need the plugin.

## Log verification

The plugin writes to:
- MergeBlockProjectionFix.log next to the DLL
- the main SpaceEngineersDedicated log when VRage.Utils.MyLog is available

Expected startup lines:

    [MergeBlockProjectionFix R2] Initializing R2 transition-gated neighbour refresh patch.
    [MergeBlockProjectionFix R2] Compatibility guard: UpdateOnceBeforeFrame contains 2 direct UpdateBlockNeighbours call(s).
    [MergeBlockProjectionFix R2] PATCH ACTIVE R2: Merge neighbour refresh runs only when IsWorking changes during UpdateOnceBeforeFrame.

During welding, expected lines include:

    SUPPRESS neighbour refresh ... IsWorking stayed False ...

When the block becomes genuinely working or is later disabled:

    ALLOW neighbour refresh ... IsWorking changed False -> True ...
    ALLOW neighbour refresh ... IsWorking changed True -> False ...

If the current game code no longer has exactly two direct UpdateBlockNeighbours calls, R2 safe-disables.

## Emergency disable

    set SE_MERGE_PROJECTION_FIX_DISABLE=1

This is an experimental server-side compatibility patch, not an official Keen fix.
