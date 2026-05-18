"""Управление режимом парковки грида.

Функции для включения/выключения парковки, подготовки к парковке
и финализации после завершения стыковки.
"""

from __future__ import annotations

import time
from typing import Optional

from secontrol.grids import Grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

from .helpers import get_connector_status, is_already_docked, STATUS_CONNECTED
from .docking import DockingResult, _ensure_telemetry, _get_pos


def park_grid(grid: Grid) -> int:
    """
    Включает режим парковки на гриде.
    
    - Тормозит колёса
    - Выключает трастеры
    - Блокирует коннекторы
    
    Args:
        grid: Грид для парковки
        
    Returns:
        Результат команды
    """
    print(f"  🅿️ Parking grid '{grid.name}'...")
    return grid.park_on()


def unpark_grid(grid: Grid) -> int:
    """
    Выключает режим парковки на гриде.
    
    Args:
        grid: Грид для выхода из парковки
        
    Returns:
        Результат команды
    """
    print(f"  🔓 Unparking grid '{grid.name}'...")
    return grid.park_off()


def prepare_for_parking(ship_grid: Grid) -> bool:
    """
    Подготавливает корабль/дрон к парковке:
    - Снимает режим парковки
    - Включает RemoteControl
    - Включает гироскопы и трастеры
    - Включает демпферы
    
    Args:
        ship_grid: Грид корабля/дрона
        
    Returns:
        True если подготовка успешна
    """
    print("\n🔧 Подготовка к парковке...")
    
    # Снимаем парковку
    unpark_grid(ship_grid)
    
    # Находим и включаем RemoteControl
    remotes = ship_grid.find_devices_by_type("remote_control")
    if not remotes:
        print("  ❌ RemoteControl не найден!")
        return False
    
    rc = remotes[0]
    print(f"  📡 Включаю RemoteControl...")
    rc.enable()
    rc.gyro_control_on()
    rc.thrusters_on()
    rc.dampeners_on()
    time.sleep(1)
    
    return True


def finalize_parking(
    ship_grid: Grid, 
    base_grid: Optional[Grid] = None,
    auto_park: bool = True,
) -> DockingResult:
    """
    Финализация парковки после стыковки:
    - Проверяет статус коннектора
    - Включает режим парковки (если auto_park=True)
    - Выключает системы корабля
    
    Args:
        ship_grid: Грид корабля/дрона
        base_grid: Опционально грид базы (для проверки стыковки)
        auto_park: Включить режим парковки после стыковки
        
    Returns:
        DockingResult с результатом финализации
    """
    print("\n🏁 Финализация парковки...")
    
    # Обновляем телеметрию
    ship_grid.refresh_devices()
    
    # Проверяем коннекторы
    connectors = ship_grid.find_devices_by_type("connector")
    if not connectors:
        return DockingResult(success=False, message="No connector found on ship")
    
    conn = connectors[0]
    conn.update()
    status = get_connector_status(conn)
    
    print(f"  Коннектор: {status}")
    
    if status != STATUS_CONNECTED and base_grid:
        return DockingResult(
            success=False,
            message=f"Not connected: {status}"
        )
    
    # Включаем парковку если нужно
    if auto_park and status == STATUS_CONNECTED:
        print("  🅿️ Включаю режим парковки...")
        park_grid(ship_grid)
        
        # Выключаем системы
        remotes = ship_grid.find_devices_by_type("remote_control")
        if remotes:
            print("  🔌 Выключаю RemoteControl...")
            remotes[0].disable()
    
    return DockingResult(
        success=True,
        message=f"Parking finalized: {status}"
    )


def undock_ship(ship_grid: Grid) -> bool:
    """
    Отстыковывает корабль/дрон от базы.
    
    Args:
        ship_grid: Грид корабля/дрона
        
    Returns:
        True если отстыковка успешна
    """
    print("\n🔓 Отстыковка...")
    
    connectors = ship_grid.find_devices_by_type("connector")
    if not connectors:
        print("  ❌ Коннектор не найден!")
        return False
    
    conn = connectors[0]
    
    if not is_already_docked(conn):
        print("  ℹ️ Не состыкован")
        return True
    
    print(f"  Текущий статус: {get_connector_status(conn)}")
    print("  ⚡ Отстыковка...")
    
    conn.disconnect()
    time.sleep(1)
    conn.update()
    
    new_status = get_connector_status(conn)
    print(f"  Новый статус: {new_status}")
    
    # Снимаем парковку
    unpark_grid(ship_grid)
    
    # Включаем RemoteControl для управления
    remotes = ship_grid.find_devices_by_type("remote_control")
    if remotes:
        rc = remotes[0]
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)
    
    return new_status != STATUS_CONNECTED
