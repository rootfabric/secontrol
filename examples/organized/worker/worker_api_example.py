from WorkerApi import WorkerApiClient
import time

client = WorkerApiClient()

# 1. Список запущенных программ
running = client.get_running_programs()
print("Running:", running)

programs = client.get_programs()
print("Programs:")
program_uuid = None
if programs and "items" in programs:
    for item in programs["items"]:
        name = item.get("name", "N/A")
        uuid = item.get("uuid", "N/A")
        print(f"  {name}: {uuid}")

        if name == 'Drone test':
            program_uuid = uuid
            print(f"Found program 'Drone test' with UUID: {program_uuid}")
            break

if not program_uuid:
    # Если программа не найдена, создаём новую
    print("Program 'Drone test' not found, creating...")
    program = client.create_program("Drone test")
    if program and "uuid" in program:
        program_uuid = program["uuid"]
        print(f"Created program with UUID: {program_uuid}")
    else:
        print("Failed to create program")
        exit(1)

# 3. Загрузить скрипт
# client.upload_files(program_uuid, ["drone_harvest_basic3.py"])

client.upload_files(program_uuid, ["example_app_params.py"])

print("Program UUID:", program_uuid)
# 4. Запустить на известном гриде
run_info = client.run_program(
    program_uuid,
    "example_app_params.py",
    grid_id=program_uuid,  # пример реального grid_id из твоих логов
    params={"param1": 1, "param2": "test param"}
)
print("Run:", run_info)

time.sleep(5)

# 5. Получить хвост логов
logs = client.get_program_logs(program_uuid, tail_bytes=5000)
print(logs)

time.sleep(5)
res = client.stop_program(program_uuid)
print(res)
