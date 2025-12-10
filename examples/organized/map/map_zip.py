from secontrol.common import prepare_grid
from secontrol.controllers.shared_map_controller import SharedMapController

grid = prepare_grid("taburet")
mc = SharedMapController(owner_id=grid.owner_id)

# 3) Для справки размер в Redis
# redis_size = mc. get_redis_memory_usage()
# print(f"\nПримерный размер карты в Redis: {redis_size} байт ({redis_size / 1024:.1f} KB)")

stats = mc.thin_voxel_density(
    resolution=5.0,          # шаг "куба" для объединения точек, можно 5–10 м
    min_points_to_thin=1000, # мелкие чанки не трогаем
    max_points_per_cell=1,   # в одном кубе оставляем одну точку
    verbose=True,
)

print("Thinning stats:", stats)

# Если хочешь иметь в контроллере актуальную карту:
# mc.load()  # или load_region(...) для нужного района


# redis_size = mc.get_redis_memory_usage()
# print(f"\nПримерный размер карты в Redis: {redis_size} байт ({redis_size / 1024:.1f} KB)")

