class App:
    def __init__(self, grid):
        self.grid = grid
        print(self.grid.name)
        self.counter = 0

    def start(self):
        print("Started!")

    def step(self):
        self.counter += 1
        print(f"Step {self.counter}")
