using System;
using System.Collections.Generic;
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
        private const string HarmonyId = "rootfabric.se.mergeblock-projection-fix.r4";
        private static readonly object LogLock = new object();

        private static Harmony _harmony;
        private static Type _mergeType;
        private static PropertyInfo _isWorkingProperty;
        private static MethodInfo[] _neighbourRefreshMethods;
        private static string _logPath;
        private static bool _patchApplied;

        private static long _suppressedRefreshCount;
        private static long _allowedTransitionRefreshCount;
        private static long _unrelatedRefreshCount;
        private static int _runtimeFailureLogged;

        private static object _myLogDefault;
        private static MethodInfo _myLogWriteLineAndConsole;

        [ThreadStatic]
        private static MergeUpdateContext _mergeUpdateContext;

        private sealed class MergeUpdateContext
        {
            public MergeUpdateContext Previous;
            public object Merge;
            public bool IsWorkingBefore;
            public int InterceptedRefreshCalls;
        }

        public void Init(object gameInstance)
        {
            try
            {
                var assemblyDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)
                                  ?? AppDomain.CurrentDomain.BaseDirectory;
                _logPath = Path.Combine(assemblyDir, "MergeBlockProjectionFix.log");
                InitGameLogBridge();

                Log("Initializing R4 runtime-signature merge-update neighbour gate.");

                if (string.Equals(
                        Environment.GetEnvironmentVariable("SE_MERGE_PROJECTION_FIX_DISABLE"),
                        "1",
                        StringComparison.Ordinal))
                {
                    Log("Disabled by SE_MERGE_PROJECTION_FIX_DISABLE=1.");
                    return;
                }

                _mergeType = AccessTools.TypeByName(
                    "SpaceEngineers.Game.Entities.Blocks.MyShipMergeBlock");

                if (_mergeType == null)
                {
                    Log("SAFE-DISABLE: MyShipMergeBlock type was not found.");
                    return;
                }

                var updateOnce = AccessTools.Method(_mergeType, "UpdateOnceBeforeFrame");
                if (updateOnce == null)
                {
                    Log("SAFE-DISABLE: MyShipMergeBlock.UpdateOnceBeforeFrame() was not found.");
                    return;
                }

                _isWorkingProperty = AccessTools.Property(_mergeType, "IsWorking");
                if (_isWorkingProperty == null ||
                    _isWorkingProperty.PropertyType != typeof(bool))
                {
                    Log("SAFE-DISABLE: IsWorking property was not found.");
                    return;
                }

                var originalInstructions = PatchProcessor
                    .GetOriginalInstructions(updateOnce)
                    .ToList();

                var directCalls = originalInstructions
                    .Where(i =>
                    {
                        var method = i.operand as MethodInfo;
                        return method != null &&
                               string.Equals(
                                   method.Name,
                                   "UpdateBlockNeighbours",
                                   StringComparison.Ordinal);
                    })
                    .Select(i => (MethodInfo)i.operand)
                    .ToList();

                Log("Compatibility guard: UpdateOnceBeforeFrame contains " +
                    directCalls.Count +
                    " direct UpdateBlockNeighbours call(s).");

                if (directCalls.Count < 1 || directCalls.Count > 2)
                {
                    Log("SAFE-DISABLE: expected 1 or 2 direct UpdateBlockNeighbours calls; current game code differs.");
                    return;
                }

                _neighbourRefreshMethods = directCalls
                    .Distinct(MethodInfoComparer.Instance)
                    .ToArray();

                var updatePrefix = AccessTools.Method(
                    typeof(Plugin),
                    nameof(MergeUpdatePrefix));

                var updateFinalizer = AccessTools.Method(
                    typeof(Plugin),
                    nameof(MergeUpdateFinalizer));

                var neighbourPrefix = AccessTools.Method(
                    typeof(Plugin),
                    nameof(UpdateBlockNeighboursPrefix));

                _harmony = new Harmony(HarmonyId);

                _harmony.Patch(
                    updateOnce,
                    prefix: new HarmonyMethod(updatePrefix),
                    finalizer: new HarmonyMethod(updateFinalizer));

                foreach (var method in _neighbourRefreshMethods)
                {
                    _harmony.Patch(
                        method,
                        prefix: new HarmonyMethod(neighbourPrefix));

                    Log("Patched target: " +
                        method.DeclaringType?.FullName + "." +
                        method.Name + "(" +
                        string.Join(", ",
                            method.GetParameters()
                                  .Select(p => p.ParameterType.FullName)) +
                        ")");
                }

                _patchApplied = true;
                Log("PATCH ACTIVE R4: " + directCalls.Count + " direct UpdateBlockNeighbours call(s) gated by MyShipMergeBlock IsWorking transition.");
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
                Log(
                    "Dispose. PatchApplied=" + _patchApplied +
                    ", suppressedRefreshes=" +
                    Interlocked.Read(ref _suppressedRefreshCount) +
                    ", allowedTransitionRefreshes=" +
                    Interlocked.Read(ref _allowedTransitionRefreshCount) +
                    ", unrelatedRefreshes=" +
                    Interlocked.Read(ref _unrelatedRefreshCount) + ".");
            }
            catch
            {
            }
        }

        private static void MergeUpdatePrefix(object __instance)
        {
            try
            {
                _mergeUpdateContext = new MergeUpdateContext
                {
                    Previous = _mergeUpdateContext,
                    Merge = __instance,
                    IsWorkingBefore = ReadIsWorking(__instance),
                    InterceptedRefreshCalls = 0
                };
            }
            catch (Exception ex)
            {
                RuntimeFailure("MergeUpdatePrefix", ex);
            }
        }

        private static Exception MergeUpdateFinalizer(Exception __exception)
        {
            try
            {
                var context = _mergeUpdateContext;
                if (context != null)
                {
                    if (context.InterceptedRefreshCalls > 0)
                    {
                        var after = ReadIsWorking(context.Merge);

                        if (after != context.IsWorkingBefore)
                        {
                            Log(
                                "Merge update completed with IsWorking transition " +
                                context.IsWorkingBefore + " -> " + after +
                                ", intercepted calls=" +
                                context.InterceptedRefreshCalls + ".");
                        }
                    }

                    _mergeUpdateContext = context.Previous;
                }
            }
            catch (Exception ex)
            {
                RuntimeFailure("MergeUpdateFinalizer", ex);
                _mergeUpdateContext = null;
            }

            return __exception;
        }

        private static bool UpdateBlockNeighboursPrefix()
        {
            try
            {
                var context = _mergeUpdateContext;

                // Critical safety boundary:
                // Outside MyShipMergeBlock.UpdateOnceBeforeFrame, never alter grid topology updates.
                if (context == null)
                {
                    Interlocked.Increment(ref _unrelatedRefreshCount);
                    return true;
                }

                context.InterceptedRefreshCalls++;

                var isWorkingNow = ReadIsWorking(context.Merge);

                // Regression path: the 1.210 code refreshes neighbours even though
                // MyShipMergeBlock did not actually change working state.
                if (isWorkingNow == context.IsWorkingBefore)
                {
                    var count = Interlocked.Increment(ref _suppressedRefreshCount);

                    if (count <= 12 || count % 100 == 0)
                    {
                        Log(
                            "SUPPRESS neighbour refresh #" + count +
                            ": Merge IsWorking stayed " +
                            isWorkingNow +
                            " inside UpdateOnceBeforeFrame; callIndex=" +
                            context.InterceptedRefreshCalls + ".");
                    }

                    return false;
                }

                var allowed = Interlocked.Increment(
                    ref _allowedTransitionRefreshCount);

                if (allowed <= 12 || allowed % 100 == 0)
                {
                    Log(
                        "ALLOW neighbour refresh #" + allowed +
                        ": Merge IsWorking changed " +
                        context.IsWorkingBefore + " -> " +
                        isWorkingNow +
                        "; callIndex=" +
                        context.InterceptedRefreshCalls + ".");
                }

                return true;
            }
            catch (Exception ex)
            {
                RuntimeFailure("UpdateBlockNeighboursPrefix", ex);

                // Fail open. Never block vanilla topology work if our reflection state fails.
                return true;
            }
        }

        private static bool ReadIsWorking(object merge)
        {
            return (bool)_isWorkingProperty.GetValue(merge, null);
        }

        private static void RuntimeFailure(string where, Exception ex)
        {
            if (Interlocked.Exchange(ref _runtimeFailureLogged, 1) == 0)
            {
                Log(
                    "RUNTIME PATCH ERROR at " + where +
                    "; falling back to vanilla where possible: " + ex);
            }
        }

        private static void InitGameLogBridge()
        {
            try
            {
                var myLogType = AccessTools.TypeByName("VRage.Utils.MyLog");
                if (myLogType == null)
                    return;

                var defaultProperty = AccessTools.Property(myLogType, "Default");
                if (defaultProperty == null)
                    return;

                _myLogDefault = defaultProperty.GetValue(null, null);
                _myLogWriteLineAndConsole = AccessTools.Method(
                    myLogType,
                    "WriteLineAndConsole",
                    new[] { typeof(string) });
            }
            catch
            {
                _myLogDefault = null;
                _myLogWriteLineAndConsole = null;
            }
        }

        private static void Log(string message)
        {
            var line =
                DateTime.UtcNow.ToString("O") +
                " [MergeBlockProjectionFix R4] " +
                message;

            try
            {
                Trace.WriteLine(line);
            }
            catch
            {
            }

            try
            {
                if (_myLogDefault != null &&
                    _myLogWriteLineAndConsole != null)
                {
                    _myLogWriteLineAndConsole.Invoke(
                        _myLogDefault,
                        new object[] { line });
                }
            }
            catch
            {
            }

            try
            {
                lock (LogLock)
                {
                    if (!string.IsNullOrEmpty(_logPath))
                    {
                        File.AppendAllText(
                            _logPath,
                            line + Environment.NewLine);
                    }
                }
            }
            catch
            {
            }
        }

        private sealed class MethodInfoComparer : IEqualityComparer<MethodInfo>
        {
            public static readonly MethodInfoComparer Instance =
                new MethodInfoComparer();

            public bool Equals(MethodInfo x, MethodInfo y)
            {
                if (ReferenceEquals(x, y))
                    return true;

                if (x == null || y == null)
                    return false;

                return x.Module == y.Module &&
                       x.MetadataToken == y.MetadataToken;
            }

            public int GetHashCode(MethodInfo obj)
            {
                unchecked
                {
                    return (obj.Module.GetHashCode() * 397) ^
                           obj.MetadataToken;
                }
            }
        }
    }
}
