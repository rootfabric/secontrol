"""
Автопилот для стыковки двух коннекторов.

Алгоритм:
1. Берём данные о коннекторе базы (позиция и ориентация) и коннекторе летящего грида.
2. Вычисляем смещение коннектора корабля относительно его REMOTE CONTROL через геометрию грида.
3. Целевая точка для REMOTE CONTROL = позиция коннектора базы минус это смещение.
4. Летим в точку подхода, затем в точку стыковки с флагом dock.

Подсказки:
- Позиции блоков берутся из gridinfo: ``relative_to_grid_center`` / ``local_position``.
- Позиции и ориентации устройств — из телеметрии (``position``, ``orientation.forward``/``up``).
- Оси грида считаются так: x=right, y=up, z=forward.
"""

from __future__ import annotations
"""
Стыковка летящего грида к заданному коннектору базы.

Алгоритм:
1. Читаем из gridinfo позиции REMOTE CONTROL и коннектора корабля относительно центра грида.
2. По телеметрии REMOTE CONTROL строим базис (forward/up/right) и вычисляем мировой сдвиг
   от REMOTE CONTROL до коннектора корабля.
3. Берём мировую позицию коннектора базы (из телеметрии) и вычитаем найденный сдвиг — это
   точка, куда нужно поставить REMOTE CONTROL для совмещения коннекторов.
4. Летим в точку подхода, затем в точку стыковки с флагом ``dock`` аналогично ``drone_goto.py``.

Подсказки:
- ``relative_to_grid_center`` / ``local_position`` в ``gridinfo`` дают координаты блоков
  относительно центра грида.
- Телеметрия устройств должна содержать ``position`` (или ``worldPosition``) и ``orientation``
  с векторами ``forward``/``up``.
"""

import math
import time
from typing import Dict, Iterable, Optional, Sequence, Tuple

from secontrol.base_device import BaseDevice, BlockInfo
from secontrol.common import close, prepare_grid
from secontrol.devices.connector_device import ConnectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# Точность/таймауты
ARRIVAL_DISTANCE = 0.05
RC_STOP_TOLERANCE = 0.1
CHECK_INTERVAL = 0.2
AUTOPILOT_ARM_TIME = 2.0
MAX_FLIGHT_TIME = 240.0
SPEED_DISTANCE_THRESHOLD = 8.0


# ---- Утилиты векторов ----------------------------------------------------

def _vec(value: Sequence[float]) -> Tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError("Vector must have three components")
    return float(value[0]), float(value[1]), float(value[2])


def _parse_vector(value: object) -> Optional[Tuple[float, float, float]]:
    if isinstance(value, dict):
        keys = ("x", "y", "z")
        if all(k in value for k in keys):
            try:
                return _vec((value["x"], value["y"], value["z"]))
            except Exception:
                return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return _vec(value)
        except Exception:
            return None
    return None


def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-6:
        raise ValueError("Cannot normalize zero-length vector")
    return x / length, y / length, z / length


