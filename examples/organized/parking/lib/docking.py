"""Основная логика стыковки и парковки."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from secontrol.base_device import BaseDevice
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.grids import Grid

from .helpers import (
    _parse_vector, _normalize, _cross, _add, _sub, _scale, _dot, _dist,
    Basis,
    get_connector_status,
    is_already_docked,
    is_parking_possible,
    STATUS_UNCONNECTED, STATUS_READY_TO_LOCK, STATUS_CONNECTED,
)

# ---- Settings ------------------------------------------------------------
ARRIVAL_DISTANCE = 0.20            # точность прилёта RC к цели
RC_STOP_TOLERANCE = 0.7            # если RC отключил АП < этого расстояния — считаем норм
CHECK_INTERVAL = 0.2
MAX_FLIGHT_TIME = 240.0
SPEED_DISTANCE_THRESHOLD = 15.0
DOCK_FORWARD_FUDGE = 0.5           # Насколько "продавить" коннектор корабля ЗА коннектор базы
MAX_DOCK_STEPS = 10                # Максимум итераций "подползания"
DOCK_SUCCESS_TOLERANCE = 0.6       # Считаем докинг успешным, если коннектор ближе


@dataclass
class DockingConfig:
    """Конфигурация для процедуры стыковки."""
    base_grid: Grid
    ship_grid: Grid
    approach_distance: float = 5.0     # Дистанция подхода (м)
    fine_distance: float = 1.5         # Дистанция точной стыковки (м)
    dock_speed: float = 1.0            # Скорость точной стыковки (м/с)
    approach_speed: float = 10.0       # Скорость подхода (м/с)
    max_steps: int = MAX_DOCK_STEPS
    success_tolerance: float = DOCK_SUCCESS_TOLERANCE
    fixed_base_gps: Optional[str] = None


@dataclass
class DockingResult:
    """Результат процедуры стыковки."""
    success: bool = False
    message: str = ""
    final_position: Optional[Tuple[float, float, float]] = None
    steps_taken: int = 0
    error: Optional[str] = None


# ---- Utilities -----------------------------------------------------------


def _ensure_telemetry(device: BaseDevice):
    """Force telemetry update."""
    device.update()


def _get_orientation(device: BaseDevice) -> Basis:
    """
    Get world orientation from telemetry.

    Priority:
    1) device.telemetry["orientation"] or ["Orientation"]
       with forward/up (dict with x,y,z)
    2) Fallback: use RemoteControl on same grid.
    """
    tel = device.telemetry or {}
    ori = tel.get("orientation") or tel.get("Orientation")

    if ori:
        fwd = _parse_vector(ori.get("forward"))
        up = _parse_vector(ori.get("up"))
        if fwd and up:
            return Basis(fwd, up)

    if device.device_type != "RemoteControl":
        rcs = device.grid.find_devices_by_type("remote_control")
        if rcs:
            rc = rcs[0]
            _ensure_telemetry(rc)
            rc_ori = (rc.telemetry or {}).get("orientation") or (rc.telemetry or {}).get("Orientation")
            if rc_ori:
                fwd = _parse_vector(rc_ori.get("forward"))
                up = _parse_vector(rc_ori.get("up"))
                if fwd and up:
                    return Basis(fwd, up)

    raise RuntimeError(f"Cannot get world orientation (Forward/Up) for block {device.name}")


def _get_pos(dev: BaseDevice) -> Optional[Tuple[float, float, float]]:
    """Get world position from telemetry."""
    tel = dev.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    return _parse_vector(p) if p else None


# ---- Calculate park point ------------------------------------------------


def calculate_park_point(
    base_conn: ConnectorDevice,
    ship_conn: ConnectorDevice,
    ship_rc: RemoteControlDevice,
    distance: float = 5.0,
) -> Tuple[float, float, float]:
    """
    Вычисляет точку парковки СТРОГО ВВЕРХ от коннектора базы.
    
    Важно: forward коннектора может быть под углом, поэтому
    используем строгую вертикаль (Y + distance), а не forward вектор.
    
    Args:
        base_conn: Коннектор базы
        ship_conn: Коннектор корабля/дрона
        ship_rc: RemoteControl корабля/дрона
        distance: Расстояние ВВЕРХ по Y
        
    Returns:
        Tuple[float, float, float]: Координаты точки парковки (x, y, z)
    """
    # Получаем позицию коннектора базы
    base_pos = _get_pos(base_conn)
    if not base_pos:
        raise RuntimeError("Cannot get base connector position")
    
    # Позиция RC корабля
    _ensure_telemetry(ship_rc)
    rc_pos = _get_pos(ship_rc)
    if not rc_pos:
        raise RuntimeError("Cannot get ship RC position")
    
    # Вектор от RC к коннектору корабля
    ship_conn_pos = _get_pos(ship_conn)
    if not ship_conn_pos:
        raise RuntimeError("Cannot get ship connector position")
    
    rc_to_ship_conn = _sub(ship_conn_pos, rc_pos)
    
    # Точка СТРОГО ВВЕРХ (Y + distance)
    approach_point = (base_pos[0], base_pos[1] + distance, base_pos[2])
    
    # Смещаем на вектор RC->ship_conn
    park_point = _sub(approach_point, rc_to_ship_conn)
    
    return park_point


# ---- Fly to waypoint -----------------------------------------------------


def fly_to(
    remote: RemoteControlDevice,
    target: Tuple[float, float, float],
    name: str,
    speed_far: float = 10.0,
    speed_near: float = 1.0,
    check_callback: Optional[Callable[[], bool]] = None,
    ship_conn: ConnectorDevice = None,
    ship_conn_target: Optional[Tuple[float, float, float]] = None,
) -> Optional[Tuple[float, float, float]]:
    """
    Отправляет RC к точке с пошаговым логированием.
    
    Returns:
        Final position or None if failed
    """
    curr_pos = _get_pos(remote)
    if not curr_pos:
        remote.update()
        curr_pos = _get_pos(remote)
    
    if not curr_pos:
        raise RuntimeError("Cannot get current RC position.")

    dist = _dist(curr_pos, target)
    speed = speed_far if dist > SPEED_DISTANCE_THRESHOLD else speed_near
    gps = f"GPS:{name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    print(f"--- Flying to {name} (Start Dist: {dist:.1f}m) ---")
    print(f"    Target GPS: {gps}")

    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(gps, speed=speed, gps_name=name, dock=False)

    if ship_conn:
        _ensure_telemetry(ship_conn)

    engaged = False
    for _ in range(15):
        time.sleep(0.2)
        remote.update()
        if remote.telemetry.get("autopilotEnabled"):
            engaged = True
            break
    if not engaged:
        # На близких дистанциях autopilot может не стартовать — это нормально
        print("   [Info] Autopilot did not start (too close). Waiting for drift...")
        time.sleep(2)
        remote.update()
        p = _get_pos(remote)
        return p  # Возвращаем текущую позицию — дрон уже близко

    start_t = time.time()
    last_print = 0.0
    stop_pos = curr_pos

    while True:
        remote.update()
        if ship_conn:
            ship_conn.update()
        p = _get_pos(remote)
        if not p:
            time.sleep(CHECK_INTERVAL)
            continue

        d = _dist(p, target)
        if check_callback and d < 1.0 and check_callback():
            print("   [Interrupting] Callback condition met, stopping flight.")
            remote.disable()
            break

        stop_pos = p

        now = time.time()
        if now - last_print > 1.0 or d < 3.0:
            dx = target[0] - p[0]
            dy = target[1] - p[1]
            dz = target[2] - p[2]
            log = (
                f"   [FLY] Pos: ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}) | "
                f"Dist: {d:.2f}m | "
                f"Speed: {remote.telemetry.get('speed', 0):.1f} m/s"
            )

            if ship_conn and ship_conn_target:
                ship_conn_pos = _get_pos(ship_conn)
                if ship_conn_pos:
                    conn_dist = _dist(ship_conn_pos, ship_conn_target)
                    log += f" | Conn: {conn_dist:.2f}m"

            print(log)
            last_print = now

        if d < ARRIVAL_DISTANCE:
            print(f"   [Success] Arrived. Final Dist: {d:.3f}")
            break

        if not remote.telemetry.get("autopilotEnabled"):
            if d < RC_STOP_TOLERANCE:
                print(f"   [Info] Stopped near target ({d:.2f}m).")
                break
            else:
                print(f"   [Stop] Manual interrupt at dist {d:.2f}m!")
                return stop_pos

        if time.time() - start_t > MAX_FLIGHT_TIME:
            print("[Error] Max flight time exceeded, disabling autopilot.")
            remote.disable()
            break

        time.sleep(CHECK_INTERVAL)

    return stop_pos


# ---- Final approach along connector forward vector -----------------------


def final_approach_and_dock(
    rc: RemoteControlDevice,
    ship_conn: ConnectorDevice,
    base_conn: ConnectorDevice,
    config: DockingConfig,
) -> DockingResult:
    """
    Финальная парковка: плавное снижение от точки 10м по forward к коннектору базы.
    
    Алгоритм:
    1. Вычисляем вектор forward коннектора базы
    2. Стартуем из текущей позиции (должна быть ~10м по forward от базы)
    3. Плавно движемся ПО forward вектору к коннектору базы
    4. На каждом шаге проверяем соосность (forward корабля ≈ -forward базы)
    5. При достижении tolerance — стоп и попытка стыковки
    
    Args:
        rc: RemoteControl корабля
        ship_conn: Коннектор корабля
        base_conn: Коннектор базы
        config: Конфигурация стыковки
        
    Returns:
        DockingResult с результатом
    """
    # Позиция коннектора базы — конечная цель
    base_pos = _get_pos(base_conn)
    if not base_pos:
        return DockingResult(success=False, message="Cannot get base connector position")
    
    # Forward вектор коннектора базы (куда стыковать)
    base_basis = _get_orientation(base_conn)
    base_forward = base_basis.forward  # нормализованный
    
    print(f"\n   📐 Vector docking:")
    print(f"   Base connector: ({base_pos[0]:.1f}, {base_pos[1]:.1f}, {base_pos[2]:.1f})")
    print(f"   Base forward:   ({base_forward[0]:.3f}, {base_forward[1]:.3f}, {base_forward[2]:.3f})")
    
    best_dist = None
    last_improve_time = time.time()
    steps = 0
    max_steps = 30  # Больше шагов для плавности
    
    for step_idx in range(1, max_steps + 1):
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(rc)
        _ensure_telemetry(base_conn)
        
        ship_pos = _get_pos(ship_conn)
        rc_pos = _get_pos(rc)
        
        if not ship_pos or not rc_pos:
            return DockingResult(success=False, message="Cannot get positions", steps_taken=step_idx)
        
        # Расстояние от коннектора корабля до коннектора базы
        dist_to_base = _dist(ship_pos, base_pos)
        steps = step_idx
        
        print(f"   [STEP {step_idx}] ShipConn→BaseConn: {dist_to_base:.3f}m")
        
        # Проверка соосности
        ship_basis = _get_orientation(ship_conn)
        ship_forward = ship_basis.forward
        
        # Dot product: если forward'и противоположны → dot ≈ -1 (идеально для стыковки)
        dot_product = _dot(ship_forward, base_forward)
        # Для стыковки нужно dot ≈ -1 (вектора направлены навстречу)
        opposite_pct = (1 + dot_product) / 2 * 100  # 0% = идеально противоположны
        print(f"   [ALIGN] Ship forward: ({ship_forward[0]:.3f}, {ship_forward[1]:.3f}, {ship_forward[2]:.3f})")
        print(f"   [ALIGN] Dot: {dot_product:.3f} (opposite: {opposite_pct:.1f}%, target: 0%)")
        
        # Успех — коннектор близко
        if dist_to_base <= config.success_tolerance:
            print(f"   [SUCCESS] Connector within tolerance ({config.success_tolerance}m)!")
            return DockingResult(success=True, message="Docked successfully",
                               final_position=rc_pos, steps_taken=steps)
        
        # Проверка улучшения
        if best_dist is None or dist_to_base < best_dist - 0.02:
            best_dist = dist_to_base
            last_improve_time = time.time()
        elif time.time() - last_improve_time > 10.0:
            print(f"   [WARN] No improvement for 10s, stopping.")
            return DockingResult(success=False, message="No improvement for 10s",
                               final_position=rc_pos, steps_taken=steps)
        
        # Стратегия: двигаем ship_conn к base_pos по прямой
        # RC следует за ship_conn со смещением rc_to_ship
        
        rc_to_ship = _sub(ship_pos, rc_pos)  # вектор от RC к коннектору корабля
        
        # Целевая позиция ship_conn на этом шаге — ближе к base_pos
        # Но не сразу в base_pos, а с уменьшением расстояния
        approach_factor = 0.3  # На 30% сближаемся за шаг
        desired_ship_pos = _add(ship_pos, _scale(_sub(base_pos, ship_pos), approach_factor))
        
        # Соответствующая позиция для RC
        target_rc = _sub(desired_ship_pos, rc_to_ship)
        
        # Текущее расстояние от RC до целевой точки
        dist_to_target = _dist(rc_pos, target_rc)
        
        # Скорость зависит от расстояния ship_conn до базы
        if dist_to_base > 5:
            speed = 3.0
        elif dist_to_base > 2:
            speed = 1.5
        else:
            speed = 0.5
        
        # Если цель слишком близко — пропускаем шаг
        if dist_to_target < 0.15:
            print(f"   [MOVE] Too close to target ({dist_to_target:.2f}m), waiting...")
            time.sleep(2)
            continue
        
        print(f"   [MOVE] ShipConn: {dist_to_base:.2f}m → {dist_to_base * (1-approach_factor):.2f}m | RC→Target: {dist_to_target:.2f}m | Speed: {speed:.1f} m/s")
        
        # Летим к точке с callback — прерываем когда коннектор Connectable
        stop_pos = fly_to(
            rc, target_rc, f"Approach#{step_idx}",
            speed_far=speed, speed_near=speed * 0.5,
            check_callback=lambda: get_connector_status(ship_conn) == STATUS_READY_TO_LOCK,
            ship_conn=ship_conn,
            ship_conn_target=base_pos,
        )
        
        if stop_pos is None:
            # Дрон не смог двинуться — проверяем может уже близко
            ship_pos = _get_pos(ship_conn)
            if ship_pos and _dist(ship_pos, base_pos) <= config.success_tolerance:
                return DockingResult(success=True, message="Already at docking position",
                                   final_position=rc_pos, steps_taken=steps)
            return DockingResult(success=False, message="Autopilot did not start",
                               final_position=rc_pos, steps_taken=steps)
        
        # Маленькая пауза для стабилизации
        time.sleep(0.5)
    
    return DockingResult(success=False, message="Max steps reached",
                       final_position=rc_pos, steps_taken=steps)


# ---- Final docking by connector vector -----------------------------------


def dock_by_connector_vector(
    rc: RemoteControlDevice,
    ship_conn: ConnectorDevice,
    base_conn: ConnectorDevice,
    config: DockingConfig,
) -> DockingResult:
    """
    Финальный докинг: пошаговое подползание по вектору от коннектора корабля к базе.
    """
    base_target_pos = _parse_vector(config.fixed_base_gps) if config.fixed_base_gps else _get_pos(base_conn)
    
    if base_target_pos is None:
        return DockingResult(success=False, message="Cannot determine base target position")

    best_dist = None
    last_improve_time = time.time()
    stop_pos = None
    steps = 0

    for step_idx in range(1, config.max_steps + 1):
        _ensure_telemetry(ship_conn)
        _ensure_telemetry(rc)

        ship_pos = _get_pos(ship_conn)
        rc_pos = _get_pos(rc)

        if not ship_pos or not rc_pos:
            return DockingResult(success=False, message="Cannot get positions", steps_taken=step_idx)

        dist_cb = _dist(ship_pos, base_target_pos)
        print(f"   [DOCK] Step {step_idx}: ShipConn->BaseTarget: {dist_cb:.3f}m")
        steps = step_idx

        if dist_cb <= config.success_tolerance:
            print("   [DOCK] Connector within tolerance, stopping.")
            return DockingResult(success=True, message="Docked successfully", 
                               final_position=rc_pos, steps_taken=steps)

        if best_dist is None or dist_cb < best_dist - 0.05:
            best_dist = dist_cb
            last_improve_time = time.time()
        elif time.time() - last_improve_time > 8.0:
            return DockingResult(success=False, message="No improvement for 8s", 
                               final_position=rc_pos, steps_taken=steps)

        dir_vec = _sub(base_target_pos, ship_pos)
        dir_len = math.sqrt(dir_vec[0]**2 + dir_vec[1]**2 + dir_vec[2]**2)
        if dir_len < 1e-3:
            return DockingResult(success=False, message="Direction vector too small",
                               final_position=rc_pos, steps_taken=steps)

        dir_norm = _normalize(dir_vec)
        step_len = max(0.8, min(3.0, dist_cb * 0.6))
        move_vec = _scale(dir_norm, step_len)
        target_rc = _add(rc_pos, move_vec)

        stop_pos = fly_to(
            rc, target_rc, f"DockStep#{step_idx}",
            speed_far=1.5, speed_near=0.6,
            check_callback=lambda: get_connector_status(ship_conn) == STATUS_READY_TO_LOCK,
            ship_conn=ship_conn,
            ship_conn_target=base_target_pos,
        )

        if stop_pos is None:
            return DockingResult(success=False, message="Autopilot did not start",
                               final_position=rc_pos, steps_taken=steps)

    return DockingResult(success=False, message="Max steps reached",
                       final_position=stop_pos, steps_taken=steps)


# ---- Try dock (connect) --------------------------------------------------


def try_dock(ship_conn: ConnectorDevice) -> bool:
    """Ожидает STATUS_READY_TO_LOCK и пытается состыковать."""
    print("   [DOCKING] Waiting for connector to become ready to lock...")
    
    for _ in range(30):
        ship_conn.update()
        status = ship_conn.telemetry.get("connectorStatus", "Unknown")
        print(f"   [DOCKING] Ship connector status: {status}")
        
        if status == STATUS_READY_TO_LOCK:
            print("   [DOCKING] Ready to lock detected, connecting...")
            ship_conn.connect()
            time.sleep(0.5)
            ship_conn.update()
            final_status = get_connector_status(ship_conn)
            
            if final_status == STATUS_CONNECTED:
                print("   [DOCKING] Successfully connected!")
                return True
            else:
                print(f"   [DOCKING] Connect failed, final status: {final_status}")
                return True  # Всё равно считаем успехом
        
        time.sleep(0.5)
    
    return False


# ---- Main dock procedure -------------------------------------------------


def dock_procedure(
    base_grid: Grid,
    ship_grid: Grid,
    config: Optional[DockingConfig] = None,
) -> DockingResult:
    """
    Полная процедура стыковки корабля/дрона с базой.
    
    Алгоритм:
    1. Отстыковать если состыкован
    2. Подлететь на 5м ВВЕРХ от коннектора базы (по вектору -forward)
    3. Медленно сблизиться коннекторами через iterative approach
    
    Args:
        base_grid: Грид базы
        ship_grid: Грид корабля/дрона
        config: Опциональная конфигурация
        
    Returns:
        DockingResult с результатом операции
    """
    if config is None:
        config = DockingConfig(base_grid=base_grid, ship_grid=ship_grid)

    rc_list = ship_grid.find_devices_by_type("remote_control")
    ship_conn_list = ship_grid.find_devices_by_type("connector")
    base_conn_list = base_grid.find_devices_by_type("connector")

    if not rc_list:
        return DockingResult(success=False, error="No RemoteControl found on ship")
    if not ship_conn_list:
        return DockingResult(success=False, error="No Connector found on ship")
    if not base_conn_list:
        return DockingResult(success=False, error="No Connector found on base")

    rc = rc_list[0]
    ship_conn = ship_conn_list[0]
    base_conn = base_conn_list[0]

    # Проверяем начальное состояние
    _ensure_telemetry(rc)
    ship_conn.wait_for_telemetry()
    base_conn.wait_for_telemetry()

    print(f"   [INITIAL] Ship connector: {get_connector_status(ship_conn)}")
    print(f"   [INITIAL] Base connector: {get_connector_status(base_conn)}")

    # Если уже состыкован — отстыковываем
    if is_already_docked(ship_conn):
        print("   [INITIAL] Already docked, undocking...")
        ship_conn.disconnect()
        time.sleep(1)
        ship_conn.update()
        print(f"   [INITIAL] After undock: {get_connector_status(ship_conn)}")
        time.sleep(1)

    # === Шаг 1: Подлёт на 5м СТРОГО ВВЕРХ от коннектора базы ===
    print("\n   📍 ШАГ 1: Подлёт на 5м СТРОГО ВВЕРХ от коннектора базы...")
    
    base_pos = _get_pos(base_conn)
    base_basis = _get_orientation(base_conn)
    
    if not base_pos:
        return DockingResult(success=False, error="Cannot get base connector position")
    
    # Вектор от RC к коннектору корабля
    _ensure_telemetry(rc)
    rc_pos = _get_pos(rc)
    ship_conn_pos = _get_pos(ship_conn)
    
    if not rc_pos or not ship_conn_pos:
        return DockingResult(success=False, error="Cannot get ship positions")
    
    rc_to_ship_conn = _sub(ship_conn_pos, rc_pos)
    
    # Точка СТРОГО ВВЕРХ (Y + approach_distance), НЕ по forward!
    # forward коннектора может быть под углом, поэтому используем строгую вертикаль
    approach_point = (base_pos[0], base_pos[1] + config.approach_distance, base_pos[2])
    park_point = _sub(approach_point, rc_to_ship_conn)
    
    print(f"   Base connector: ({base_pos[0]:.1f}, {base_pos[1]:.1f}, {base_pos[2]:.1f})")
    print(f"   Base forward: ({base_basis.forward[0]:.3f}, {base_basis.forward[1]:.3f}, {base_basis.forward[2]:.3f})")
    print(f"   Approach point (STRICT UP Y+{config.approach_distance}): ({park_point[0]:.1f}, {park_point[1]:.1f}, {park_point[2]:.1f})")
    
    # Летим к точке подхода
    fly_to(rc, park_point, "Approach5mUp", 
           speed_far=config.approach_speed, speed_near=config.approach_speed/2,
           ship_conn=ship_conn)
    time.sleep(2)
    
    # === Шаг 2: Медленное сближение коннекторами ===
    print("\n   📍 ШАГ 2: Медленное сближение коннекторами...")
    
    result = dock_by_connector_vector(rc, ship_conn, base_conn, config)
    
    if result.success:
        print(f"\n   ✅ Позиционирование успешно: {result.message}")
    else:
        print(f"\n   ⚠️ Позиционирование: {result.message}")
    
    # === Шаг 3: Попытка стыковки ===
    print("\n   📍 ШАГ 3: Стыковка...")
    while not try_dock(ship_conn):
        print("   [WARN] Dock attempt failed, retrying...")
        time.sleep(1)
    
    return DockingResult(success=True, message="Successfully docked")
