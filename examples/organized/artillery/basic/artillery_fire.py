import time
from secontrol.common import close, prepare_grid, resolve_owner_id



def main():
    """Подключаемся к гриду и производим выстрел артиллерии."""
    grid = prepare_grid("DroneBase")

    for d in grid.devices.values():
        print(d.device_type)

    # Находим артиллерийское устройство по имени "Artillery"
    artillery = grid.get_first_device(device_type="ArtilleryDevice")

    if not artillery:
        print("Артиллерия не найдена!")
        return

    print(f"Найдена {artillery.name}")
    print(f"Включена: {artillery.is_enabled()}")
    print(f"Работает: {artillery.is_working()}")
    print(f"Заряжается: {artillery.is_reloading()}")
    print(f"Стреляет: {artillery.is_shooting()}")

    # Проверяем количество снарядов
    ammo = artillery.ammo_status()
    print(f"Боекомплект: {ammo}")

    if ammo.get("current", 0) == 0:
        print("Нет снарядов! Невозможно выстрелить.")
        return

    # Производим одиночный выстрел
    print("Стреляем...")
    result = artillery.shoot_once()
    print(f"Команда отправлена, результат: {result}")

    # Ждем немного для обработки
    time.sleep(1)

    # Проверяем статус снова
    ammo_after = artillery.ammo_status()
    print(f"Боекомплект после выстрела: {ammo_after}")

    print("Готово!")


if __name__ == "__main__":
    main()
