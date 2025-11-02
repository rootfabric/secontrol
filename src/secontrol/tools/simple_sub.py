import datetime
import os
import redis
import json

from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv(usecwd=True), override=False)

# === Настройка подключения ===
resolved_url = os.getenv("REDIS_URL", "redis://api.outenemy.ru:6379/0")
resolved_username = os.getenv("REDIS_USERNAME")
resolved_password = os.getenv("REDIS_PASSWORD")

resolved_username=""
resolved_password = os.getenv("REDIS_ADMIN_PASSWORD")

# if not resolved_username:
#     raise SystemExit("REDIS_USERNAME не задан")

# твой реальный ключ телеметрии
key_name = "se:144115188075855919:grid:127168092107255649:text_panel:99187922852764730:telemetry"
key_name = "se:144115188075855919:grid:127168092107255649:damage"
key_name = "telemetry/device/ore_detector/141123856054096097/124829695601500437"
# key_name = "se:144115188075855898:grid:141123856054096097:ore_detector:124829695601500437:telemetry"

# каналы:
DB=1
keyspace_channel = f"__keyspace@{DB}__:{key_name}"   # сработает только если включены keyspace-нотисы
telemetry_channel = key_name                      # на случай, если плагин делает PUBLISH прямо в этот канал

r = redis.Redis.from_url(
    resolved_url,
    username=resolved_username,
    password=resolved_password,
    decode_responses=True,
)

def handle_telemetry(payload):
    print(datetime.datetime.now(), "TELEMETRY:", payload)

pubsub = r.pubsub()

# 1) пробуем подписаться на keyspace
pubsub.subscribe(keyspace_channel)
# 2) и ОБЯЗАТЕЛЬНО на сам канал
# pubsub.subscribe(telemetry_channel)

print("Listening:")
print(" - keyspace:", keyspace_channel)
# print(" - channel :", telemetry_channel)

for msg in pubsub.listen():
    mtype = msg["type"]

    # первые сообщения будут 'subscribe'
    if mtype != "message":
        continue

    channel = msg["channel"]
    data = msg["data"]

    # 1. пришло по ПРЯМОМУ каналу телеметрии (PUBLISH)
    if channel == telemetry_channel:
        # тут обычно уже готовый json
        try:
            payload = json.loads(data)
        except Exception:
            payload = {"raw": data}
        handle_telemetry(payload)
        continue

    # 2. пришло по keyspace (SET/DEL и т.п.)
    if channel == keyspace_channel:
        if data in ("set", "hset"):
            raw = r.get(key_name)
            if raw:
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = {"raw": raw}
                handle_telemetry(payload)
            else:
                print("key updated but empty")
        elif data == "del":
            print("key deleted")