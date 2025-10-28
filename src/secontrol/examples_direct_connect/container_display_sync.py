"""Пример: вывод содержимого контейнеров на ближайшие дисплеи.

Скрипт перебирает все грузовые контейнеры на гриде, ищет для каждого ближайший
текстовый дисплей с тегом ``[cont]`` в названии и выводит на него список вещей.
После инициализации создаются подписки на телеметрию контейнеров, поэтому при
любом изменении содержимого дисплей автоматически обновляется.

Перед запуском убедитесь, что переменные окружения ``REDIS_URL`` (опционально),
``REDIS_USERNAME`` и ``SE_PLAYER_ID`` / ``SE_GRID_ID`` настроены согласно
описанию в ``README.md``. Пример запуска:

```
python -m secontrol.examples_direct_connect.container_display_sync
```
"""

from __future__ import annotations

import math
import re
import signal
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from secontrol.base_device import BlockInfo, Grid
from secontrol.common import close, prepare_grid
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.display_device import DisplayDevice


TAG_PATTERN = re.compile(r"\[(?P<tags>[^\[\]]+)\]")


def _normalize_tag(text: str | None) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", text).strip("_")
    if not cleaned:
        return None
    return cleaned.lower()


def _split_tags(chunk: str) -> Iterable[str]:
    for raw in re.split(r"[\s,;:/|]+", chunk):
        normalized = _normalize_tag(raw)
        if normalized:
            yield normalized


def _extract_tags_from_name(name: str | None) -> set[str]:
    tags: set[str] = set()
    if not name:
        return tags
    for match in TAG_PATTERN.finditer(name):
        tags.update(_split_tags(match.group("tags")))
    return tags


def _extract_tags_from_custom_data(device: DisplayDevice) -> set[str]:
    data = device.custom_data()
    if not data:
        return set()
    tags: set[str] = set()
    for raw_line in data.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip().lower() not in {"tag", "tags", "labels"}:
                continue
            tags.update(_split_tags(value))
        else:
            tags.update(_split_tags(line))
    return tags


def _resolve_block_for_device(grid: Grid, device: ContainerDevice | DisplayDevice) -> Optional[BlockInfo]:
    """Попробовать найти BlockInfo, соответствующий устройству."""

    candidates: list[int] = []
    extra = getattr(device, "metadata", None)
    extra_map = extra.extra if getattr(extra, "extra", None) else {}

    for key in ("blockId", "block_id", "entityId", "entity_id", "id"):
        value = extra_map.get(key)
        if value is None:
            continue
        try:
            candidates.append(int(value))
        except (TypeError, ValueError):
            continue

    try:
        candidates.append(int(device.device_id))
    except (TypeError, ValueError):
        pass

    block_info_entry = extra_map.get("block")
    if isinstance(block_info_entry, dict):
        maybe_id = block_info_entry.get("id") or block_info_entry.get("entityId")
        try:
            if maybe_id is not None:
                candidates.append(int(maybe_id))
        except (TypeError, ValueError):
            pass

    for candidate in candidates:
        block = grid.get_block(candidate)
        if block is not None:
            return block
    return None


def _extract_position(block: BlockInfo | None) -> Optional[Tuple[float, float, float]]:
    if block is None:
        return None
    for attr in ("relative_to_grid_center", "local_position"):
        value = getattr(block, attr, None)
        if isinstance(value, tuple) and len(value) == 3:
            return tuple(float(v) for v in value)
    extra = getattr(block, "extra", {}) or {}
    position = extra.get("position") or extra.get("localPosition")
    if isinstance(position, (list, tuple)) and len(position) == 3:
        try:
            return tuple(float(v) for v in position)
        except (TypeError, ValueError):
            return None
    return None


def _distance(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt(sum((ax - bx) ** 2 for ax, bx in zip(a, b)))


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_amount(value: float) -> str:
    if math.isclose(value % 1, 0.0, abs_tol=1e-6):
        return f"{int(round(value))}"
    if value >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:.2f}"


def _format_inventory(container: ContainerDevice) -> str:
    name = container.name or f"Контейнер #{container.device_id}"
    capacity = container.capacity()
    items = container.items()

    lines = [name]

    if capacity:
        current = _coerce_float(capacity.get("currentVolume"))
        maximum = _coerce_float(capacity.get("maxVolume"))
        fill_ratio = _coerce_float(capacity.get("fillRatio"))
        percent = fill_ratio * 100
        lines.append(
            f"Заполнено: {percent:.1f}% ({current:.3f}/{maximum:.3f} м³)"
        )

    if not items:
        lines.append("(пусто)")
        return "\n".join(lines)

    aggregated: Dict[str, float] = defaultdict(float)
    for item in items:
        label = item.display_name or item.subtype or item.type or "?"
        aggregated[label] += float(item.amount)

    for label in sorted(aggregated):
        lines.append(f"{label}: {_format_amount(aggregated[label])}")

    return "\n".join(lines)


@dataclass
class Assignment:
    container: ContainerDevice
    display: DisplayDevice
    distance: float


def _device_label(device: ContainerDevice | DisplayDevice) -> str:
    base = device.name or getattr(device, "device_type", "device")
    return f"{base} (#{device.device_id})"


