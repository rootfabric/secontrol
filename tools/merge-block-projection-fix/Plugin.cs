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
        private const string HarmonyId = "rootfabric.se.mergeblock-projection-fix.r2";
        private static readonly object LogLock = new object();

        private static Harmony _harmony;
        private static Type _mergeType;
        private static PropertyInfo _isWorkingProperty;
        private static PropertyInfo _slimBlockProperty;
        private static MethodInfo _getOtherMergeBlockMethod;
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
            public object SelfSlim;
            public object OtherSlim;
            public bool IsWorkingBefore;
            public int MatchedRefreshCalls;
        }

        public void Init(object gameInstance)
        {
            try
            {
                var assemblyDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)
                                  ?? AppDomain.CurrentDomain.BaseDirectory;
                _logPath = Path.Combine(assemblyDir, "MergeBlockProjectionFix.log");
                InitGameLogBridge();

                Log("Initializing R2 transition-gated neighbour refresh patch.");

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
                _slimBlockProperty = AccessTools.Property(_mergeType, "SlimBlock");
                _getOtherMergeBlockMethod = AccessTools.Method(_mergeType, "GetOtherMergeBlock");

                if (_isWorkingProperty == null ||
                    _isWorkingProperty.PropertyType != typeof(bool))
                {
                    Log("SAFE-DISABLE: IsWorking property was not found.");
                    return;
                }

                if (_slimBlockProperty == null)
                {
                    Log("SAFE-DISABLE: SlimBlock property was not found.");
                    return;
                }

                if (_getOtherMergeBlockMethod == null)
                {
                    Log("SAFE-DISABLE: GetOtherMergeBlock() was not found.");
                    return;
                }

                var originalInstructions = PatchProcessor
                    .GetOriginalInstructions(updateOnce)
                    .ToList();

                var neighbourRefreshCalls = originalInstructions
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
                    neighbourRefreshCalls.Count +
                    " direct UpdateBlockNeighbours call(s).");

                if (neighbourRefreshCalls.Count != 2)
                {
                    Log("SAFE-DISABLE: expected exactly 2 direct neighbour-refresh calls; current game code differs.");
                    return;
                }

                _neighbourRefreshMethods = neighbourRefreshCalls
                    .Distinct(MethodInfoComparer.Instance)
                    .ToArray();

                if (_neighbourRefreshMethods.Length == 0)
                {
                    Log("SAFE-DISABLE: no neighbour-refresh target method resolved.");
                    return;
                }

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

                    Log("Patched neighbour refresh target: " +
                        method.DeclaringType?.FullName + "." + method.Name +
                        "(" + string.Join(", ",
                            method.GetParameters()
                                  .Select(p => p.ParameterType.FullName)) + ")");
                }

                _patchApplied = true;
                Log("PATCH ACTIVE R2: Merge neighbour refresh runs only when IsWorking changes during UpdateOnceBeforeFrame.");
            }
            catch (Exception ex)
            {
                Log("SAFE-DISABLE due to initialization failure: " + ex);
            }
        }

        public void Update()
        {
            // No polling or per-frame mutation is required.
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
                var previous = _mergeUpdateContext;

                var context = new MergeUpdateContext
                {
                    Previous = previous,
                    Merge = __instance,
                    IsWorkingBefore = ReadIsWorking(__instance),
                    SelfSlim = _slimBlockProperty.GetValue(__instance, null)
                };

                var other = _getOtherMergeBlockMethod.Invoke(
                    __instance,
                    Array.Empty<object>());

                if (other != null)
                    context.OtherSlim = _slimBlockProperty.GetValue(other, null);

                _mergeUpdateContext = context;
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
                    if (context.MatchedRefreshCalls > 0)
                    {
                        var after = ReadIsWorking(context.Merge);
                        if (after != context.IsWorkingBefore)
                        {
                            LogOccasionally(
                                "IsWorking transition observed " +
                                context.IsWorkingBefore + " -> " + after +
                                "; vanilla neighbour refresh allowed.");
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

        private static bool UpdateBlockNeighboursPrefix(object[] __args)
        {
            try
            {
                var context = _mergeUpdateContext;

                // Never change normal MyCubeGrid neighbour updates. We only gate the
                // two calls made while MyShipMergeBlock.UpdateOnceBeforeFrame is active.
                if (context == null)
                {
                    Interlocked.Increment(ref _unrelatedRefreshCount);
                    return true;
                }

                if (__args == null || __args.Length < 1)
                    return true;

                var slim = __args[0];

                // Extra safety: only intercept the current merge block or the facing
                // merge block captured by GetOtherMergeBlock() at method entry.
                if (!ReferenceEquals(slim, context.SelfSlim) &&
                    !ReferenceEquals(slim, context.OtherSlim))
                {
                    Interlocked.Increment(ref _unrelatedRefreshCount);
                    return true;
                }

                context.MatchedRefreshCalls++;

                var isWorkingAfterUpdate = ReadIsWorking(context.Merge);

                if (isWorkingAfterUpdate == context.IsWorkingBefore)
                {
                    var count = Interlocked.Increment(ref _suppressedRefreshCount);

                    if (count <= 8 || count % 100 == 0)
                    {
                        Log(
                            "SUPPRESS neighbour refresh #" + count +
                            ": IsWorking stayed " +
                            context.IsWorkingBefore +
                            " during Merge UpdateOnceBeforeFrame.");
                    }

                    return false;
                }

                var allowed = Interlocked.Increment(
                    ref _allowedTransitionRefreshCount);

                if (allowed <= 8 || allowed % 100 == 0)
                {
                    Log(
                        "ALLOW neighbour refresh #" + allowed +
                        ": IsWorking changed " +
                        context.IsWorkingBefore + " -> " +
                        isWorkingAfterUpdate + ".");
                }

                return true;
            }
            catch (Exception ex)
            {
                RuntimeFailure("UpdateBlockNeighboursPrefix", ex);

                // Fail open: if the runtime shape is not what we expected,
                // execute vanilla code rather than risking stuck grid topology.
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

        private static void LogOccasionally(string message)
        {
            // The important per-call counters are already rate limited in the prefix.
            // This helper exists to keep transition diagnostics concise.
            Log(message);
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
                " [MergeBlockProjectionFix R2] " +
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
