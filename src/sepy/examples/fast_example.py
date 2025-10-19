from sepy.redis_client import RedisEventClient
from sepy.common import prepare_grid,resolve_owner_id

# owner_id = resolve_owner_id()
# print(f"Using owner id: {owner_id}")

client, grid = prepare_grid()
print(grid)