"""Пример работы с радаром (детектор руды) с конфигом.

- Находит детектор руды на выбранном гриде
- Отправляет команду сканирования ("scan") по расписанию
- Подписывается на телеметрию и печатает изменения (ревизия, контакты, клетки руды)

Конфиг задаётся прямо в коде в словаре `CONFIG` (см. начало файла) —
удобно быстро менять параметры без внешних файлов/переменных окружения.

Поддерживаемые ключи:
- includePlayers (bool, по умолчанию true)
- includeGrids (bool, по умолчанию true)
- includeVoxels (bool, по умолчанию true)
- radius (float), cellSize (float)
- voxelScanHz (float)
- voxelStep / voxelStepMultiplier (int)
- fullSolidScan / includeStoneCells (bool)
- budgetMsPerTick (float)
- voxelMinContent (int)
- scanIntervalSec (float, период повторного scan; по умолчанию 2.0)
- select: { deviceId: int | deviceName: str } — выбор конкретного датчика

Дополнительные параметры политики (если поддерживаются сервером):
- contactsHz (float)
- fullScanHz (float)
- losScanHz (float)
- maxLosRaysPerTick (int)
- noDetectorCapMin (float)
- noDetectorCapMax (float)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from secontrol.common import close, prepare_grid

DEFAULT_CONFIG: Dict[str, Any] = {
    "includePlayers": True,
    "includeGrids": True,
    "includeVoxels": True,
    "scanIntervalSec": 2.0,
}

# Редактируйте этот словарь для настройки поведения радара
CONFIG: Dict[str, Any] = {
    # Базовые флаги
    "includePlayers": True,
    "includeGrids": True,
    "includeVoxels": True,

    # Параметры сканирования
    # Пример: 200.0 (если устройство не отклонит/не заклампит)
    "radius": 500,
    # Пример: 10.0
    "cellSize": 1,

    # Растяжка вокселей и плотность
    # Пример: 0.2 (раз в 5 сек)
    "voxelScanHz": None,
    # Пример: 1 (плотная), 2/3 — грубее/быстрее
    "voxelStep": None,
    # Полный камень / мягкая фильтрация
    "fullSolidScan": None,
    # Альяс для совместимости
    "includeStoneCells": True,
    # Пример: 1.0 (мс на тик)
    "budgetMsPerTick": 5,
    # Пример: 1 (мягкая фильтрация границ)
    "voxelMinContent": None,

    # Контакты/сканеры
    "contactsHz": None,
    "fullScanHz": None,
    "losScanHz": None,
    "maxLosRaysPerTick": None,
    "noDetectorCapMin": None,
    "noDetectorCapMax": None,

    # Период повтора scan (секунды)
    "scanIntervalSec": 1.0,

    # Выбор устройства: {"deviceId": 123} или {"deviceName": "Ore Detector"}
    "select": {},
}


# без нагрузки
# CONFIG: Dict[str, Any] = {
# "includePlayers": True,
# "includeGrids": True,
# "includeVoxels": True,
# "radius": 75,
# "cellSize": 16,
# "voxelScanHz": 0.1,
# "voxelStep": 3,
# "fullSolidScan": False,
# "includeStoneCells": False,
# "budgetMsPerTick": 5.0,
# "voxelMinContent": 1,
# "contactsHz": 0.2,
# "fullScanHz": 0.5,
# "losScanHz": 10,
# "maxLosRaysPerTick": 8,
# "noDetectorCapMin": 150,
# "noDetectorCapMax": 200,
# "scanIntervalSec": 5.0,
# "select": {}
# }


def _coerce_bool(x: Any, default: Optional[bool] = None) -> Optional[bool]:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        v = x.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(x: Any) -> Optional[int]:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_float(x: Any) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    try:
        cfg.update(CONFIG)
    except Exception:
        pass
    return cfg


def _select_device_from_config(grid, cfg: Dict[str, Any]):
    sel = cfg.get("select") or {}
    if isinstance(sel, dict):
        dev_id = _coerce_int(sel.get("deviceId"))
        if dev_id is not None:
            dev = grid.get_device_num(dev_id)
            if dev is not None:
                return dev
        name = sel.get("deviceName") or sel.get("name")
        if isinstance(name, str) and name.strip():
            matches = grid.find_devices_by_name(name)
            if matches:
                for d in matches:
                    if getattr(d, "device_type", "") == "ore_detector":
                        return d
                return matches[0]
    detectors = grid.find_devices_by_type("ore_detector")
    return detectors[0] if detectors else None


def _send_scan(
    device,
    *,
    include_players: bool = True,
    include_grids: bool = True,
    include_voxels: bool = True,
    radius: Optional[float] = None,
    cell_size: Optional[float] = None,
    voxel_scan_hz: Optional[float] = None,
    voxel_step: Optional[int] = None,
    include_stone_cells: Optional[bool] = None,
    budget_ms_per_tick: Optional[float] = None,
    voxel_min_content: Optional[int] = None,
    contacts_hz: Optional[float] = None,
    full_scan_hz: Optional[float] = None,
    los_scan_hz: Optional[float] = None,
    max_los_rays_per_tick: Optional[int] = None,
    no_detector_cap_min: Optional[float] = None,
    no_detector_cap_max: Optional[float] = None,
) -> int:
    """Отправляет команду сканирования в канал устройства."""

    state: Dict[str, Any] = {
        "includePlayers": bool(include_players),
        "includeGrids": bool(include_grids),
        "includeVoxels": bool(include_voxels),
    }
    if radius is not None:
        state["radius"] = float(radius)
    if cell_size is not None:
        state["cellSize"] = float(cell_size)
    if voxel_scan_hz is not None:
        state["voxelScanHz"] = float(voxel_scan_hz)
    if voxel_step is not None:
        # Плагин принимает voxelStep|voxel_step|voxelStepMultiplier — используем краткое имя
        try:
            state["voxelStep"] = int(voxel_step)
        except (TypeError, ValueError):
            pass
    if include_stone_cells is not None:
        # Поддерживается также includeStoneCells/stoneCells — отправим fullSolidScan=true/false
        state["fullSolidScan"] = bool(include_stone_cells)
        # продублируем совместимые ключи на всякий случай
        state["includeStoneCells"] = bool(include_stone_cells)
    if budget_ms_per_tick is not None:
        state["budgetMsPerTick"] = float(budget_ms_per_tick)
    if voxel_min_content is not None:
        try:
            state["voxelMinContent"] = int(voxel_min_content)
        except (TypeError, ValueError):
            pass
    if contacts_hz is not None:
        state["contactsHz"] = float(contacts_hz)
    if full_scan_hz is not None:
        state["fullScanHz"] = float(full_scan_hz)
    if los_scan_hz is not None:
        state["losScanHz"] = float(los_scan_hz)
    if max_los_rays_per_tick is not None:
        try:
            state["maxLosRaysPerTick"] = int(max_los_rays_per_tick)
        except (TypeError, ValueError):
            pass
    if no_detector_cap_min is not None:
        state["noDetectorCapMin"] = float(no_detector_cap_min)
    if no_detector_cap_max is not None:
        state["noDetectorCapMax"] = float(no_detector_cap_max)

    payload: Dict[str, Any] = {
        "cmd": "scan",
        "targetId": int(device.device_id),
        "state": state,
    }
    if getattr(device, "name", None):
        payload["targetName"] = device.name
    return device.send_command(payload)


def _pick_radar_dict(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Выбирает словарь радара из телеметрии, учитывая разные схемы."""

    # Обычный случай: внутри поля radar
    rad = data.get("radar")
    if isinstance(rad, dict):
        return rad
    # Альтернативно некоторые плагины складывают поля прямо в корень
    root_keys = set(data.keys())
    if {"contacts", "cellSize"} & root_keys:
        return data
    if {"contacts", "radius"} & root_keys:
        return data
    # Возможные обёртки
    alt = data.get("voxel") or data.get("ore") or data.get("map")
    if isinstance(alt, dict):
        return alt
    return None


