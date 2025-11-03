import os
import redis
import json

from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv(usecwd=True), override=False)

# === Настройка подключения ===
resolved_url = os.getenv("REDIS_URL", "redis://api.outenemy.ru:6379/0")
resolved_username = os.getenv("REDIS_USERNAME")
resolved_password = os.getenv("REDIS_PASSWORD")

# resolved_username=os.getenv("REDIS_ADMIN_USERNAME")
# resolved_password = os.getenv("REDIS_ADMIN_PASSWORD")

print(resolved_username)
print(resolved_password)
# if not resolved_username:
#     raise SystemExit("REDIS_USERNAME не задан")

# твой реальный ключ телеметрии
key_name = "se:144115188075855919:grid:127168092107255649:text_panel:99187922852764730:telemetry"
key_name = "se:144115188075855919:grids"
# key_name = "telemetry/device/ore_detector/141123856054096097/124829695601500437"
# key_name = "telemetry/device/ore_detector/*"
# key_name = "se:144115188075855898:grid:141123856054096097:ore_detector:124829695601500437:telemetry"

r = redis.Redis.from_url(
    resolved_url,
    username=resolved_username,
    password=resolved_password,
    decode_responses=True,
)

# Получаем содержимое ключа
raw = r.get(key_name)
if raw:
    try:
        payload = json.loads(raw)
        print("Key content:", payload)
    except Exception:
        print("Raw key content:", raw)
else:
    print("Key not found or empty")
