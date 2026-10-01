using System;

namespace VRage.Plugins
{
    // Compile-time reference surface only.
    // The DLL produced by this project is NEVER shipped with the plugin.
    // At runtime Space Engineers supplies its own VRage.dll containing this interface.
    public interface IPlugin : IDisposable
    {
        void Init(object gameInstance);
        void Update();
    }
}