def _extract_ore_cells(radar: Dict[str, Any]) -> tuple[list[dict], int]:
    """Извлекает список ячеек руды и флаг усечения из разных возможных полей."""

    cells: list[dict] = []
    truncated = 0

    # Основные варианты
    raw = radar.get("oreCells")
    if isinstance(raw, list):
        cells = [c for c in raw if isinstance(c, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("cells"), list):
        cells = [c for c in raw.get("cells", []) if isinstance(c, dict)]

    # Альтернативные имена/размещения
    if not cells:
        for key in ("ore_cells", "cells", "ores"):
            alt = radar.get(key)
            if isinstance(alt, list):
                cells = [c for c in alt if isinstance(c, dict)]
                break
            if isinstance(alt, dict) and isinstance(alt.get("cells"), list):
                cells = [c for c in alt.get("cells", []) if isinstance(c, dict)]
                break

    # Признак усечения
    trunc = radar.get("oreCellsTruncated")
    try:
        truncated = int(trunc) if trunc is not None else 0
    except (TypeError, ValueError):
        truncated = 0

    return cells, truncated


def main() -> None:
    client, grid = prepare_grid()
    try:
        # Загружаем конфиг и выбираем датчик
        cfg = _load_config()
        device = _select_device_from_config(grid, cfg)
        if device is None:
            print("На гриде не найдено ни одного детектора руды (ore_detector).")
            return
        print(f"Найден радар device_id={device.device_id} name={device.name!r}")
        print(f"Ключ телеметрии: {device.telemetry_key}")

        # Читаем параметры сканирования из конфига
        include_players = _coerce_bool(cfg.get("includePlayers"), True)
        include_grids = _coerce_bool(cfg.get("includeGrids"), True)
        include_voxels = _coerce_bool(cfg.get("includeVoxels"), True)
        radius = _coerce_float(cfg.get("radius"))
        cell_size = _coerce_float(cfg.get("cellSize"))
        voxel_scan_hz = _coerce_float(cfg.get("voxelScanHz"))
        voxel_step = _coerce_int(cfg.get("voxelStep") if cfg.get("voxelStep") is not None else cfg.get("voxelStepMultiplier"))
        include_stone_cells = _coerce_bool(
            cfg.get("fullSolidScan") if cfg.get("fullSolidScan") is not None else cfg.get("includeStoneCells"),
            None,
        )
        budget_ms_per_tick = _coerce_float(cfg.get("budgetMsPerTick"))
        voxel_min_content = _coerce_int(cfg.get("voxelMinContent"))
        scan_interval = _coerce_float(cfg.get("scanIntervalSec")) or DEFAULT_CONFIG["scanIntervalSec"]
        contacts_hz = _coerce_float(cfg.get("contactsHz"))
        full_scan_hz = _coerce_float(cfg.get("fullScanHz"))
        los_scan_hz = _coerce_float(cfg.get("losScanHz"))
        max_los_rays_per_tick = _coerce_int(cfg.get("maxLosRaysPerTick"))
        no_detector_cap_min = _coerce_float(cfg.get("noDetectorCapMin"))
        no_detector_cap_max = _coerce_float(cfg.get("noDetectorCapMax"))

        # Подписываемся на изменения телеметрии конкретного устройства
        last_rev: Optional[int] = None
        last_ore_count: Optional[int] = None
        last_truncated: Optional[int] = None
        last_done: Optional[bool] = None
        last_contacts_count: Optional[int] = None
        cached_ore_cells: list[dict] = []
        cached_ore_count: int = 0

        def _on_update(_key: str, payload: Any, event: str) -> None:
            nonlocal last_rev
            if event == "del":
                print("[radar] telemetry deleted")
                return

            data: Dict[str, Any] | None = None
            if isinstance(payload, dict):
                data = payload
            elif isinstance(payload, str):
                text = payload.strip()
                if text:
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = None

            if not isinstance(data, dict):
                return

            radar = _pick_radar_dict(data)
            contacts = radar.get("contacts", []) if isinstance(radar, dict) else []
            ore_cells, truncated = _extract_ore_cells(radar or {})

            # Ревизия/время
            rev_val = radar.get("revision") if radar else None
            try:
                rev = int(rev_val) if rev_val is not None else None
            except (TypeError, ValueError):
                rev = None

            
            cell = radar.get("cellSize") if isinstance(radar, dict) else None
            radius_val = radar.get("radius") if isinstance(radar, dict) else None
            ts_ms = radar.get("tsMs") if isinstance(radar, dict) else None
            los_sec = radar.get("lastLosUpdateSec") if isinstance(radar, dict) else None
            # Политика может быть как в корне радара, так и внутри policy{}
            policy = radar.get("policy") if isinstance(radar, dict) else None
            voxel_interval = (
                (radar.get("voxelIntervalSec") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("voxelIntervalSec")
            )
            full_interval = (
                (radar.get("fullScanIntervalSec") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("fullScanIntervalSec")
            )
            los_interval = (
                (radar.get("losIntervalSec") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("losIntervalSec")
            )
            voxel_step_mult = (
                (radar.get("voxelStepMultiplier") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("voxelStepMultiplier")
            )
            voxel_include_stone = (
                (radar.get("voxelIncludeStoneCells") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("voxelIncludeStoneCells")
            )
            budget_ms = (
                (radar.get("budgetMsPerTick") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("budgetMsPerTick")
            )
            max_radius = (
                (radar.get("maxRadius") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("maxRadius")
            )
            los_rays = (
                (radar.get("losRaysPerTick") if isinstance(radar, dict) else None)
                if not isinstance(policy, dict) else policy.get("losRaysPerTick")
            )
            ore_count_field = None
            try:
                ore_count_field = int(radar.get("oreCellCount")) if isinstance(radar, dict) and radar.get("oreCellCount") is not None else None
            except (TypeError, ValueError):
                ore_count_field = None

            # Готовность и вычисление счётчиков
            done = bool(radar.get("done")) if isinstance(radar, dict) and "done" in radar else None
            scan_state = data.get("scan") if isinstance(data.get("scan"), dict) else {}
            scan_include_voxels = scan_state.get("includeVoxels") if isinstance(scan_state, dict) else None
            scan_in_progress = scan_state.get("inProgress") if isinstance(scan_state, dict) else None
            contacts_count = len(contacts) if isinstance(contacts, list) else 0
            ore_effective = (ore_count_field if (ore_count_field is not None and not ore_cells) else len(ore_cells))

            # Кэшируем последнюю известную руду и используем кэш при contact-only ревизиях
            used_cached = False
            if isinstance(scan_include_voxels, bool) and not scan_include_voxels:
                if ore_effective == 0 and cached_ore_count > 0:
                    ore_effective = cached_ore_count
                    if not ore_cells and cached_ore_cells:
                        ore_cells = cached_ore_cells
                    used_cached = True
            else:
                # Если в этом снимке есть руда, обновим кэш
                if ore_effective > 0:
                    cached_ore_count = ore_effective
                    cached_ore_cells = ore_cells[:]

            # Печатаем при любом изменении значимых полей (даже если rev тот же)
            should_print = (
                (rev != last_rev) or
                (ore_effective != (last_ore_count if last_ore_count is not None else -1)) or
                (truncated != (last_truncated if last_truncated is not None else -1)) or
                (done != last_done) or
                (contacts_count != (last_contacts_count if last_contacts_count is not None else -1))
            )
            if not should_print:
                return
            last_rev = rev
            last_ore_count = ore_effective
            last_truncated = truncated
            last_done = done
            last_contacts_count = contacts_count

            print(
                "[radar]",
                f"rev={rev}",
                f"contacts={contacts_count}",
                f"oreCells={ore_effective}{' [cached]' if used_cached else ''}"
                + (f" (truncated {truncated})" if truncated else ""),
                f"cellSize={cell}",
                f"radius={radius_val}",
                f"tsMs={ts_ms}",
                f"los={los_sec}",
                f"scan.inProgress={scan_in_progress}",
                f"scan.includeVoxels={scan_include_voxels}",
                f"fullIntervalSec={full_interval}",
                f"losIntervalSec={los_interval}",
                f"voxelIntervalSec={voxel_interval}",
                f"voxelStepMultiplier={voxel_step_mult}",
                f"voxelIncludeStoneCells={voxel_include_stone}",
                f"budgetMsPerTick={budget_ms}",
                f"maxRadius={max_radius}",
                f"losRaysPerTick={los_rays}",
            )

            # Небольшой превью первых 3 ячеек, чтобы визуально подтвердить наличие
            if ore_cells:
                preview = []
                for c in ore_cells[:3]:
                    ore = c.get("ore") or c.get("material") or "?"
                    content = c.get("content")
                    idx = c.get("index")
                    preview.append(f"{ore}@{idx}:{content}")
                print("[radar] ore preview:", ", ".join(preview))
            elif ore_count_field:
                print("[radar] note: oreCells list отсутствует, но oreCellCount=", ore_count_field)

        sub = client.subscribe_to_key(device.telemetry_key, _on_update)

        # Отправляем первое сканирование и затем периодически повторяем
        _send_scan(
            device,
            include_players=bool(include_players if include_players is not None else True),
            include_grids=bool(include_grids if include_grids is not None else True),
            include_voxels=bool(include_voxels if include_voxels is not None else True),
            radius=radius,
            cell_size=cell_size,
            voxel_scan_hz=voxel_scan_hz,
            voxel_step=voxel_step,
            include_stone_cells=include_stone_cells,
            budget_ms_per_tick=budget_ms_per_tick,
            voxel_min_content=voxel_min_content,
            contacts_hz=contacts_hz,
            full_scan_hz=full_scan_hz,
            los_scan_hz=los_scan_hz,
            max_los_rays_per_tick=max_los_rays_per_tick,
            no_detector_cap_min=no_detector_cap_min,
            no_detector_cap_max=no_detector_cap_max,
        )

        print("Скан отправлен. Ждём обновления телеметрии... (Ctrl+C для выхода)")

        try:
            # Лёгкий цикл с периодическим повтором
            while True:
                time.sleep(float(scan_interval))
                print("scan")
                _send_scan(
                    device,
                    include_players=bool(include_players if include_players is not None else True),
                    include_grids=bool(include_grids if include_grids is not None else True),
                    include_voxels=bool(include_voxels if include_voxels is not None else True),
                    radius=radius,
                    cell_size=cell_size,
                    voxel_scan_hz=voxel_scan_hz,
                    voxel_step=voxel_step,
                    include_stone_cells=include_stone_cells,
                    budget_ms_per_tick=budget_ms_per_tick,
                    voxel_min_content=voxel_min_content,
                    contacts_hz=contacts_hz,
                    full_scan_hz=full_scan_hz,
                    los_scan_hz=los_scan_hz,
                    max_los_rays_per_tick=max_los_rays_per_tick,
                    no_detector_cap_min=no_detector_cap_min,
                    no_detector_cap_max=no_detector_cap_max,
                )
        except KeyboardInterrupt:
            pass
        finally:
            try:
                sub.close()
            except Exception:
                pass
    finally:
        close(client, grid)


if __name__ == "__main__":
    main()
