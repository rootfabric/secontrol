"""Вычислить точку парковки по вектору forward коннектора базы."""
from __future__ import annotations

from typing import Tuple
from secontrol import Grid
from secontrol.redis_client import RedisEventClient


def calculate_connector_forward_point(
    base_grid: Grid,
    distance: float = 10.0,
    connector_name: str = None,
) -> Tuple[float, float, float]:
    """
    Вычисляет точку на заданном расстоянии по вектору forward коннектора базы.
    
    Args:
        base_grid: Грид базы (объект Grid)
        distance: Расстояние по forward вектору (метры), по умолчанию 10м
        connector_name: Имя коннектора (опционально, берётся первый если не указан)
        
    Returns:
        Tuple[float, float, float]: (x, y, z) — координаты точки
        
    Example:
        base = Grid.from_name("DroneBase 2", redis_client=client)
        point = calculate_connector_forward_point(base, distance=10.0)
        # point = (999432.20, 90587.40, 1595517.45)
    """
    # Находим коннектор
    connectors = base_grid.find_devices_by_type("connector")
    if not connectors:
        raise RuntimeError(f"На гриде '{base_grid.name}' не найден коннектор!")
    
    # Если указано имя — ищем по имени
    if connector_name:
        conn = None
        for c in connectors:
            if connector_name.lower() in (c.telemetry.get("customName") or "").lower():
                conn = c
                break
        if not conn:
            raise RuntimeError(f"Коннектор '{connector_name}' не найден! Доступные: {[c.telemetry.get('customName') for c in connectors]}")
    else:
        conn = connectors[0]
    
    # Получаем позицию и forward
    pos = conn.telemetry.get("position", {})
    orientation = conn.telemetry.get("orientation", {})
    fwd = orientation.get("forward", {})
    
    base_x = pos.get("x", 0)
    base_y = pos.get("y", 0)
    base_z = pos.get("z", 0)
    
    fwd_x = fwd.get("x", 0)
    fwd_y = fwd.get("y", 0)
    fwd_z = fwd.get("z", 0)
    
    # Вычисляем точку
    target_x = base_x + fwd_x * distance
    target_y = base_y + fwd_y * distance
    target_z = base_z + fwd_z * distance
    
    return (target_x, target_y, target_z)


def calculate_connector_forward_point_by_name(
    base_name: str,
    distance: float = 10.0,
    connector_name: str = None,
    redis_client=None,
) -> Tuple[float, float, float]:
    """
    Вычисляет точку по имени базы (создаёт Grid автоматически).
    
    Args:
        base_name: Имя грида базы (например "DroneBase 2")
        distance: Расстояние по forward вектору (метры)
        connector_name: Имя коннектора (опционально)
        redis_client: RedisEventClient (если None — создаст новый)
        
    Returns:
        Tuple[float, float, float]: (x, y, z) — координаты точки
        
    Example:
        point = calculate_connector_forward_point_by_name("DroneBase 2", distance=10.0)
    """
    owns_client = False
    if redis_client is None:
        redis_client = RedisEventClient()
        owns_client = True
    
    try:
        base = Grid.from_name(base_name, redis_client=redis_client)
        point = calculate_connector_forward_point(base, distance, connector_name)
        base.close()
        return point
    finally:
        if owns_client:
            redis_client.close()


# === CLI ===
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Вычислить точку по forward коннектора базы")
    parser.add_argument("--base", default="DroneBase 2", help="Имя базы (по умолчанию: DroneBase 2)")
    parser.add_argument("--distance", type=float, default=10.0, help="Расстояние по forward (по умолчанию: 10м)")
    parser.add_argument("--connector", default=None, help="Имя коннектора (по умолчанию: первый)")
    parser.add_argument("--gps", action="store_true", help="Вывести в GPS формате")
    
    args = parser.parse_args()
    
    client = RedisEventClient()
    
    try:
        point = calculate_connector_forward_point_by_name(args.base, args.distance, args.connector, client)
        
        print(f"База: {args.base}")
        print(f"Расстояние: {args.distance}м")
        print(f"\n🎯 Точка: ({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f})")
        
        if args.gps:
            gps = f"GPS:Target:{point[0]:.6f}:{point[1]:.6f}:{point[2]:.6f}:"
            print(f"\n📍 GPS: {gps}")
    finally:
        client.close()
