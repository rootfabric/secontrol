# MergeBlockProjectionFix R3

Server-only experimental compatibility fix for the Space Engineers 1.210 projected Merge Block regression.

R2 did not activate on the tested 1.210.014 server because the runtime MyShipMergeBlock type did not expose the SlimBlock property via reflection. R3 removes that dependency completely.

R3 patch strategy:

1. Patch MyShipMergeBlock.UpdateOnceBeforeFrame().
2. Record IsWorking at method entry.
3. Identify the exact two direct UpdateBlockNeighbours() calls present in the current 1.210.014 method body.
4. Patch those target methods globally, but change behavior only while a MyShipMergeBlock.UpdateOnceBeforeFrame() is active on the current thread.
5. If IsWorking did not change, suppress the neighbour refresh.
6. If IsWorking changed, allow vanilla neighbour refresh.
7. Outside MyShipMergeBlock.UpdateOnceBeforeFrame(), all normal UpdateBlockNeighbours calls are untouched.

Expected startup log:

    [MergeBlockProjectionFix R3] Initializing R3 direct merge-update neighbour gate.
    [MergeBlockProjectionFix R3] Compatibility guard: UpdateOnceBeforeFrame contains 2 direct UpdateBlockNeighbours call(s).
    [MergeBlockProjectionFix R3] PATCH ACTIVE R3: direct UpdateBlockNeighbours calls are gated by MyShipMergeBlock IsWorking transition.

Expected welding diagnostics:

    SUPPRESS neighbour refresh ... Merge IsWorking stayed False ...

Expected real state transition:

    ALLOW neighbour refresh ... Merge IsWorking changed False -> True ...

Emergency disable:

    set SE_MERGE_PROJECTION_FIX_DISABLE=1

This is an experimental server-side compatibility patch, not an official Keen fix.
