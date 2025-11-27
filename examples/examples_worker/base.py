from secontrol.common import prepare_grid

class App:
    def __init__(self, grid):
        # Если нам передали уже подготовленный grid-объект — используем его как есть.
        # Если строку (имя/ID грида) — резолвим через prepare_grid.
        if isinstance(grid, str):
            self.grid = prepare_grid(grid)
        else:
            self.grid = grid
        print(self.grid.name)
        self.counter = 0

    def start(self):
        print("Started!")

    def step(self):
        self.counter += 1
        print(f"Step {self.counter}")
