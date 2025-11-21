from __future__ import annotations
import math
import time
from typing import Dict, Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice, BlockInfo
from secontrol.common import close, prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# ---- Настройки -----------------------------------------------------------
ARRIVAL_DISTANCE = 0.20
RC_STOP_TOLERANCE = 2.0
CHECK_INTERVAL = 0.2
MAX_FLIGHT_TIME = 240.0
SPEED_DISTANCE_THRESHOLD = 15.0


# ---- Математика ----------------------------------------------------------

def _vec(value: Sequence[float]) -> Tuple[float, float, float]:
    """Преобразует последовательность чисел в кортеж (x, y, z)."""
    return float(value[0]), float(value[1]), float(value[2])


def _parse_vector(value: object) -> Optional[Tuple[float, float, float]]:
    """Парсинг вектора из разных форматов (строка GPS, словарь, список)."""
    if isinstance(value, str):
        parts = value.split(':')
        if len(parts) >= 5 and parts[0] == 'GPS':
            return (float(parts[2]), float(parts[3]), float(parts[4]))
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return _vec((value["x"], value["y"], value["z"]))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return _vec(value)
    return None


def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Нормализация вектора."""
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-6: return (0.0, 0.0, 1.0)
    return v[0] / length, v[1] / length, v[2] / length


def _cross(a, b):
    """Векторное произведение."""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(v, s): return (v[0] * s, v[1] * s, v[2] * s)


def _dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class Basis:
    """Представление базиса (Forward, Up, Right) для блока."""

    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        self.forward = _normalize(forward)
        raw_up = _normalize(up)
        right = _cross(self.forward, raw_up)
        self.right = _normalize(right)
        self.up = _normalize(_cross(self.right, self.forward))


# ---- Утилиты -------------------------------------------------------------

def _ensure_telemetry(device: BaseDevice):
    """Обновляет телеметрию устройства."""
    device.update()


def _get_block_info(grid, device: BaseDevice) -> BlockInfo:
    """Получает информацию о блоке из данных грида."""
    try:
        b = grid.get_block(int(device.device_id))
        if b: return b
    except:
        pass
    target_id = int(device.device_id)
    for b in grid.blocks.values():
        if b.id == target_id: return b
    raise RuntimeError(f"Блок {device.name} не найден в gridinfo!")


def _get_orientation(device: BaseDevice) -> Basis:
    """Получает ориентацию устройства, используя прямые векторы или откат к RC."""
    tel = device.telemetry or {}
    ori = tel.get("orientation") or tel.get("Orientation")

    if ori:
        fwd = _parse_vector(ori.get("forward"))
        up = _parse_vector(ori.get("up"))

        if fwd and up:
            print(f"   [INFO] Using direct orientation vectors for {device.name}.")
            return Basis(fwd, up)

    # Аварийный откат (если ориентация коннектора не отдана, но есть RC на гриде)
    if device.device_type != "RemoteControl":
        print(f"   [WARN] No direct orientation for {device.name}. Searching for RC on grid...")
        rcs = device.grid.find_devices_by_type(RemoteControlDevice)
        if rcs:
            rc = rcs[0]
            if rc.telemetry.get("orientation") or rc.telemetry.get("Orientation"):
                _ensure_telemetry(rc)
                rc_ori = rc.telemetry.get("orientation") or rc.telemetry.get("Orientation")
                fwd = _parse_vector(rc_ori.get("forward"))
                up = _parse_vector(rc_ori.get("up"))
                print(f"   [WARN] Fallback: Using Remote Control orientation for Base.")
                if fwd and up:
                    return Basis(fwd, up)

    raise RuntimeError(f"Не удалось получить мировую ориентацию (Forward/Up) для блока {device.name}")


# ---- ЛОГИКА РАСЧЕТА СТЫКОВКИ ---------------------------------------

def _calculate_docking_point(
        ship_rc: RemoteControlDevice,
        ship_conn: ConnectorDevice,
        base_conn: ConnectorDevice,
        base_grid,
        fixed_base_gps: str = None
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
    """Рассчитывает финальную позицию RC для стыковки."""
    # 1. Локальное смещение на корабле
    rc_blk = _get_block_info(ship_rc.grid, ship_rc)
    conn_blk = _get_block_info(ship_rc.grid, ship_conn)
    rc_loc = _vec(rc_blk.relative_to_grid_center)
    conn_loc = _vec(conn_blk.relative_to_grid_center)
    diff_local = _sub(rc_loc, conn_loc)  # Вектор от Коннектора к RC

    # 2. Данные базы
    base_basis = _get_orientation(base_conn)

    # 3. Позиция коннектора базы
    base_pos = None
    if fixed_base_gps:
        base_pos = _parse_vector(fixed_base_gps)

    if not base_pos:
        tel = base_conn.telemetry or {}
        p = tel.get("worldPosition") or tel.get("position")
        if p:
            base_pos = _parse_vector(p)
        else:
            print("   [Base] Calculating connector position via Anchor RC...")
            anchor = base_grid.find_devices_by_type(RemoteControlDevice)[0]
            _ensure_telemetry(anchor)
            anchor_pos = _get_pos(anchor)
            anchor_basis = _get_orientation(anchor)
            a_blk = _get_block_info(base_grid, anchor)
            t_blk = _get_block_info(base_grid, base_conn)
            d = _sub(_vec(t_blk.relative_to_grid_center), _vec(a_blk.relative_to_grid_center))
            world_diff = _add(_add(_scale(anchor_basis.right, d[0]), _scale(anchor_basis.up, d[1])),
                              _scale(anchor_basis.forward, d[2]))
            base_pos = _add(anchor_pos, world_diff)

    # 4. Проекция смещения
    bx, by, bz = diff_local

    v_right = _scale(base_basis.right, -bx)  # Инвертируем X (право -> лево)
    v_up = _scale(base_basis.up, by)  # Y (верх -> верх)

    # *** ИЗМЕНЕНИЕ ДЛЯ ТЕСТА: Убираем инверсию Z. Если RC базы перевернут, это поможет. ***
    v_fwd = _scale(base_basis.forward, bz)  # БЫЛО -bz, СТАЛО bz.

    total_offset = _add(_add(v_right, v_up), v_fwd)

    # 5. Расчет точек
    dock_dist = 0.5  # Уменьшаем зазор, если плавно заходит
    target_point_space = _add(base_pos, _scale(base_basis.forward, dock_dist))
    final_rc_pos = _add(target_point_space, total_offset)

    return final_rc_pos, base_basis.forward, base_pos


# ---- АВТОПИЛОТ С ОТЛАДКОЙ ------------------------------------------------

def _get_pos(dev):
    """Получает мировую позицию устройства."""
    tel = dev.telemetry or {}
    p = tel.get("worldPosition") or tel.get("position")
    return _parse_vector(p) if p else None


def _fly_to(remote: RemoteControlDevice, target: Tuple[float, float, float], name: str, speed_far: float,
            speed_near: float):
    """Отправляет RC в указанную точку с пошаговым логированием."""

    curr_pos = _get_pos(remote)

    if not curr_pos:
        remote.update()
        curr_pos = _get_pos(remote)

    dist = _dist(curr_pos, target)
    speed = speed_far if dist > SPEED_DISTANCE_THRESHOLD else speed_near
    gps = f"GPS:{name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    print(f"--- Flying to {name} (Start Dist: {dist:.1f}m) ---")
    print(f"    Target GPS: {gps}")

    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(gps, speed=speed, gps_name=name, dock=False)

    engaged = False
    for _ in range(15):
        time.sleep(0.2)
        remote.update()
        if remote.telemetry.get("autopilotEnabled"):
            engaged = True
            break
    if not engaged:
        print("   [Error] Autopilot did not start!")
        return

    start_t = time.time()
    last_print = 0

    # Сохраняем позицию остановки для финального сравнения
    stop_pos = curr_pos

    while True:
        remote.update()
        p = _get_pos(remote)
        if not p: continue
        stop_pos = p  # Обновляем текущую позицию

        d = _dist(p, target)

        # --- DEBUG PRINT BLOCK ---
        now = time.time()
        if now - last_print > 1.0 or d < 3.0:  # Печатаем чаще при приближении
            dx = target[0] - p[0]
            dy = target[1] - p[1]
            dz = target[2] - p[2]
            print(
                f"   [FLY] CurrentPos(XYZ): ({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}) | Dist: {d:.2f}m | Delta(XYZ): ({dx:.2f}, {dy:.2f}, {dz:.2f})")
            last_print = now
        # -------------------------

        if d < ARRIVAL_DISTANCE:
            print(f"   [Success] Arrived. Final Dist: {d:.3f}")
            break

        if not remote.telemetry.get("autopilotEnabled"):
            if d < RC_STOP_TOLERANCE:
                print(f"   [Info] Stopped near target ({d:.2f}m). Considered aligned.")
                break
            else:
                print(f"   [Stop] Manual interrupt at dist {d:.2f}m!")
                return

        if time.time() - start_t > MAX_FLIGHT_TIME:
            remote.disable()
            break
        time.sleep(CHECK_INTERVAL)

    return stop_pos  # Возвращаем фактическую позицию остановки


# ---- Main Logic ----------------------------------------------------------

def dock_procedure(base_grid_id: str, ship_grid_id: str, fixed_base_gps: str = None):
    ship_grid = prepare_grid(ship_grid_id)
    base_grid = prepare_grid(ship_grid.redis, base_grid_id)

    current_rc_pos = None
    final_rc_pos = None
    stop_pos_docking = None

    try:
        rc = ship_grid.find_devices_by_type(RemoteControlDevice)[0]
        ship_conn = ship_grid.find_devices_by_type(ConnectorDevice)[0]
        base_conn = base_grid.find_devices_by_type(ConnectorDevice)[0]

        _ensure_telemetry(rc)
        _ensure_telemetry(base_conn)

        # Расчет точки RC
        final_rc_pos, base_fwd, base_conn_pos = _calculate_docking_point(
            rc, ship_conn, base_conn, base_grid, fixed_base_gps
        )

        # Точка подхода (Approach)
        approach_rc_pos = _add(final_rc_pos, _scale(base_fwd, 20.0))

        # --- Plan ---
        current_rc_pos = _get_pos(rc)
        print("\n=======================================================")
        print("                   --- PLAN ---")
        print("=======================================================")
        print(
            f"🚀 Ship RC Current Position: (X={current_rc_pos[0]:.2f}, Y={current_rc_pos[1]:.2f}, Z={current_rc_pos[2]:.2f})")
        print(
            f"⚓ Base Connector Position (Target): (X={base_conn_pos[0]:.2f}, Y={base_conn_pos[1]:.2f}, Z={base_conn_pos[2]:.2f})")
        print(
            f"🎯 Final RC Position (Docking Point): (X={final_rc_pos[0]:.2f}, Y={final_rc_pos[1]:.2f}, Z={final_rc_pos[2]:.2f})")
        print("-------------------------------------------------------")

        input("\nPress Enter to Execute Docking Sequence...")

        _fly_to(rc, approach_rc_pos, "Approach", 15.0, 5.0)
        stop_pos_docking = _fly_to(rc, final_rc_pos, "Docking", 3.0, 0.5)

        print("Locking...")
        ship_conn.connect()

        # Проверка результата
        time.sleep(0.5)
        ship_conn.update()
        status = ship_conn.telemetry.get("status") or ship_conn.telemetry.get("Status")
        print(f"Final Connector Status: {status}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            rc.disable()
        except:
            pass
        close(ship_grid)
        close(base_grid)

        # --- ФИНАЛЬНЫЙ ВЫВОД КООРДИНАТ ---
        if current_rc_pos and final_rc_pos and stop_pos_docking:
            print("\n=======================================================")
            print("                  --- RESULT ---")
            print("=======================================================")
            print(
                f"🚀 RC Start Position: (X={current_rc_pos[0]:.2f}, Y={current_rc_pos[1]:.2f}, Z={current_rc_pos[2]:.2f})")
            print(f"🎯 RC Final Target:   (X={final_rc_pos[0]:.2f}, Y={final_rc_pos[1]:.2f}, Z={final_rc_pos[2]:.2f})")
            print(
                f"🛑 RC Actual Stop:    (X={stop_pos_docking[0]:.2f}, Y={stop_pos_docking[1]:.2f}, Z={stop_pos_docking[2]:.2f})")

            # Рассчитываем финальное отклонение от целевой точки RC
            final_delta_to_target = _sub(final_rc_pos, stop_pos_docking)
            print("--- Deviation from Target (Target - Actual) ---")
            print(
                f"   Delta (DX/DY/DZ): ({final_delta_to_target[0]:.2f}, {final_delta_to_target[1]:.2f}, {final_delta_to_target[2]:.2f})")
            print(f"   Final Distance to Target: {_dist(final_rc_pos, stop_pos_docking):.2f}m")
            print("-----------------------------------------------")


if __name__ == "__main__":
    # ВАЖНО: Убедитесь, что этот GPS соответствует точному центру коннектора на базе!
    FIXED_GPS = "GPS:root #1:1010038.32:170828.19:1672421.4:#FF75C9F1:"

    dock_procedure(
        base_grid_id="DroneBase",
        ship_grid_id="Owl",
        fixed_base_gps=FIXED_GPS
    )