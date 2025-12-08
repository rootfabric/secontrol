from WorkerApi import WorkerApiClient

client = WorkerApiClient()

# 1. Список запущенных программ
running = client.get_running_programs()
print("Running:", running)

# 2. Создать программу
program = client.create_program("Drone harvest")
program_uuid = program["uuid"]
print("Program uuid:", program_uuid)

# 3. Загрузить скрипт
client.upload_files(program_uuid, ["drone_harvest_basic3.py"])

# 4. Запустить на известном гриде
run_info = client.run_program(
    program_uuid,
    "drone_harvest_basic3.py",
    grid_id="134815497374974083",  # пример реального grid_id из твоих логов
)
print("Run:", run_info)

# 5. Получить хвост логов
logs = client.get_program_logs(program_uuid, tail_bytes=5000)
print(logs)
