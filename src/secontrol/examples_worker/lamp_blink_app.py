"""Example: blinking lamps in App(start/step) format.

This example uses the App class with start/step methods and toggles
all lamps on the selected grid on each step call.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from secontrol.common import close, prepare_grid
from secontrol.base_device import Grid
from secontrol.devices.lamp_device import LampDevice


class App:
    def __init__(self):
        self.counter: int = 0
        self._client = None
        self._grid: Optional[Grid] = None
        self._lamps: List[LampDevice] = []
        self._on: bool = False

    def start(self):
        # Create Redis client and Grid, then collect all lamps
        self._client, self._grid = prepare_grid()

        # Prefer type-based search if available, otherwise isinstance fallback
        lamps = []
        try:
            lamps = list(self._grid.find_devices_by_type("lamp"))  # type: ignore[attr-defined]
        except Exception:
            pass
        if not lamps:
            lamps = [d for d in self._grid.devices.values() if isinstance(d, LampDevice)]  # type: ignore[union-attr]

        self._lamps = lamps
        print(f"Started! Lamps found: {len(self._lamps)}")

    def step(self):
        self.counter += 1
        # Toggle state each step and apply to all lamps
        self._on = not self._on
        for lamp in self._lamps:
            try:
                lamp.set_enabled(self._on)
            except Exception:
                # Ignore individual device errors to keep stepping
                pass
        state = "ON" if self._on else "OFF"
        print(f"Step {self.counter}: lamps -> {state}")

    # Optional: allow external cleanup
    def close(self):
        if self._client and self._grid:
            try:
                close(self._client, self._grid)
            except Exception:
                pass


if __name__ == "__main__":
    app = App()
    app.start()
    # Simple demo: perform a few steps
    for _ in range(6):
        app.step()
    app.close()