def _cross(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _add(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _sub(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _scale(v: Tuple[float, float, float], s: float) -> Tuple[float, float, float]:
    return v[0] * s, v[1] * s, v[2] * s


def _distance(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt(sum((ax - bx) ** 2 for ax, bx in zip(a, b)))


class Basis:
    def __init__(self, forward: Tuple[float, float, float], up: Tuple[float, float, float]):
        self.forward = _normalize(forward)
        raw_up = _normalize(up)
        right = _cross(self.forward, raw_up)
        if math.isclose(sum(c * c for c in right), 0.0, abs_tol=1e-6):
            raise ValueError("Forward and up vectors are collinear")
        self.right = _normalize(right)
        self.up = _normalize(_cross(self.right, self.forward))

    def to_world(self, local: Tuple[float, float, float]) -> Tuple[float, float, float]:
        x, y, z = local  # x=right, y=up, z=forward
        return (
            self.right[0] * x + self.up[0] * y + self.forward[0] * z,
            self.right[1] * x + self.up[1] * y + self.forward[1] * z,
            self.right[2] * x + self.up[2] * y + self.forward[2] * z,
        )


# ---- Извлечение позиций/ориентаций --------------------------------------

def _ensure_telemetry(device: BaseDevice) -> None:
    device.update()
    device.wait_for_telemetry()


def _block_position(block: BlockInfo | None) -> Optional[Tuple[float, float, float]]:
    if block is None:
        return None
    for attr in ("relative_to_grid_center", "local_position"):
        value = getattr(block, attr, None)
        if isinstance(value, tuple) and len(value) == 3:
            try:
                return _vec(value)
            except Exception:
                continue
    extra = getattr(block, "extra", {}) or {}
    pos = extra.get("position") or extra.get("localPosition")
    return _parse_vector(pos)


def _find_block_for_device(grid, device: BaseDevice) -> BlockInfo | None:
    # First, try device.device_id as EntityId of the block
    try:
        cid = int(device.device_id)
        block = grid.get_block(cid)
        if block is not None:
            return block
    except Exception:
        pass

    # Fallback to extra fields
    candidates: list[int] = []
    for key in ("blockId", "block_id", "entityId", "entity_id", "id"):
        raw = device.metadata.extra.get(key)
        if raw is None:
            continue
        try:
            candidates.append(int(raw))
        except Exception:
            continue
    for cid in candidates:
        block = grid.get_block(cid)
        if block is not None:
            return block
    return None


def _orientation_from_payload(payload: Dict[str, object] | None) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    if not isinstance(payload, dict):
        return None
    ori = payload.get("orientation") or payload
    if not isinstance(ori, dict):
        return None

    forward = _parse_vector(
        ori.get("forward")
        or ori.get("Forward")
        or ori.get("look")
        or ori.get("Look")
    )
    up = _parse_vector(ori.get("up") or ori.get("Up"))
    if forward and up:
        return _normalize(forward), _normalize(up)
    return None


def _device_world_position(device: BaseDevice) -> Optional[Tuple[float, float, float]]:
    telemetry = device.telemetry or {}
    pos = telemetry.get("worldPosition") or telemetry.get("position")
    if pos:
        return _parse_vector(pos)

    # Fallback: compute from grid blocks relative_to_grid_center
    block = _find_block_for_device(device.grid, device)
    if not block:
        return None
    local_pos = _block_position(block)
    if not local_pos:
        return None
    reference = _find_reference_device_for_grid_center(device.grid)
    if reference:
        grid_center, basis = _compute_grid_center_and_basis(reference)
        if grid_center and basis:
            return _device_world_from_grid(grid_center, local_pos, basis)
    # approximate for stationary grids using bounding boxes
    approx_center = _compute_approximate_grid_center(device.grid)
    if approx_center:
        # assume identity rotation
        basis = Basis((0,0,1), (0,1,0))
        return _device_world_from_grid(approx_center, local_pos, basis)
    return None


def _device_orientation(device: BaseDevice, block: BlockInfo | None = None) -> Optional[Basis]:
    orientation = _orientation_from_payload(device.telemetry)
    if not orientation and block is not None:
        orientation = _orientation_from_payload(getattr(block, "extra", {}) or {})
    if orientation:
        try:
            return Basis(*orientation)
        except Exception:
            return None
    return None


def _connector_forward(device: ConnectorDevice, block: BlockInfo | None) -> Optional[Tuple[float, float, float]]:
    orientation = _orientation_from_payload(device.telemetry)
    if orientation:
        return orientation[0]
    orientation = _orientation_from_payload(getattr(block, "extra", {}) or {})
    if orientation:
        return orientation[0]
    return None


def _find_reference_device_for_grid_center(grid):
    # Prefer devices with position in telemetry and orientation available via _device_orientation
    for pref_type in ['remote_control', 'cockpit']:
        for dev in grid.devices.values():
            tel = dev.telemetry or {}
            if (tel.get("position") or tel.get("worldPosition")) and _device_orientation(dev):
                return dev
    # Any with position and orientation
    for dev in grid.devices.values():
        tel = dev.telemetry or {}
        if (tel.get("position") or tel.get("worldPosition")) and _device_orientation(dev):
            return dev
    return None


def _compute_grid_center_and_basis(reference_device):
    world_pos = _device_world_position(reference_device)
    if not world_pos:
        return None, None
    block = _find_block_for_device(reference_device.grid, reference_device)
    if not block:
        return None, None
    local_pos = _block_position(block)
    if not local_pos:
        return None, None
    basis = _device_orientation(reference_device, block)
    if not basis:
        return None, None
    grid_center = _grid_center_world(world_pos, local_pos, basis)
    return grid_center, basis


def _compute_approximate_grid_center(grid):
    blocks = list(grid.blocks.values())
    if not blocks:
        return None
    # Find basis from any device
    grid_basis = None
    for dev in grid.devices.values():
        ori = _device_orientation(dev)
        if ori:
            grid_basis = ori
            break
    if not grid_basis:
        grid_basis = Basis((0,0,1), (0,1,0))  # identity
    candidates = []
    for block in blocks:
        if block.relative_to_grid_center and block.bounding_box:
            local = block.relative_to_grid_center
            local_dist = sum(c**2 for c in local)**0.5
            if 'min' in block.bounding_box and 'max' in block.bounding_box:
                min_bb = block.bounding_box['min']
                max_bb = block.bounding_box['max']
                block_center = tuple((m + M)/2 for m, M in zip(min_bb, max_bb))
                candidates.append((local_dist, local, block_center))
    if not candidates:
        return None
    # sort by local_dist
    candidates.sort(key=lambda x: x[0])
    _, local, block_center = candidates[0]
    # grid_center = block_center - grid_basis.to_world(local)
    grid_center = tuple(bc - wc for bc, wc in zip(block_center, grid_basis.to_world(local)))
    return grid_center


# ---- Геометрия стыковки ---------------------------------------------------

def _grid_center_world(rc_world: Tuple[float, float, float], rc_local: Tuple[float, float, float], basis: Basis) -> Tuple[float, float, float]:
    return _sub(rc_world, basis.to_world(rc_local))


def _device_world_from_grid(
    grid_center: Tuple[float, float, float],
    block_local: Tuple[float, float, float],
    basis: Basis,
) -> Tuple[float, float, float]:
    return _add(grid_center, basis.to_world(block_local))


# ---- Автопилот -----------------------------------------------------------

def _fly_to(
    remote: RemoteControlDevice,
    target_pos: Tuple[float, float, float],
    *,
    gps_name: str,
    speed_far: float,
    speed_near: float,
    dock: bool,
) -> None:
    _ensure_telemetry(remote)
    current_pos = _device_world_position(remote)
    if current_pos is None:
        raise RuntimeError("Remote Control telemetry does not contain position")
    initial_d = _distance(current_pos, target_pos)
    speed = float(speed_far if initial_d > SPEED_DISTANCE_THRESHOLD else speed_near)
    x, y, z = target_pos
    gps = f"GPS:{gps_name}:{x:.6f}:{y:.6f}:{z:.6f}:"

    print(
        f"[fly_to] target={gps}, dock={dock}, initial_distance={initial_d:.2f} m, "
        f"chosen_speed={speed:.2f}"
    )

    remote.set_mode("oneway")
    remote.goto(gps, speed=speed, gps_name=gps_name, dock=dock)

    arm_start = time.time()
    while time.time() - arm_start < AUTOPILOT_ARM_TIME:
        _ensure_telemetry(remote)
        time.sleep(0.1)

    start_time = time.time()
    last_print = start_time
    prev_d = None
    stuck_ticks = 0

    while True:
        _ensure_telemetry(remote)
        pos = _device_world_position(remote)
        if pos is None:
            raise RuntimeError("Remote Control telemetry lost position")
        d = _distance(pos, target_pos)
        autopilot_enabled = bool(remote.telemetry.get("autopilotEnabled", False))

        now = time.time()
        if now - start_time > MAX_FLIGHT_TIME:
            print(f"[fly_to] TIMEOUT after {MAX_FLIGHT_TIME} s, disabling autopilot")
            remote.disable()
            break

        if prev_d is not None and abs(prev_d - d) < 0.05:
            stuck_ticks += 1
        else:
            stuck_ticks = 0
        prev_d = d

        if now - last_print > 1.0:
            ship_speed = float(remote.telemetry.get("speed", 0.0))
            print(
                f"[fly_to] {gps_name}: distance={d:.2f} m, autopilot={'on' if autopilot_enabled else 'off'}, "
                f"speed={ship_speed:.2f} m/s, stuck_ticks={stuck_ticks}"
            )
            last_print = now

        if d <= ARRIVAL_DISTANCE:
            print(f"[fly_to] reached {gps_name} within {ARRIVAL_DISTANCE} m")
            if autopilot_enabled:
                remote.disable()
            break

        if not autopilot_enabled:
            if d <= RC_STOP_TOLERANCE:
                print(
                    f"[fly_to] RC disabled autopilot at {d:.3f} m (<= {RC_STOP_TOLERANCE} m), treating as arrived"
                )
            else:
                print(f"[fly_to] RC disabled autopilot early at {d:.3f} m")
            break

        if stuck_ticks > int(5 / CHECK_INTERVAL):
            print(f"[fly_to] movement stalled at {d:.3f} m, stopping")
            if autopilot_enabled:
                remote.disable()
            break

        time.sleep(CHECK_INTERVAL)


# ---- Выбор устройств -----------------------------------------------------

def _pick_connector(connectors: Iterable[ConnectorDevice], preferred: Optional[str]) -> Optional[ConnectorDevice]:
    connectors = list(connectors)
    if not connectors:
        return None
    if not preferred:
        return connectors[0]
    for conn in connectors:
        if conn.device_id == preferred or (conn.name and preferred.lower() in conn.name.lower()):
            return conn
    return connectors[0]


# ---- Основная логика -----------------------------------------------------

def _compute_ship_offset(
    remote: RemoteControlDevice,
    ship_connector: ConnectorDevice,
) -> Tuple[Tuple[float, float, float], Basis]:
    rc_block = _find_block_for_device(remote.grid, remote)
    conn_block = _find_block_for_device(remote.grid, ship_connector)
    rc_local = _block_position(rc_block)
    conn_local = _block_position(conn_block)

    if rc_local is None or conn_local is None:
        raise RuntimeError("Не удалось извлечь позиции RC/коннектора из gridinfo")

    _ensure_telemetry(remote)
    rc_world = _device_world_position(remote)
    if rc_world is None:
        raise RuntimeError("Remote Control telemetry does not contain position")

    basis = _device_orientation(remote, rc_block)
    if basis is None:
        raise RuntimeError("Не удалось получить ориентацию REMOTE CONTROL")

    grid_center = _grid_center_world(rc_world, rc_local, basis)
    ship_conn_world = _device_world_from_grid(grid_center, conn_local, basis)
    offset = _sub(ship_conn_world, rc_world)
    print(f"Ship RC @ {rc_world}, connector @ {ship_conn_world}, offset={offset}")
    return offset, basis


def _base_connector_world(base_connector: ConnectorDevice) -> Tuple[Optional[Tuple[float, float, float]], Optional[Tuple[float, float, float]]]:
    _ensure_telemetry(base_connector)
    world_pos = _device_world_position(base_connector)
    block = _find_block_for_device(base_connector.grid, base_connector)

    forward = _connector_forward(base_connector, block)
    if forward:
        forward = _normalize(forward)
    return world_pos, forward


def dock_to_base(
    base_grid_id: str,
    ship_grid_id: Optional[str],
    *,
    base_connector_hint: Optional[str],
    ship_connector_hint: Optional[str],
    approach: float,
    speed_far: float,
    speed_near: float,
) -> None:
    ship_grid = prepare_grid(ship_grid_id)
    base_grid = prepare_grid(ship_grid.redis, base_grid_id)

    try:
        ship_connector = _pick_connector(ship_grid.find_devices_by_type(ConnectorDevice), ship_connector_hint)
        if not ship_connector:
            print("На летящем гриде нет коннекторов")
            return
        base_connector = _pick_connector(base_grid.find_devices_by_type(ConnectorDevice), base_connector_hint)
        if not base_connector:
            print("На базе нет коннекторов")
            return

        remotes = ship_grid.find_devices_by_type(RemoteControlDevice)
        if not remotes:
            print("Remote Control не найден на летящем гриде")
            return
        remote: RemoteControlDevice = remotes[0]

        # First, compute and print positions without docking
        offset, basis = _compute_ship_offset(remote, ship_connector)
        base_pos, base_forward = _base_connector_world(base_connector)
        if base_pos is None:
            raise RuntimeError("Не удалось определить позицию коннектора базы")

        # Compute ship connector world position
        rc_world = _device_world_position(remote)
        ship_conn_world = _add(rc_world, offset)

        print(f"Ship RC @ {rc_world}")
        print(f"Ship connector @ {ship_conn_world}")
        print(f"Base connector @ {base_pos}")
        print(f"Offset = {offset}")
        print(f"Expected target RC (after alignment) = {base_pos}")

        print("Примите эту позицию (зацепитесь коннектором корабля к коннектору базы), затем нажмите Enter для продолжения...")
        # input("Нажмите Enter когда готовы: ")

        target_rc = _sub(base_pos, offset)

        print(f"Target RC position: {target_rc}")
        if base_forward:
            print(f"Base connector forward: {base_forward}")
        else:
            print("Forward вектор базы не найден, подлёт будет прямой")

        approach_point = None
        if base_forward and approach > 0:
            approach_point = _add(target_rc, _scale(base_forward, approach))
            print(f"Approach point: {approach_point} (distance {approach} m ahead)")

        if approach_point:
            _fly_to(remote, approach_point, gps_name="Approach", speed_far=speed_far, speed_near=speed_near, dock=False)
        _fly_to(remote, target_rc, gps_name="Dock", speed_far=speed_far, speed_near=speed_near, dock=False)
        print("Манёвр завершён")
    finally:
        close(ship_grid)
        close(base_grid)


# ---- Настройка параметров -------------------------------------------------

# Заполните значения для своей сцены. Все параметры можно оставить None, чтобы использовать
# значения по умолчанию (например, первый доступный корабль или первый коннектор).
DOCKING_PARAMS = {
    "base_grid_id": "DroneBase",  # обязательно: ID или имя грида базы
    "ship_grid_id": "Owl",  # опционально: ID или имя летящего грида
    "base_connector_hint": None,  # имя или ID коннектора на базе
    "ship_connector_hint": None,  # имя или ID коннектора корабля
    "approach": 1.0,  # дистанция точки подхода вдоль вектора базы (м)
    "speed_far": 12.0,  # скорость на удалении (м/с)
    "speed_near": 2.0,  # скорость при подлёте (м/с)
}


def main() -> None:
    params = dict(DOCKING_PARAMS)
    dock_to_base(**params)


if __name__ == "__main__":
    main()
