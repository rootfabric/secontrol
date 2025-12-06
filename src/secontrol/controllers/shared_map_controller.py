from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from secontrol.common import resolve_owner_id
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.redis_client import RedisEventClient
from secontrol.tools.navigation_tools import get_world_position


Point3D = Tuple[float, float, float]


@dataclass
class OreHit:
    material: str
    position: Point3D
    content: Any = None


def _normalize_point(point: Sequence[float]) -> Point3D:
    if len(point) != 3:
        raise ValueError(f"Point must have 3 coordinates, got {point}")
    return (float(point[0]), float(point[1]), float(point[2]))


@dataclass
class SharedMapData:
    voxels: List[Point3D] = field(default_factory=list)
    visited: List[Point3D] = field(default_factory=list)
    ores: List[OreHit] = field(default_factory=list)
    paths: Dict[str, List[Point3D]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any] | None) -> "SharedMapData":
        payload = payload or {}
        return cls(
            voxels=[_normalize_point(p) for p in payload.get("voxels", [])],
            visited=[_normalize_point(p) for p in payload.get("visited", [])],
            ores=[
                OreHit(
                    material=str(item.get("material") or item.get("ore") or "unknown"),
                    position=_normalize_point(item.get("position")),
                    content=item.get("content"),
                )
                for item in payload.get("ores", [])
                if item.get("position") is not None
            ],
            paths={name: [_normalize_point(p) for p in pts] for name, pts in (payload.get("paths") or {}).items()},
            metadata=payload.get("metadata", {}),
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "voxels": self.voxels,
            "visited": self.visited,
            "ores": [
                {"material": ore.material, "position": ore.position, "content": ore.content}
                for ore in self.ores
            ],
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

    def merge_ores(self, ores: Iterable[OreHit]) -> None:
        known = {(ore.material, ore.position) for ore in self.ores}
        for ore in ores:
            key = (ore.material, ore.position)
            if key not in known:
                self.ores.append(ore)
                known.add(key)


class SharedMapController:
    """Контроллер общей карты с переключаемыми бэкендами хранения.

    Можно использовать как удаленное хранилище Redis, так и локальную SQLite
    базу. В обоих вариантах данные разбиваются на чанки фиксированного размера,
    чтобы выборка по радиусу выполнялась за счет работы только с нужными
    чанками.
    """

    def __init__(
        self,
        owner_id: Optional[str] = None,
        *,
        redis_client: Optional[RedisEventClient] = None,
        memory_key: Optional[str] = None,
        chunk_size: float = 100.0,
        storage_backend: str = "redis",
        sqlite_path: str | os.PathLike[str] | None = None,
        storage: Optional[SharedMapStorage] = None,
    ) -> None:
        self.owner_id = owner_id or resolve_owner_id()
        self.memory_key = memory_key or f"se:{self.owner_id}:memory"
        self.memory_prefix = self.memory_key  # для обратной совместимости
        self.chunk_size = float(chunk_size)
        self.storage: SharedMapStorage
        self.client: Optional[RedisEventClient] = None

        if storage is not None:
            self.storage = storage
        elif storage_backend.lower() == "sqlite":
            db_path = sqlite_path or Path.home() / ".secontrol" / "maps" / f"{self.owner_id}.sqlite"
            self.storage = SQLiteSharedMapStorage(db_path, chunk_size=self.chunk_size)
        else:
            self.client = redis_client or RedisEventClient()
            self.storage = RedisSharedMapStorage(
                self.client,
                memory_prefix=self.memory_prefix,
                chunk_size=self.chunk_size,
            )

        self.chunk_size = float(self.storage.chunk_size)
        self.data = SharedMapData()

    # ------------------------------------------------------------------
    # Внутренние ключи и формат
    # ------------------------------------------------------------------
    def _chunk_id(self, point: Sequence[float]) -> str:
        x, y, z = _normalize_point(point)
        return f"{int(math.floor(x / self.chunk_size))}:{int(math.floor(y / self.chunk_size))}:{int(math.floor(z / self.chunk_size))}"

    def _load_index(self) -> Dict[str, Any]:
        idx = self.storage.load_index()
        self.chunk_size = float(idx.get("chunk_size", self.chunk_size))
        self.storage.chunk_size = self.chunk_size
        return idx

    def _save_index(self, idx: Dict[str, Any]) -> None:
        self.storage.chunk_size = self.chunk_size
        self.storage.save_index(idx)

    def _load_chunk_points(self, kind: str, chunk_id: str) -> List[Point3D]:
        return self.storage.load_chunk_points(kind, chunk_id)

    def _save_chunk_points(self, kind: str, chunk_id: str, points: Iterable[Point3D]) -> None:
        self.storage.save_chunk_points(kind, chunk_id, points)

    def _load_chunk_ores(self, chunk_id: str) -> List[OreHit]:
        return self.storage.load_chunk_ores(chunk_id)

    def _save_chunk_ores(self, chunk_id: str, ores: Iterable[OreHit]) -> None:
        self.storage.save_chunk_ores(chunk_id, ores)

    def _load_paths(self) -> Dict[str, List[Point3D]]:
        return self.storage.load_paths()

    def _save_paths(self) -> None:
        self.storage.save_paths(self.data.paths)

    def _load_metadata(self) -> Dict[str, Any]:
        return self.storage.load_metadata()

    def _save_metadata(self) -> None:
        self.storage.chunk_size = self.chunk_size
        self.storage.save_metadata(self.data.metadata)


class SharedMapStorage:
    def __init__(self, *, chunk_size: float) -> None:
        self.chunk_size = float(chunk_size)

    def load_index(self) -> Dict[str, Any]:
        raise NotImplementedError

    def save_index(self, idx: Dict[str, Any]) -> None:
        raise NotImplementedError

    def load_chunk_points(self, kind: str, chunk_id: str) -> List[Point3D]:
        raise NotImplementedError

    def save_chunk_points(self, kind: str, chunk_id: str, points: Iterable[Point3D]) -> None:
        raise NotImplementedError

    def load_chunk_ores(self, chunk_id: str) -> List[OreHit]:
        raise NotImplementedError

    def save_chunk_ores(self, chunk_id: str, ores: Iterable[OreHit]) -> None:
        raise NotImplementedError

    def load_paths(self) -> Dict[str, List[Point3D]]:
        raise NotImplementedError

    def save_paths(self, paths: Dict[str, List[Point3D]]) -> None:
        raise NotImplementedError

    def load_metadata(self) -> Dict[str, Any]:
        raise NotImplementedError

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        raise NotImplementedError

    def delete_chunk(self, kind: str, chunk_id: str) -> None:
        raise NotImplementedError


class RedisSharedMapStorage(SharedMapStorage):
    def __init__(self, client: RedisEventClient, *, memory_prefix: str, chunk_size: float) -> None:
        super().__init__(chunk_size=chunk_size)
        self.client = client
        self.memory_prefix = memory_prefix

    @property
    def index_key(self) -> str:
        return f"{self.memory_prefix}:index"

    @property
    def paths_key(self) -> str:
        return f"{self.memory_prefix}:paths"

    @property
    def metadata_key(self) -> str:
        return f"{self.memory_prefix}:meta"

    def _chunk_key(self, kind: str, chunk_id: str) -> str:
        return f"{self.memory_prefix}:{kind}:{chunk_id}"

    def load_index(self) -> Dict[str, Any]:
        idx = self.client.get_json(self.index_key) or {}
        chunk_size = float(idx.get("chunk_size", self.chunk_size))
        self.chunk_size = chunk_size
        return {
            "chunk_size": chunk_size,
            "voxels": set(idx.get("voxels", [])),
            "visited": set(idx.get("visited", [])),
            "ores": set(idx.get("ores", [])),
        }

    def save_index(self, idx: Dict[str, Any]) -> None:
        payload = {
            "chunk_size": self.chunk_size,
            "voxels": sorted(idx.get("voxels", [])),
            "visited": sorted(idx.get("visited", [])),
            "ores": sorted(idx.get("ores", [])),
        }
        self.client.set_json(self.index_key, payload)

    def load_chunk_points(self, kind: str, chunk_id: str) -> List[Point3D]:
        payload = self.client.get_json(self._chunk_key(kind, chunk_id))
        if not isinstance(payload, list):
            return []
        return [_normalize_point(p) for p in payload]

    def save_chunk_points(self, kind: str, chunk_id: str, points: Iterable[Point3D]) -> None:
        self.client.set_json(self._chunk_key(kind, chunk_id), list(points))

    def load_chunk_ores(self, chunk_id: str) -> List[OreHit]:
        payload = self.client.get_json(self._chunk_key("ores", chunk_id))
        if not isinstance(payload, list):
            return []
        ores: List[OreHit] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            pos = item.get("position")
            if pos is None:
                continue
            ores.append(
                OreHit(
                    material=str(item.get("material") or item.get("ore") or "unknown"),
                    position=_normalize_point(pos),
                    content=item.get("content"),
                )
            )
        return ores

    def save_chunk_ores(self, chunk_id: str, ores: Iterable[OreHit]) -> None:
        payload = [
            {"material": ore.material, "position": ore.position, "content": ore.content}
            for ore in ores
        ]
        self.client.set_json(self._chunk_key("ores", chunk_id), payload)

    def load_paths(self) -> Dict[str, List[Point3D]]:
        payload = self.client.get_json(self.paths_key) or {}
        return {name: [_normalize_point(p) for p in pts] for name, pts in payload.items() if isinstance(pts, list)}

    def save_paths(self, paths: Dict[str, List[Point3D]]) -> None:
        self.client.set_json(self.paths_key, paths)

    def load_metadata(self) -> Dict[str, Any]:
        payload = self.client.get_json(self.metadata_key)
        return payload if isinstance(payload, dict) else {}

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        self.client.set_json(self.metadata_key, metadata)

    def delete_chunk(self, kind: str, chunk_id: str) -> None:
        try:
            self.client._client.delete(self._chunk_key(kind, chunk_id))  # type: ignore[attr-defined]
        except Exception:
            # Если клиент не предоставляет прямого доступа, просто перезаписываем пустым списком
            self.client.set_json(self._chunk_key(kind, chunk_id), [])


class SQLiteSharedMapStorage(SharedMapStorage):
    def __init__(self, path: str | os.PathLike[str], *, chunk_size: float) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        super().__init__(chunk_size=chunk_size)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_index (
                    kind TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    PRIMARY KEY (kind, chunk_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    kind TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (kind, chunk_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paths (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def _get_metadata(self, key: str) -> Optional[Any]:
        cursor = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def _set_metadata(self, key: str, value: Any) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def load_index(self) -> Dict[str, Any]:
        stored_chunk_size = self._get_metadata("chunk_size")
        if stored_chunk_size is not None:
            try:
                self.chunk_size = float(stored_chunk_size)
            except (TypeError, ValueError):
                pass

        idx = {"chunk_size": self.chunk_size, "voxels": set(), "visited": set(), "ores": set()}
        cursor = self.conn.execute("SELECT kind, chunk_id FROM chunk_index")
        for kind, chunk_id in cursor.fetchall():
            if kind in idx:
                idx[kind].add(chunk_id)
        return idx

    def save_index(self, idx: Dict[str, Any]) -> None:
        with self.conn:
            self._set_metadata("chunk_size", float(self.chunk_size))
            for kind in ("voxels", "visited", "ores"):
                self.conn.execute("DELETE FROM chunk_index WHERE kind = ?", (kind,))
                chunk_ids = [(kind, cid) for cid in sorted(idx.get(kind, []))]
                if chunk_ids:
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO chunk_index (kind, chunk_id) VALUES (?, ?)", chunk_ids
                    )

    def load_chunk_points(self, kind: str, chunk_id: str) -> List[Point3D]:
        cursor = self.conn.execute(
            "SELECT payload FROM chunks WHERE kind = ? AND chunk_id = ?", (kind, chunk_id)
        )
        row = cursor.fetchone()
        if not row:
            return []
        try:
            payload = json.loads(row[0])
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [_normalize_point(p) for p in payload]

    def save_chunk_points(self, kind: str, chunk_id: str, points: Iterable[Point3D]) -> None:
        payload = json.dumps(list(points))
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO chunks (kind, chunk_id, payload) VALUES (?, ?, ?)",
                (kind, chunk_id, payload),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO chunk_index (kind, chunk_id) VALUES (?, ?)",
                (kind, chunk_id),
            )

    def load_chunk_ores(self, chunk_id: str) -> List[OreHit]:
        cursor = self.conn.execute(
            "SELECT payload FROM chunks WHERE kind = 'ores' AND chunk_id = ?", (chunk_id,)
        )
        row = cursor.fetchone()
        if not row:
            return []
        try:
            payload = json.loads(row[0])
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        ores: List[OreHit] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            pos = item.get("position")
            if pos is None:
                continue
            ores.append(
                OreHit(
                    material=str(item.get("material") or item.get("ore") or "unknown"),
                    position=_normalize_point(pos),
                    content=item.get("content"),
                )
            )
        return ores

    def save_chunk_ores(self, chunk_id: str, ores: Iterable[OreHit]) -> None:
        payload = [
            {"material": ore.material, "position": ore.position, "content": ore.content}
            for ore in ores
        ]
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO chunks (kind, chunk_id, payload) VALUES ('ores', ?, ?)",
                (chunk_id, json.dumps(payload)),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO chunk_index (kind, chunk_id) VALUES ('ores', ?)", (chunk_id,)
            )

    def load_paths(self) -> Dict[str, List[Point3D]]:
        cursor = self.conn.execute("SELECT name, payload FROM paths")
        paths: Dict[str, List[Point3D]] = {}
        for name, payload in cursor.fetchall():
            try:
                pts = json.loads(payload)
            except Exception:
                continue
            if isinstance(pts, list):
                paths[name] = [_normalize_point(p) for p in pts]
        return paths

    def save_paths(self, paths: Dict[str, List[Point3D]]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM paths")
            if paths:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO paths (name, payload) VALUES (?, ?)",
                    [(name, json.dumps(points)) for name, points in paths.items()],
                )

    def load_metadata(self) -> Dict[str, Any]:
        cursor = self.conn.execute("SELECT key, value FROM metadata")
        metadata: Dict[str, Any] = {}
        for key, value in cursor.fetchall():
            if key == "chunk_size":
                continue
            try:
                metadata[key] = json.loads(value)
            except Exception:
                metadata[key] = value
        return metadata

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM metadata WHERE key != 'chunk_size'")
            for key, value in metadata.items():
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            self._set_metadata("chunk_size", float(self.chunk_size))

    def delete_chunk(self, kind: str, chunk_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks WHERE kind = ? AND chunk_id = ?", (kind, chunk_id))
            self.conn.execute("DELETE FROM chunk_index WHERE kind = ? AND chunk_id = ?", (kind, chunk_id))

    # ------------------------------------------------------------------
    # Загрузка/сохранение
    # ------------------------------------------------------------------
    def load(
        self,
        *,
        chunk_ids: Optional[Iterable[str]] = None,
        kinds: Sequence[str] = ("voxels", "visited", "ores"),
        include_paths: bool = True,
        include_metadata: bool = True,
    ) -> SharedMapData:
        """Загрузить выбранные чанки карты.

        ``chunk_ids=None`` означает загрузку всех чанков, перечисленных в индексе.
        Для ускорения можно передать ограниченный набор чанков.
        """

        idx = self._load_index()

        # Поддержка старого формата: если индекс пустой, пробуем прочитать весь
        # словарь из ``memory_prefix`` и разложить его по чанкам.
        if (
            not (idx["voxels"] or idx["visited"] or idx["ores"])
            and isinstance(self.storage, RedisSharedMapStorage)
        ):
            legacy_payload = self.storage.client.get_json(self.storage.memory_prefix)
            if isinstance(legacy_payload, dict) and any(
                legacy_payload.get(k) for k in ("voxels", "visited", "ores")
            ):
                legacy = SharedMapData.from_payload(legacy_payload)
                if legacy.voxels:
                    self.add_voxel_points(legacy.voxels, save=True)
                if legacy.visited:
                    self.add_flight_points(legacy.visited, save=True)
                if legacy.ores:
                    self.add_ore_cells(
                        [
                            {"material": ore.material, "position": ore.position, "content": ore.content}
                            for ore in legacy.ores
                        ],
                        save=True,
                    )
                if legacy.paths:
                    self.data.paths = legacy.paths
                    self._save_paths()
                if legacy.metadata:
                    self.data.metadata = legacy.metadata
                    self._save_metadata()
                idx = self._load_index()

        self.data = SharedMapData()

        load_chunk_ids = set(chunk_ids) if chunk_ids is not None else None

        def _should_load(cid: str) -> bool:
            return load_chunk_ids is None or cid in load_chunk_ids

        if "voxels" in kinds:
            for cid in idx["voxels"]:
                if _should_load(cid):
                    self.data.merge_voxels(self._load_chunk_points("voxels", cid))

        if "visited" in kinds:
            for cid in idx["visited"]:
                if _should_load(cid):
                    self.data.merge_visited(self._load_chunk_points("visited", cid))

        if "ores" in kinds:
            for cid in idx["ores"]:
                if _should_load(cid):
                    self.data.merge_ores(self._load_chunk_ores(cid))

        if include_paths:
            self.data.paths = self._load_paths()

        if include_metadata:
            self.data.metadata = self._load_metadata()

        return self.data

    def load_region(
        self,
        center: Point3D,
        radius: float,
        *,
        kinds: Sequence[str] = ("voxels", "visited", "ores"),
        include_paths: bool = True,
        include_metadata: bool = True,
    ) -> SharedMapData:
        """Загрузить только чанки, которые пересекают сферу радиуса ``radius``."""

        # Сначала подгружаем индекс, чтобы актуализировать chunk_size
        idx = self._load_index()
        chunk_size = float(self.chunk_size)

        cx, cy, cz = center
        cr = float(radius)
        min_x, max_x = cx - cr, cx + cr
        min_y, max_y = cy - cr, cy + cr
        min_z, max_z = cz - cr, cz + cr

        def _chunk_range(vmin: float, vmax: float) -> range:
            start = math.floor(vmin / chunk_size)
            end = math.floor(vmax / chunk_size)
            return range(int(start), int(end) + 1)

        chunk_ids = {
            f"{ix}:{iy}:{iz}"
            for ix in _chunk_range(min_x, max_x)
            for iy in _chunk_range(min_y, max_y)
            for iz in _chunk_range(min_z, max_z)
        }

        # idx мы уже считали, но load() сам подтянет его заново — это не страшно
        return self.load(
            chunk_ids=chunk_ids,
            kinds=kinds,
            include_paths=include_paths,
            include_metadata=include_metadata,
        )


    def save(self) -> None:
        # Сохраняем только метаданные и индекс/пути — чанки пишутся по мере обновления
        self._save_metadata()
        self._save_paths()
        self._save_index(self._load_index())

    # ------------------------------------------------------------------
    # Сбор данных
    # ------------------------------------------------------------------
    def add_voxel_points(self, points: Iterable[Sequence[float]], *, save: bool = True) -> None:
        idx = self._load_index()
        buckets: Dict[str, List[Point3D]] = {}
        for point in points:
            normalized = _normalize_point(point)
            cid = self._chunk_id(normalized)
            buckets.setdefault(cid, []).append(normalized)

        for cid, pts in buckets.items():
            existing = self._load_chunk_points("voxels", cid)
            merged = list({*existing, *pts})
            self._save_chunk_points("voxels", cid, merged)
            idx["voxels"].add(cid)
            self.data.merge_voxels(pts)

        if save:
            self._save_index(idx)
            self._save_metadata()

    def add_flight_points(self, points: Iterable[Sequence[float]], *, save: bool = True) -> None:
        idx = self._load_index()
        buckets: Dict[str, List[Point3D]] = {}
        for point in points:
            normalized = _normalize_point(point)
            cid = self._chunk_id(normalized)
            buckets.setdefault(cid, []).append(normalized)

        for cid, pts in buckets.items():
            existing = self._load_chunk_points("visited", cid)
            merged = list({*existing, *pts})
            self._save_chunk_points("visited", cid, merged)
            idx["visited"].add(cid)
            self.data.merge_visited(pts)

        if save:
            self._save_index(idx)
            self._save_metadata()

    def add_ore_cells(self, cells: Iterable[dict], *, save: bool = True) -> None:
        idx = self._load_index()
        buckets: Dict[str, List[OreHit]] = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            if cell.get("position") is None:
                continue
            ore = OreHit(
                material=str(cell.get("material") or cell.get("ore") or "unknown"),
                position=_normalize_point(cell.get("position")),
                content=cell.get("content"),
            )
            cid = self._chunk_id(ore.position)
            buckets.setdefault(cid, []).append(ore)

        for cid, ores in buckets.items():
            existing = self._load_chunk_ores(cid)
            merged = list({(o.material, o.position): o for o in [*existing, *ores]}.values())
            self._save_chunk_ores(cid, merged)
            idx["ores"].add(cid)
            self.data.merge_ores(ores)

        if save:
            self._save_index(idx)
            self._save_metadata()

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

        # сохраняем чанки + обновляем индекс
        if solid:
            self.add_voxel_points(solid, save=save)
        if ore_cells:
            self.add_ore_cells(ore_cells, save=save)

        if persist_metadata and metadata:
            self.data.metadata["last_radar"] = metadata
            if save:
                self._save_metadata()

        return solid, metadata, contacts, ore_cells


    def get_known_ores(
        self,
        material: Optional[str] = None,
        *,
        chunk_ids: Optional[Iterable[str]] = None,
    ) -> List[OreHit]:
        """Вернуть список найденных руд, с возможностью фильтрации по материалу."""

        idx = self._load_index()
        ids = set(chunk_ids) if chunk_ids is not None else set(idx["ores"])

        ore_map: Dict[tuple[str, Point3D], OreHit] = {}
        material_filter = material.lower() if material else None

        for cid in ids:
            ores = self._load_chunk_ores(cid)
            for ore in ores:
                if material_filter and ore.material.lower() != material_filter:
                    continue
                ore_map[(ore.material, ore.position)] = ore

        return list(ore_map.values())

    # ------------------------------------------------------------------
    # Работа с путями
    # ------------------------------------------------------------------
    def store_named_path(self, name: str, points: Iterable[Sequence[float]], *, save: bool = True) -> List[Point3D]:
        path = [_normalize_point(p) for p in points]
        self.data.paths[name] = path
        if save:
            self._save_paths()
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
            self._save_paths()
        return path

    # ------------------------------------------------------------------
    # Размер в памяти Redis
    # ------------------------------------------------------------------
    def get_redis_memory_usage(self) -> int:
        """
        Примерный размер карты в Redis в байтах.

        Считаем сумму по всем ключам карты, которые известны из индекса:
        - index, paths, meta
        - чанки voxels / visited / ores.
        Для каждого ключа сначала пробуем MEMORY USAGE, при ошибке
        откатываемся на get_json + json.dumps.
        """
        if not isinstance(self.storage, RedisSharedMapStorage):
            raise RuntimeError("Подсчет памяти доступен только для Redis-бэкенда")

        idx = self._load_index()

        # Формируем список всех ключей, которые относятся к карте
        keys: list[str] = [
            self.storage.index_key,
            self.storage.paths_key,
            self.storage.metadata_key,
        ]

        for cid in idx["voxels"]:
            keys.append(self.storage._chunk_key("voxels", cid))
        for cid in idx["visited"]:
            keys.append(self.storage._chunk_key("visited", cid))
        for cid in idx["ores"]:
            keys.append(self.storage._chunk_key("ores", cid))

        # На случай старого формата, когда всё лежало по memory_prefix
        keys.append(self.storage.memory_prefix)

        # Пытаемся достучаться до "сырого" redis-клиента
        redis_client = None
        for attr in ("client", "_client", "redis"):
            if hasattr(self.storage.client, attr):
                redis_client = getattr(self.storage.client, attr)
                break

        total_size = 0

        for key in keys:
            size = 0

            # 1) Основной вариант: MEMORY USAGE, если доступен
            if redis_client is not None and hasattr(redis_client, "memory_usage"):
                try:
                    usage = redis_client.memory_usage(key)  # type: ignore[attr-defined]
                    if usage is not None:
                        size = int(usage)
                except Exception:
                    size = 0

            # 2) Fallback: через get_json, если MEMORY USAGE недоступен или вернул 0
            if size == 0:
                try:
                    payload = self.storage.client.get_json(key)
                except Exception:
                    payload = None

                if payload is None:
                    continue

                try:
                    dump = json.dumps(payload, separators=(",", ":"))
                except TypeError:
                    dump = json.dumps(payload)

                size = len(dump.encode("utf-8", "ignore"))

            total_size += size

        return total_size

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

    def thin_voxel_density(
        self,
        *,
        resolution: float = 5.0,
        min_points_to_thin: int = 1000,
        max_points_per_cell: int = 1,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """
        Проредить (разредить) облака вокселей в активном хранилище.

        Логика:
        - Для каждого чанка с вокселями строится 3D-сетка с шагом `resolution`.
        - В каждую ячейку сетки допускается не более `max_points_per_cell` точек.
        - Остальные точки в этой ячейке считаются "лишними" и удаляются.
        - Операция выполняется ПРЯМО по чанкам (хранилище реально очищается).

        Параметры:
            resolution:
                Пространственный шаг (в метрах) для объединения близких точек.
                Например, 5.0 означает, что все точки в кубе 5x5x5 м
                будут сжаты до не более чем `max_points_per_cell` точек.
            min_points_to_thin:
                Минимальное количество точек в чанке, при котором мы вообще
                будем что-то прореживать. Мелкие чанки не трогаем.
            max_points_per_cell:
                Максимальное количество точек на одну "ячейку" сетки.
                Обычно достаточно 1.
            verbose:
                Если True — печатает подробную статистику.

        Возвращает:
            dict со статистикой:
            {
                "chunks_total": int,
                "chunks_thinned": int,
                "total_before": int,
                "total_after": int,
                "total_removed": int,
                "resolution": float,
                "max_points_per_cell": int,
            }

        ВАЖНО:
        - Метод изменяет данные в хранилище. Если у контроллера уже загружена
          self.data.voxels, она может не совпасть с хранилищем — после
          прорядки имеет смысл вызвать load() / load_region() заново.
        """
        if resolution <= 0.0:
            raise ValueError(f"resolution must be > 0, got {resolution}")
        if max_points_per_cell <= 0:
            raise ValueError(f"max_points_per_cell must be > 0, got {max_points_per_cell}")

        idx = self._load_index()
        voxel_chunk_ids = list(idx.get("voxels", []))

        chunks_total = len(voxel_chunk_ids)
        chunks_thinned = 0
        total_before = 0
        total_after = 0

        for cid in voxel_chunk_ids:
            points = self._load_chunk_points("voxels", cid)
            n_before = len(points)
            if n_before == 0:
                continue

            total_before += n_before

            # Не трогаем мелкие чанки
            if n_before < min_points_to_thin:
                if verbose:
                    print(
                        f"[thin_voxel_density] chunk {cid}: {n_before} points "
                        f"(<{min_points_to_thin}), skip thinning."
                    )
                total_after += n_before
                continue

            # Квантование в мировых координатах с шагом `resolution`
            # ВАЖНО: ключи ячеек используются только внутри одного чанка,
            # поэтому нас не волнует граница между чанками.
            cell_buckets: Dict[Tuple[int, int, int], List[Point3D]] = {}

            for p in points:
                x, y, z = p
                cx = int(math.floor(x / resolution))
                cy = int(math.floor(y / resolution))
                cz = int(math.floor(z / resolution))
                key = (cx, cy, cz)

                bucket = cell_buckets.setdefault(key, [])
                if len(bucket) < max_points_per_cell:
                    bucket.append(p)
                # Если уже достигли max_points_per_cell — остальные точки
                # в этом кубе считаем "лишними" и не добавляем.

            # Собираем новые точки
            new_points: List[Point3D] = []
            for bucket in cell_buckets.values():
                # Обычно в bucket 1 точка, но теоретически может быть до max_points_per_cell.
                # Можно было бы усреднять, но для навигации вполне достаточно любой из них.
                new_points.extend(bucket)

            n_after = len(new_points)
            total_after += n_after
            chunks_thinned += 1

            if verbose:
                removed = n_before - n_after
                ratio = (n_after / n_before) if n_before > 0 else 1.0
                print(
                    f"[thin_voxel_density] chunk {cid}: "
                    f"{n_before} → {n_after} points "
                    f"(removed {removed}, kept {ratio * 100:.1f}%)"
                )

            # Перезаписываем чанк в Redis
            self._save_chunk_points("voxels", cid, new_points)

        total_removed = total_before - total_after

        if verbose:
            print(
                "[thin_voxel_density] done: "
                f"chunks_total={chunks_total}, "
                f"chunks_thinned={chunks_thinned}, "
                f"total_before={total_before}, "
                f"total_after={total_after}, "
                f"total_removed={total_removed}, "
                f"resolution={resolution}, "
                f"max_points_per_cell={max_points_per_cell}"
            )

        return {
            "chunks_total": chunks_total,
            "chunks_thinned": chunks_thinned,
            "total_before": total_before,
            "total_after": total_after,
            "total_removed": total_removed,
            "resolution": float(resolution),
            "max_points_per_cell": int(max_points_per_cell),
        }

    def remove_points_in_radius(
        self,
        center: Point3D,
        radius: float,
        kinds: Sequence[str] = ("voxels", "visited", "ores"),
        save: bool = True,
    ) -> Dict[str, Any]:
        """
        Удалить все точки в заданном радиусе от центра для указанных типов данных.

        Логика:
        - Находит чанки, которые могут содержать точки в сфере радиуса `radius`.
        - Для каждого типа (`kinds`) загружает точки из этих чанков.
        - Удаляет точки, находящиеся внутри радиуса (евклидово расстояние <= radius).
        - Сохраняет отфильтрованные точки обратно в Redis.
        - Обновляет индекс: пустые чанки удаляются из индекса и из Redis.

        Параметры:
            center: Центр сферы удаления (Point3D).
            radius: Радиус сферы (float, в метрах).
            kinds: Типы точек для обработки ("voxels", "visited", "ores").
            save: Если True, сохраняет изменения в Redis.

        Возвращает:
            dict со статистикой:
            {
                "total_removed": int,  # Общее количество удаленных точек
                "chunks_affected": int,  # Количество затронутых чанков
                "kinds_processed": list[str],  # Обработанные типы
            }

        ВАЖНО:
        - Изменяет данные в активном хранилище. После удаления имеет смысл вызвать load() / load_region() заново,
          если self.data уже загружена.
        - Для ores удаляет по позиции OreHit.
        """
        if radius <= 0.0:
            raise ValueError(f"radius must be > 0, got {radius}")

        cx, cy, cz = center
        cr = float(radius)

        # Загружаем индекс
        idx = self._load_index()

        # Находим все чанки, которые могут пересекать сферу
        chunk_size = float(self.chunk_size)
        min_x, max_x = cx - cr, cx + cr
        min_y, max_y = cy - cr, cy + cr
        min_z, max_z = cz - cr, cz + cr

        def _chunk_range(vmin: float, vmax: float) -> range:
            start = math.floor(vmin / chunk_size)
            end = math.floor(vmax / chunk_size)
            return range(int(start), int(end) + 1)

        relevant_chunk_ids = {
            f"{ix}:{iy}:{iz}"
            for ix in _chunk_range(min_x, max_x)
            for iy in _chunk_range(min_y, max_y)
            for iz in _chunk_range(min_z, max_z)
        }

        # Функция расстояния
        def _dist(a: Point3D, b: Point3D) -> float:
            dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
            return (dx * dx + dy * dy + dz * dz) ** 0.5

        total_removed = 0
        chunks_affected = 0

        # Обрабатываем каждый тип
        for kind in kinds:
            if kind not in ("voxels", "visited", "ores"):
                continue

            chunk_ids = idx.get(kind, set())
            chunks_to_process = relevant_chunk_ids & chunk_ids

            for cid in chunks_to_process:
                if kind == "ores":
                    ores = self._load_chunk_ores(cid)
                    filtered_ores = [ore for ore in ores if _dist(ore.position, center) > radius]
                    removed_count = len(ores) - len(filtered_ores)
                    if removed_count > 0:
                        if filtered_ores:
                            self._save_chunk_ores(cid, filtered_ores)
                        else:
                            # Чанк пуст, удаляем
                            self.storage.delete_chunk("ores", cid)
                            idx["ores"].discard(cid)
                        chunks_affected += 1
                        total_removed += removed_count
                else:
                    # voxels или visited
                    points = self._load_chunk_points(kind, cid)
                    filtered_points = [p for p in points if _dist(p, center) > radius]
                    removed_count = len(points) - len(filtered_points)
                    if removed_count > 0:
                        if filtered_points:
                            self._save_chunk_points(kind, cid, filtered_points)
                        else:
                            # Чанк пуст, удаляем
                            self.storage.delete_chunk(kind, cid)
                            idx[kind].discard(cid)
                        chunks_affected += 1
                        total_removed += removed_count

        if save:
            self._save_index(idx)

        return {
            "total_removed": total_removed,
            "chunks_affected": chunks_affected,
            "kinds_processed": list(kinds),
        }