class ContainerDisplayManager:
    """Связывает контейнеры с дисплеями и поддерживает вывод инвентаря."""

    def __init__(self, grid: Grid, *, tag: str = "cont") -> None:
        self.grid = grid
        self.tag = tag
        self._assignments: Dict[str, Assignment] = {}
        self._callbacks: Dict[str, Callable[[ContainerDevice, Dict[str, Any], str], None]] = {}
        self._grid_listener = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._grid_listener = self._on_devices_event
        self.grid.on("devices", self._grid_listener)
        self._refresh_assignments()

    # ------------------------------------------------------------------
    def stop(self) -> None:
        if self._grid_listener is not None:
            try:
                self.grid.off("devices", self._grid_listener)
            except Exception:
                pass
            self._grid_listener = None
        with self._lock:
            for container_id in list(self._assignments):
                assignment = self._assignments.pop(container_id)
                self._detach_container(container_id)
                self._clear_display(assignment.display)
        
    # ------------------------------------------------------------------
    def _on_devices_event(self, grid: Grid, payload, source: str) -> None:  # noqa: D401 - simple proxy
        self._refresh_assignments()

    # ------------------------------------------------------------------
    def _refresh_assignments(self) -> None:
        with self._lock:
            containers = self._collect_containers()
            displays = self._collect_displays()
            if not containers or not displays:
                for container_id in list(self._assignments):
                    existing = self._assignments.pop(container_id)
                    self._detach_container(container_id)
                    self._clear_display(existing.display)
                    print(
                        f"{_device_label(existing.display)} освобождён от "
                        f"{_device_label(existing.container)}",
                    )
                return

            new_assignments: Dict[str, Assignment] = {}
            available = list(displays)

            for container, position in containers:
                best_display = None
                best_distance = math.inf
                best_index = -1
                for index, (display, dpos) in enumerate(available):
                    dist = _distance(position, dpos)
                    if dist < best_distance:
                        best_distance = dist
                        best_display = display
                        best_index = index
                if best_display is None:
                    continue
                available.pop(best_index)
                new_assignments[container.device_id] = Assignment(
                    container=container,
                    display=best_display,
                    distance=best_distance,
                )
                if not available:
                    break

            # Отключаем старые
            for container_id in list(self._assignments):
                if container_id not in new_assignments:
                    existing = self._assignments.pop(container_id)
                    self._detach_container(container_id)
                    self._clear_display(existing.display)
                    print(
                        f"{_device_label(existing.display)} освобождён от "
                        f"{_device_label(existing.container)}",
                    )

            # Подключаем новые и обновляем существующие
            for container_id, assignment in new_assignments.items():
                previous = self._assignments.get(container_id)
                self._assignments[container_id] = assignment
                if previous and previous.display.device_id == assignment.display.device_id:
                    self._render_container(assignment.container)
                else:
                    self._detach_container(container_id)
                    self._attach_container(assignment)
                    print(
                        f"{_device_label(assignment.display)} ⇐ "
                        f"{_device_label(assignment.container)} "
                        f"({assignment.distance:.2f} м)",
                    )

    # ------------------------------------------------------------------
    def _collect_containers(self) -> list[tuple[ContainerDevice, Tuple[float, float, float]]]:
        containers: list[tuple[ContainerDevice, Tuple[float, float, float]]] = []
        for device in self.grid.find_devices_by_type(ContainerDevice):
            block = _resolve_block_for_device(self.grid, device)
            position = _extract_position(block)
            if position is None:
                continue
            containers.append((device, position))
        containers.sort(key=lambda pair: pair[0].device_id)
        return containers

    # ------------------------------------------------------------------
    def _collect_displays(self) -> list[tuple[DisplayDevice, Tuple[float, float, float]]]:
        displays: list[tuple[DisplayDevice, Tuple[float, float, float]]] = []
        for device in self.grid.find_devices_by_type(DisplayDevice):
            tags = _extract_tags_from_name(device.name)
            tags.update(_extract_tags_from_custom_data(device))
            if self.tag not in tags:
                continue
            block = _resolve_block_for_device(self.grid, device)
            position = _extract_position(block)
            if position is None:
                continue
            displays.append((device, position))
        displays.sort(key=lambda pair: pair[0].device_id)
        return displays

    # ------------------------------------------------------------------
    def _attach_container(self, assignment: Assignment) -> None:
        container = assignment.container
        display = assignment.display

        def _on_telemetry(device: ContainerDevice, telemetry, source: str) -> None:  # noqa: ANN001
            self._render_container(device)

        container.on("telemetry", _on_telemetry)
        self._callbacks[container.device_id] = _on_telemetry

        if container.telemetry:
            self._render_container(container)
        else:
            try:
                display.set_text(f"{container.name or 'Контейнер'}\nЗагрузка...")
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _detach_container(self, container_id: str) -> None:
        callback = self._callbacks.pop(container_id, None)
        if not callback:
            return
        device = self.grid.get_device(container_id)
        if isinstance(device, ContainerDevice):
            try:
                device.off("telemetry", callback)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _render_container(self, container: ContainerDevice) -> None:
        assignment = self._assignments.get(container.device_id)
        if not assignment:
            return
        display = assignment.display
        text = _format_inventory(container)
        try:
            display.set_text(text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _clear_display(self, display: DisplayDevice) -> None:
        try:
            display.set_text("Нет привязанного контейнера")
        except Exception:
            pass


def main() -> int:
    try:
        grid = prepare_grid()
    except Exception as exc:  # pragma: no cover - defensive for runtime usage
        print(f"Не удалось подготовить грид: {exc}", file=sys.stderr)
        return 1

    manager = ContainerDisplayManager(grid)

    def _handle_stop(signum, frame):  # noqa: ANN001
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    try:
        manager.start()
        print("Сопоставление контейнеров и дисплеев запущено. Нажмите Ctrl+C для выхода.")
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nОстановка...")
    finally:
        manager.stop()
        close(grid)
    return 0


if __name__ == "__main__":  # pragma: no cover - ручной запуск
    sys.exit(main())

