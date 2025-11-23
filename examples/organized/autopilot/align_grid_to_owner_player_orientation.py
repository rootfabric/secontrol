"""Доворачивание грида под ориентацию владельца, считанную радаром.

Сценарий:
- Ищем ближайшего игрока-владельца по данным радара (ore_detector).
- Забираем его forward/up из поля orientation контакта.
- Через гироскопы плавно доворачиваем грид, пока его оси совпадут с осями игрока.

Подсказки:
- Пример обновления ориентации гироскопами взят из скриптов в ``examples/organized/autopilot``.
- Отслеживание игрока реализовано аналогично ``rover_track_player_move_to_point.py``.
"""

from __future__ import annotations

import time
from typing import Iterable, Sequence, Tuple

from secontrol.common import close, prepare_grid
from secontrol.devices.gyro_device import GyroDevice
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice

# Параметры управления
SCAN_RADIUS = 300.0
ALIGN_TOLERANCE_DOT = 0.998
ALIGN_GAIN = 0.6
ALIGN_SLEEP = 0.1
ALIGN_TIMEOUT = 20.0


def vec_from_orientation(d: dict) -> Tuple[float, float, float]:
    return float(d["x"]), float(d["y"]), float(d["z"])


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def cross(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (
        float(a[1] * b[2] - a[2] * b[1]),
        float(a[2] * b[0] - a[0] * b[2]),
        float(a[0] * b[1] - a[1] * b[0]),
    )


def clamp(x: float, min_value: float, max_value: float) -> float:
    return float(max(min_value, min(max_value, x)))


def normalize(v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    length = (x * x + y * y + z * z) ** 0.5
    if length < 1e-6:
        raise ValueError("cannot normalize zero-length vector")
    return x / length, y / length, z / length


def get_remote_basis(remote: RemoteControlDevice) -> Tuple[Tuple[float, float, float], ...]:
    """Возвращает forward, up, right из телеметрии REMOTE CONTROL."""

    ori = remote.telemetry.get("orientation") or {}
    f_raw = ori.get("forward")
    u_raw = ori.get("up")
    r_raw = ori.get("right")
    l_raw = ori.get("left")

    if not f_raw or not u_raw:
        raise RuntimeError("Remote telemetry does not contain orientation.forward/up")

    forward = normalize(vec_from_orientation(f_raw))
    up = normalize(vec_from_orientation(u_raw))

    if r_raw:
        right = normalize(vec_from_orientation(r_raw))
    elif l_raw:
        lx, ly, lz = vec_from_orientation(l_raw)
        right = normalize((-lx, -ly, -lz))
    else:
        right = normalize(cross(forward, up))

    return forward, up, right


def _orthonormal_from_forward(forward: Tuple[float, float, float]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Строит ортонормированный forward/up только по направлению forward.

    Используем фиксированный опорный вектор (мировой Y), а если forward почти
    параллелен ему, берём мировой X. Это позволяет обойтись без гравитации в
    контакте игрока.
    """

    f = normalize(forward)
    ref = (0.0, 1.0, 0.0) if abs(dot(f, (0.0, 1.0, 0.0))) < 0.99 else (1.0, 0.0, 0.0)
    right = normalize(cross(ref, f))
    up = normalize(cross(f, right))
    return f, up


def extract_player_orientation(contact: dict) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]] | None:
    """Пытается вытащить forward/up из контакта игрока.

    В данных радара встречаются варианты:
    - ``orientation.forward``/``orientation.up`` (dict с x/y/z),
    - ``forward``/``up`` как списки координат,
    - ``headForward`` вместо ``forward`` (когда игрок смотрит в сторону).

    Если up недоступен или нулевой, строим его из forward без опоры на
    гравитацию.
    """

    orientation = contact.get("orientation") if isinstance(contact.get("orientation"), dict) else None

    forward_raw = None
    up_raw = None

    if orientation:
        forward_raw = orientation.get("forward")
        up_raw = orientation.get("up")

    forward_raw = forward_raw or contact.get("forward") or contact.get("headForward")
    up_raw = up_raw or contact.get("up") or contact.get("headUp")

    if isinstance(forward_raw, dict):
        forward_raw = vec_from_orientation(forward_raw)
    if isinstance(up_raw, dict):
        up_raw = vec_from_orientation(up_raw)

    if not forward_raw:
        return None

    try:
        forward = normalize(forward_raw)
    except ValueError:
        return None

    up: Tuple[float, float, float] | None = None
    if up_raw:
        try:
            up = normalize(up_raw)
        except ValueError:
            up = None

    if up is None:
        forward, up = _orthonormal_from_forward(forward)

    return forward, up


def correct_orientation(
    remote: RemoteControlDevice,
    gyros: Iterable[GyroDevice],
    target_forward: Sequence[float],
    target_up: Sequence[float],
    *,
    tolerance_dot: float = ALIGN_TOLERANCE_DOT,
    gain: float = ALIGN_GAIN,
    max_time: float = ALIGN_TIMEOUT,
    sleep_interval: float = ALIGN_SLEEP,
) -> None:
    """Плавно доворачивает грид к заданным осям с помощью гироскопов."""

    gyro_list = list(gyros)
    if not gyro_list:
        print("[orientation] No gyros found, skipping alignment")
        return

    start_time = time.time()
    target_forward = normalize(tuple(target_forward))
    target_up = normalize(tuple(target_up))

    def _stop_gyros() -> None:
        for g in gyro_list:
            g.set_override(pitch=0.0, yaw=0.0, roll=0.0)

    try:
        while True:
            remote.update()
            remote.wait_for_telemetry()

            current_forward, current_up, current_right = get_remote_basis(remote)

            df = dot(current_forward, target_forward)
            du = dot(current_up, target_up)
            if df >= tolerance_dot and du >= tolerance_dot:
                print(f"[orientation] aligned: dotF={df:.4f}, dotU={du:.4f}")
                break

            err_f = cross(current_forward, target_forward)
            err_u = cross(current_up, target_up)

            err_vec = (
                err_f[0] + err_u[0],
                err_f[1] + err_u[1],
                err_f[2] + err_u[2],
            )

            yaw = clamp(dot(err_vec, current_up) * gain, -1.0, 1.0)
            pitch = clamp(dot(err_vec, current_right) * gain, -1.0, 1.0)
            roll = clamp(dot(err_vec, current_forward) * gain, -1.0, 1.0)

            for gyro in gyro_list:
                gyro.set_override(pitch=pitch, yaw=yaw, roll=roll)

            if time.time() - start_time > max_time:
                print(
                    f"[orientation] timeout after {max_time} s, "
                    f"last dots: dotF={df:.4f}, dotU={du:.4f}"
                )
                break

            time.sleep(sleep_interval)
    finally:
        _stop_gyros()


def main() -> None:
    grid = prepare_grid()

    try:
        detectors = grid.find_devices_by_type(OreDetectorDevice)
        if not detectors:
            print("На гриде не найдено ни одного детектора руды (ore_detector).")
            return
        detector = detectors[0]
        print(f"Найден радар device_id={detector.device_id} name={detector.name!r}")

        remotes = grid.find_devices_by_type(RemoteControlDevice)
        if not remotes:
            print("Не найдено блока REMOTE CONTROL для чтения ориентации грида.")
            return
        remote = remotes[0]
        print(f"Используется REMOTE CONTROL {remote.name!r} (id={remote.device_id})")

        gyros = grid.find_devices_by_type(GyroDevice)
        if not gyros:
            print("Не найдено гироскопов на гриде.")
            return
        print(f"Найдено гироскопов: {len(gyros)}")

        print("Сканируем игрока-владельца и доворaчиваемся под его ориентацию (Ctrl+C для выхода)...")

        last_target: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None

        while True:
            detector.scan(include_players=True, include_grids=False, radius=SCAN_RADIUS)

            contacts = detector.contacts()
            player_forward_up = None
            for contact in contacts:
                if contact.get("type") != "player":
                    continue
                owner_id = str(contact.get("ownerId"))
                if owner_id != str(grid.owner_id):
                    continue

                player_forward_up = extract_player_orientation(contact)
                if player_forward_up:
                    break

            if not player_forward_up:
                print("Игрок-владелец не найден или нет ориентации в контакте.")
                time.sleep(1.0)
                continue

            if last_target != player_forward_up:
                print(
                    "Ориентация игрока обновлена, доворачиваем грид...",
                    f"forward={player_forward_up[0]}, up={player_forward_up[1]}",
                )
                correct_orientation(
                    remote,
                    gyros,
                    target_forward=player_forward_up[0],
                    target_up=player_forward_up[1],
                )
                last_target = player_forward_up

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("Выход...")
    finally:
        close(grid)


if __name__ == "__main__":
    main()
