from __future__ import annotations

from typing import Any, Dict

from secontrol.common import prepare_grid


class App:
    def __init__(self, params: Dict[str, Any]):
        self.params = params
        self.grid_id = str(params["grid_id"])
        self.grid = prepare_grid(self.grid_id)
        self.speed = float(params.get("speed", 10.0))
        self.mode = str(params.get("mode", "demo"))
        self.counter = 0
        print(f"Params: {params}", flush=True)
        print(f"Grid ID: {self.grid_id}", flush=True)
        print(f"Speed: {self.speed}", flush=True)
        print(f"Mode: {self.mode}", flush=True)

    def start(self) -> None:
        print("Started with runtime parameters", flush=True)

    def step(self) -> None:
        self.counter += 1
        print(f"Step {self.counter}: mode={self.mode}, speed={self.speed}", flush=True)
