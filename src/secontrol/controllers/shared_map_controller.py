from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from secontrol.common import resolve_owner_id
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.redis_client import RedisEventClient
from secontrol.tools.navigation_tools import get_world_position


Point3D = Tuple[float, float, float]


def _normalize_point(point: Sequence[float]) -> Point3D:
    if len(point) != 3:
        raise ValueError(f"Point must have 3 coordinates, got {point}")
    return (float(point[0]), float(point[1]), float(point[2]))


@dataclass
class SharedMapData:
    voxels: List[Point3D] = field(default_factory=list)
    visited: List[Point3D] = field(default_factory=list)
    paths: Dict[str, List[Point3D]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any] | None) -> "SharedMapData":
        payload = payload or {}
        return cls(
            voxels=[_normalize_point(p) for p in payload.get("voxels", [])],
            visited=[_normalize_point(p) for p in payload.get("visited", [])],
            paths={name: [_normalize_point(p) for p in pts] for name, pts in (payload.get("paths") or {}).items()},
            metadata=payload.get("metadata", {}),
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "voxels": self.voxels,
            "visited": self.visited,
            "paths": self.paths,
            "metadata": self.metadata,
        }

    def merge_voxels(self, points: Iterable[Sequence[float]]) -> None:
        known = {p for p in self.voxels}
        for point in points:
            normalized = _normalize_point(point)
            if normalized not in known:
                self.voxels.append(normalized)
                known.add(normalized)

    def merge_visited(self, points: Iterable[Sequence[float]]) -> None:
        known = {p for p in self.visited}
        for point in points:
            normalized = _normalize_point(point)
            if normalized not in known:
                self.visited.append(normalized)
                known.add(normalized)


class SharedMapController:
    """Контроллер для общей карты в Redis.

    - Добавляет точки вокселей, обнаруженных радаром
    - Добавляет точки маршрута, по которым уже летал грид
    - Сохраняет и загружает данные в общий ключ ``se:{owner_id}:memory``
    - Строит обратный путь на основе уже известных точек
    """

    def __init__(
        self,
        owner_id: Optional[str] = None,
        *,
        redis_client: Optional[RedisEventClient] = None,
        memory_key: Optional[str] = None,
    ) -> None:
        self.owner_id = owner_id or resolve_owner_id()
        self.memory_key = memory_key or f"se:{self.owner_id}:memory"
        self.client = redis_client or RedisEventClient()
        self.data = SharedMapData()

    # ------------------------------------------------------------------
    # Загрузка/сохранение
    # ------------------------------------------------------------------
    def load(self) -> SharedMapData:
        payload = self.client.get_json(self.memory_key)
        self.data = SharedMapData.from_payload(payload if isinstance(payload, dict) else {})
        return self.data

    def save(self) -> None:
        self.client.set_json(self.memory_key, self.data.to_payload())

    # ------------------------------------------------------------------
    # Сбор данных
    # ------------------------------------------------------------------
    def add_voxel_points(self, points: Iterable[Sequence[float]], *, save: bool = True) -> None:
        self.data.merge_voxels(points)
        if save:
            self.save()

    def add_flight_points(self, points: Iterable[Sequence[float]], *, save: bool = True) -> None:
        self.data.merge_visited(points)
        if save:
            self.save()

    def add_remote_position(self, remote: RemoteControlDevice, *, save: bool = True) -> Optional[Point3D]:
        remote.update()
        pos = get_world_position(remote)
        if pos:
            self.add_flight_points([pos], save=save)
        return pos

    def ingest_radar_scan(
        self,
        radar_controller: RadarController,
        *,
        persist_metadata: bool = True,
        save: bool = True,
    ) -> tuple[list[list[float]] | None, dict | None, list | None, list | None]:
        solid, metadata, contacts, ore_cells = radar_controller.scan_voxels()
        if solid:
            self.add_voxel_points(solid, save=False)
        if persist_metadata and metadata:
            self.data.metadata["last_radar"] = metadata
        if save:
            self.save()
        return solid, metadata, contacts, ore_cells

    # ------------------------------------------------------------------
    # Работа с путями
    # ------------------------------------------------------------------
    def store_named_path(self, name: str, points: Iterable[Sequence[float]], *, save: bool = True) -> List[Point3D]:
        path = [_normalize_point(p) for p in points]
        self.data.paths[name] = path
        if save:
            self.save()
        return path

    def build_known_path(self, start: Point3D, target: Optional[Point3D] = None, max_hops: int = 500) -> List[Point3D]:
        """Построить путь через уже известные точки.

        Простая эвристика: начинаем от ``start`` и идем через ближайшие известные
        точки (visited + voxels), пока не дойдем до ``target`` или не исчерпаем
        ``max_hops``. Возвращает список точек, включая старт и цель (если она
        была задана и найдена).
        """

        known_points = list({*self.data.visited, *self.data.voxels})
        if target:
            known_points.append(target)

        if not known_points:
            return [start] + ([target] if target else [])

        path: List[Point3D] = [start]
        current = start
        hops = 0
        remaining = set(known_points)
        if start in remaining:
            remaining.remove(start)

        def _dist(a: Point3D, b: Point3D) -> float:
            dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
            return (dx * dx + dy * dy + dz * dz) ** 0.5

        while remaining and hops < max_hops:
            closest = min(remaining, key=lambda p: _dist(current, p))
            path.append(closest)
            remaining.remove(closest)
            current = closest
            hops += 1
            if target and current == target:
                break

        if target and path[-1] != target:
            path.append(target)

        return path

    # ------------------------------------------------------------------
    # Вспомогательные сценарии
    # ------------------------------------------------------------------
    def build_and_store_return_path(
        self,
        remote: RemoteControlDevice,
        *,
        path_name: str = "return",
        home: Optional[Point3D] = None,
        max_hops: int = 200,
        save: bool = True,
    ) -> List[Point3D]:
        pos = self.add_remote_position(remote, save=False)
        if not pos:
            raise RuntimeError("Не удалось получить позицию RemoteControl")

        target = home or self.data.visited[0] if self.data.visited else pos
        path = self.build_known_path(pos, target, max_hops=max_hops)
        self.data.paths[path_name] = path
        if save:
            self.save()
        return path

    # ------------------------------------------------------------------
    # Работа с разными гридами
    # ------------------------------------------------------------------
    @classmethod
    def from_grid_devices(
        cls,
        grid_name: str,
        *,
        redis_client: Optional[RedisEventClient] = None,
        radar_radius: float = 100.0,
    ) -> tuple["SharedMapController", RadarController, RemoteControlDevice]:
        """Упрощенный помощник: получить контроллер карты и устройства грида."""
        from secontrol.common import prepare_grid

        grid = prepare_grid(grid_name)
        radar_device = grid.find_devices_by_type(OreDetectorDevice)[0]
        remote = grid.find_devices_by_type(RemoteControlDevice)[0]
        map_controller = cls(owner_id=grid.owner_id, redis_client=redis_client)
        radar_ctrl = RadarController(radar_device, radius=radar_radius)
        return map_controller, radar_ctrl, remote
