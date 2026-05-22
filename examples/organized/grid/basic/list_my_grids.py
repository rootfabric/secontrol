from secontrol import get_all_grids

for grid_id, grid_name in get_all_grids():
    print(f"{grid_name} ({grid_id})")