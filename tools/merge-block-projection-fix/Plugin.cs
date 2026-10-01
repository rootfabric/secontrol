using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using HarmonyLib;
using VRage.Plugins;

namespace MergeBlockProjectionFix
{
    public sealed class Plugin : IPlugin
    {
        private const string HarmonyId = "rootfabric.se.mergeblock-projection-fix.r1";
        private static readonly object LogLock = new object();

        private static Harmony _harmony;
        private static PropertyInfo _isFunctionalProperty;
        private static string _logPath;
        private static long _bypassCount;
        private static int _prefixFailureLogged;
        private static bool _patchApplied;

        public void Init(object gameInstance)
        {
            try
            {
                var assemblyDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)
                                  ?? AppDomain.CurrentDomain.BaseDirectory;
                _logPath = Path.Combine(assemblyDir, "MergeBlockProjectionFix.log");

                Log("Initializing R1.");

                if (string.Equals(
                        Environment.GetEnvironmentVariable("SE_MERGE_PROJECTION_FIX_DISABLE"),
                        "1",
                        StringComparison.Ordinal))
                {
                    Log("Disabled by SE_MERGE_PROJECTION_FIX_DISABLE=1.");
                    return;
                }

                var mergeType = AccessTools.TypeByName(
                    "SpaceEngineers.Game.Entities.Blocks.MyShipMergeBlock");

                if (mergeType == null)
                {
                    Log("SAFE-DISABLE: MyShipMergeBlock type was not found.");
                    return;
                }

                var updateOnce = AccessTools.Method(mergeType, "UpdateOnceBeforeFrame");
                if (updateOnce == null)
                {
                    Log("SAFE-DISABLE: UpdateOnceBeforeFrame() was not found.");
                    return;
                }

                var neighbourRefreshCalls = PatchProcessor
                    .GetOriginalInstructions(updateOnce)
                    .Count(i =>
                    {
                        var method = i.operand as MethodBase;
                        return method != null &&
                               string.Equals(
                                   method.Name,
                                   "UpdateBlockNeighbours",
                                   StringComparison.Ordinal);
                    });

                Log("Compatibility guard: UpdateOnceBeforeFrame contains " +
                    neighbourRefreshCalls + " UpdateBlockNeighbours call(s).");

                if (neighbourRefreshCalls < 2)
                {
                    Log("SAFE-DISABLE: regression signature is absent; game may already be fixed.");
                    return;
                }

                var connectionAllowed = AccessTools.Method(
                    mergeType,
                    "ConnectionAllowedInternal");

                if (connectionAllowed == null ||
                    connectionAllowed.ReturnType != typeof(bool))
                {
                    Log("SAFE-DISABLE: ConnectionAllowedInternal() signature was not found.");
                    return;
                }

                _isFunctionalProperty = AccessTools.Property(mergeType, "IsFunctional");
                if (_isFunctionalProperty == null ||
                    _isFunctionalProperty.PropertyType != typeof(bool))
                {
                    Log("SAFE-DISABLE: IsFunctional property was not found.");
                    return;
                }

                var prefix = AccessTools.Method(
                    typeof(Plugin),
                    nameof(ConnectionAllowedInternalPrefix));

                _harmony = new Harmony(HarmonyId);
                _harmony.Patch(
                    connectionAllowed,
                    prefix: new HarmonyMethod(prefix));

                _patchApplied = true;
                Log("PATCH ACTIVE: non-functional Merge Blocks keep structural connectivity while welding.");
            }
            catch (Exception ex)
            {
                Log("SAFE-DISABLE due to initialization failure: " + ex);
            }
        }

        public void Update()
        {
        }

        public void Dispose()
        {
            try
            {
                Log("Dispose. PatchApplied=" + _patchApplied +
                    ", bypassed non-functional checks=" +
                    Interlocked.Read(ref _bypassCount) + ".");
            }
            catch
            {
            }
        }

        private static bool ConnectionAllowedInternalPrefix(
            object __instance,
            ref bool __result)
        {
            try
            {
                var functional = (bool)_isFunctionalProperty.GetValue(__instance, null);
                if (!functional)
                {
                    __result = true;
                    Interlocked.Increment(ref _bypassCount);
                    return false;
                }
            }
            catch (Exception ex)
            {
                if (Interlocked.Exchange(ref _prefixFailureLogged, 1) == 0)
                    Log("Prefix read failed; falling back to vanilla: " + ex);
            }

            return true;
        }

        private static void Log(string message)
        {
            var line = DateTime.UtcNow.ToString("O") +
                       " [MergeBlockProjectionFix] " + message;

            try
            {
                Trace.WriteLine(line);
            }
            catch
            {
            }

            try
            {
                lock (LogLock)
                {
                    if (!string.IsNullOrEmpty(_logPath))
                        File.AppendAllText(_logPath, line + Environment.NewLine);
                }
            }
            catch
            {
            }
        }
    }
}
