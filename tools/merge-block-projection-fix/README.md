# MergeBlockProjectionFix R1

Server-only experimental compatibility fix for the Space Engineers 1.210 projected Merge Block regression.

Basis

The plugin uses the vanilla VRage.Plugins.IPlugin entry point and Harmony runtime patching pattern used by established Space Engineers plugin projects. It is intentionally narrow:

- It first checks that MyShipMergeBlock.UpdateOnceBeforeFrame() still contains at least two calls named UpdateBlockNeighbours, the regression signature reported for 1.210.
- If that signature is absent, the plugin safe-disables and does not patch the game.
- If present, it patches private ConnectionAllowedInternal().
- Only when the Merge Block reports IsFunctional == false does the prefix return true for structural connectivity.
- As soon as the block is functional, all vanilla Merge Block connection rules run unchanged.
- A fully built but OFF or unpowered Merge Block is therefore not globally forced to remain connected.

This is a test fix, not an official Keen patch.

Files required on the server

Keep these next to each other:

- MergeBlockProjectionFix.dll
- 0Harmony.dll

Clients do not need either file.

Vanilla Dedicated Server test

    SpaceEngineersDedicated.exe -console -plugin "C:\SEPlugins\MergeBlockProjectionFix\MergeBlockProjectionFix.dll"

Verify

After startup inspect MergeBlockProjectionFix.log.

Expected:

    Compatibility guard: UpdateOnceBeforeFrame contains 2 UpdateBlockNeighbours call(s).
    PATCH ACTIVE: non-functional Merge Blocks keep structural connectivity while welding.

Then test a minimal Survival setup:

1. Existing fully built Merge Block ON.
2. Project another grid with its Merge Block directly face-to-face.
3. Weld with a ship welder at normal speed.
4. The unfinished projected Merge Block should remain structurally attached instead of becoming a loose grid.
5. Finish welding and verify the two Merge Blocks lock normally.
6. Turn a fully built Merge Block OFF and verify normal vanilla disconnect behaviour still occurs.

If the log says SAFE-DISABLE, do not force the patch. Save the log plus the current server build number for a revised build.

Emergency disable

    set SE_MERGE_PROJECTION_FIX_DISABLE=1

The DLL will load but leave all game methods untouched.
