from secontrol.common import prepare_grid
import os
import json


class App:
    def __init__(self, params):
        self.grid = prepare_grid(params['grid_id'])
        print(params)


    def start(self):
        print("Started!")

    def step(self):

        print(f"Step")
