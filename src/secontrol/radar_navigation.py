"""Helpers for working with raw voxel radar exports on the Python side.

The module exposes utilities to decode the compact JSON that is produced by the
dedicated server plugin, build an occupancy grid, inflate obstacles for a given
robot radius and run A* path finding directly on the voxel map.

Only ``numpy`` is required which keeps the client lightweight and easy to deploy
alongside the existing Redis tooling.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

Index3 = Tuple[int, int, int]
WorldPoint = Tuple[float, float, float]


@dataclass(frozen=True)
class RadarContact:
    """Simplified contact descriptor exported by the radar."""

    type: str
    id: int
    position: WorldPoint


@dataclass
class RawRadarMap:
    """Representation of the raw radar export."""

    occ: np.ndarray
    origin: np.ndarray
    cell_size: float
    size: Index3
    revision: Optional[int]
    timestamp_ms: Optional[int]
    contacts: Sequence[RadarContact]

    _inflation_cache: Dict[int, np.ndarray]

    def __post_init__(self) -> None:  # pragma: no cover - simple defensive check
        if self.occ.shape != self.size:
            raise ValueError(
                f"Occupancy grid shape {self.occ.shape} does not match declared size {self.size}."
            )

    @classmethod
    def from_json(cls, payload: str | bytes | Dict[str, object]) -> "RawRadarMap":
        """Create a :class:`RawRadarMap` instance from a JSON document or dict."""

        if isinstance(payload, (str, bytes)):
            data = json.loads(payload)
        else:
            data = dict(payload)

        size = tuple(int(v) for v in data["size"])  # type: ignore[index]
        origin = np.array(data["origin"], dtype=np.float64)  # type: ignore[index]
        cell_size = float(data["cellSize"])  # type: ignore[index]

        occ = np.zeros(size, dtype=np.bool_)

        solid_points = data.get("solidPoints")
        if solid_points:
            arr = np.asarray(solid_points, dtype=np.float64)
            if arr.ndim == 2 and arr.shape[1] == 3:
                rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
                idx = np.rint(rel).astype(np.int64)
                valid = (
                    (idx[:, 0] >= 0)
                    & (idx[:, 0] < size[0])
                    & (idx[:, 1] >= 0)
                    & (idx[:, 1] < size[1])
                    & (idx[:, 2] >= 0)
                    & (idx[:, 2] < size[2])
                )
                idx = idx[valid]
                if idx.size:
                    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
        else:
            solid = data.get("solid", [])  # type: ignore[assignment]
            if solid:
                solid_idx = np.fromiter(solid, dtype=np.int64)
                ny, nz = size[1], size[2]
                x = solid_idx // (ny * nz)
                yz = solid_idx % (ny * nz)
                y = yz // nz
                z = yz % nz
                occ[x, y, z] = True

        for aabb in data.get("gridsAabb", []) or []:  # type: ignore[assignment]
            minx, miny, minz, maxx, maxy, maxz = aabb
            ix0 = max(0, int(math.floor((minx - origin[0]) / cell_size)))
            iy0 = max(0, int(math.floor((miny - origin[1]) / cell_size)))
            iz0 = max(0, int(math.floor((minz - origin[2]) / cell_size)))
            ix1 = min(size[0] - 1, int(math.floor((maxx - origin[0]) / cell_size)))
            iy1 = min(size[1] - 1, int(math.floor((maxy - origin[1]) / cell_size)))
            iz1 = min(size[2] - 1, int(math.floor((maxz - origin[2]) / cell_size)))
            if ix1 < ix0 or iy1 < iy0 or iz1 < iz0:
                continue
            occ[ix0 : ix1 + 1, iy0 : iy1 + 1, iz0 : iz1 + 1] = True

        contacts: List[RadarContact] = []
        for contact in data.get("contacts", []) or []:  # type: ignore[assignment]
            contacts.append(
                RadarContact(
                    type=str(contact.get("type", "")),
                    id=int(contact.get("id", 0)),
                    position=(
                        float(contact.get("pos", [0.0, 0.0, 0.0])[0]),
                        float(contact.get("pos", [0.0, 0.0, 0.0])[1]),
                        float(contact.get("pos", [0.0, 0.0, 0.0])[2]),
                    ),
                )
            )

        return cls(
            occ=occ,
            origin=origin,
            cell_size=cell_size,
            size=size,  # type: ignore[arg-type]
            revision=data.get("rev"),
            timestamp_ms=data.get("tsMs"),
            contacts=tuple(contacts),
            _inflation_cache={},
        )

    # ------------------------------------------------------------------
    # Coordinate helpers

    def world_to_index(self, point: WorldPoint) -> Optional[Index3]:
        """Convert world coordinates to a discrete grid index."""

        rel = (np.asarray(point) - self.origin) / self.cell_size
        ix, iy, iz = int(math.floor(rel[0])), int(math.floor(rel[1])), int(math.floor(rel[2]))
        if not self.is_within_bounds((ix, iy, iz)):
            return None
        return ix, iy, iz

    def index_to_world_center(self, idx: Index3) -> WorldPoint:
        """Return the center of a voxel in world space."""

        return (
            float(self.origin[0] + (idx[0] + 0.5) * self.cell_size),
            float(self.origin[1] + (idx[1] + 0.5) * self.cell_size),
            float(self.origin[2] + (idx[2] + 0.5) * self.cell_size),
        )

    def is_within_bounds(self, idx: Index3) -> bool:
        x, y, z = idx
        return (
            0 <= x < self.size[0]
            and 0 <= y < self.size[1]
            and 0 <= z < self.size[2]
        )

    # ------------------------------------------------------------------
    # Occupancy helpers

    def occupancy(self, robot_radius: float = 0.0) -> np.ndarray:
        """Return an occupancy grid inflated to accommodate a robot radius."""

        if robot_radius <= 1e-6:
            return self.occ.copy()

        radius_cells = int(math.ceil(robot_radius / self.cell_size))
        if radius_cells <= 0:
            return self.occ.copy()

        cached = self._inflation_cache.get(radius_cells)
        if cached is not None:
            return cached.copy()

        inflated = self._inflate(radius_cells)
        self._inflation_cache[radius_cells] = inflated
        return inflated.copy()

    def _inflate(self, radius_cells: int) -> np.ndarray:
        inflated = self.occ.copy()
        nx, ny, nz = inflated.shape
        xs, ys, zs = np.where(self.occ)
        for x, y, z in zip(xs, ys, zs):
            x0 = max(0, x - radius_cells)
            x1 = min(nx - 1, x + radius_cells)
            y0 = max(0, y - radius_cells)
            y1 = min(ny - 1, y + radius_cells)
            z0 = max(0, z - radius_cells)
            z1 = min(nz - 1, z + radius_cells)
            inflated[x0 : x1 + 1, y0 : y1 + 1, z0 : z1 + 1] = True
        return inflated


@dataclass
class PassabilityProfile:
    """Parameters describing how a robot is allowed to move through the grid."""

    robot_radius: float = 0.0
    max_slope_degrees: float = 45.0
    max_step_cells: int = 1
    allow_vertical_movement: bool = False
    allow_diagonal: bool = True


class PathFinder:
    """A* path finder operating on :class:`RawRadarMap` occupancy grids."""

    def __init__(self, radar_map: RawRadarMap, profile: Optional[PassabilityProfile] = None) -> None:
        self.radar_map = radar_map
        self.profile = profile or PassabilityProfile()
        self._occ = radar_map.occupancy(self.profile.robot_radius)

        if self.profile.max_step_cells < 0:
            raise ValueError("max_step_cells must be non-negative")

    # Public API ------------------------------------------------------

    def find_path_world(
        self,
        start: WorldPoint,
        goal: WorldPoint,
    ) -> List[WorldPoint]:
        """Find a path between two world coordinates."""

        start_idx = self.radar_map.world_to_index(start)
        goal_idx = self.radar_map.world_to_index(goal)
        if start_idx is None or goal_idx is None:
            return []

        path_idx = self.find_path_indices(start_idx, goal_idx)
        return [self.radar_map.index_to_world_center(p) for p in path_idx]

    def find_path_indices(self, start: Index3, goal: Index3) -> List[Index3]:
        """Return a list of indices describing a path between ``start`` and ``goal``."""

        if not self.radar_map.is_within_bounds(start) or not self.radar_map.is_within_bounds(goal):
            return []
        if self._is_blocked(start) or self._is_blocked(goal):
            return []

        open_set: List[Tuple[float, float, Index3]] = []
        heapq.heappush(open_set, (0.0, 0.0, start))

        g_score: Dict[Index3, float] = {start: 0.0}
        parents: Dict[Index3, Index3] = {}

        goal = tuple(goal)

        while open_set:
            f, g, current = heapq.heappop(open_set)
            if current == goal:
                return self._reconstruct_path(parents, current)

            for neighbor, step_cost in self._neighbors(current):
                tentative = g + step_cost
                if tentative >= g_score.get(neighbor, float("inf")):
                    continue
                g_score[neighbor] = tentative
                parents[neighbor] = current
                priority = tentative + self._heuristic(neighbor, goal)
                heapq.heappush(open_set, (priority, tentative, neighbor))

        return []

    # Internal helpers ------------------------------------------------

    def _neighbors(self, idx: Index3) -> Iterator[Tuple[Index3, float]]:
        x, y, z = idx

        if self.profile.allow_diagonal:
            directions = (
                (dx, dy, dz)
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for dz in (-1, 0, 1)
                if not (dx == dy == dz == 0)
            )
        else:
            directions = (
                (1, 0, 0),
                (-1, 0, 0),
                (0, 1, 0),
                (0, -1, 0),
                (0, 0, 1),
                (0, 0, -1),
            )

        for dx, dy, dz in directions:
            nx, ny, nz = x + dx, y + dy, z + dz
            neighbor = (nx, ny, nz)
            if not self.radar_map.is_within_bounds(neighbor):
                continue
            if self._is_blocked(neighbor):
                continue
            if not self._transition_allowed(idx, neighbor):
                continue

            step_cost = math.sqrt(dx * dx + dy * dy + dz * dz)
            yield neighbor, step_cost

    def _transition_allowed(self, current: Index3, neighbor: Index3) -> bool:
        dx = abs(neighbor[0] - current[0])
        dy = abs(neighbor[1] - current[1])
        dz = abs(neighbor[2] - current[2])

        if dy > self.profile.max_step_cells:
            return False

        horizontal = math.sqrt((dx * self.radar_map.cell_size) ** 2 + (dz * self.radar_map.cell_size) ** 2)
        vertical = dy * self.radar_map.cell_size

        if horizontal == 0.0:
            return self.profile.allow_vertical_movement and vertical <= self.profile.max_step_cells * self.radar_map.cell_size

        slope_deg = math.degrees(math.atan2(vertical, horizontal))
        if slope_deg > self.profile.max_slope_degrees:
            return False

        axis_deltas = []
        if dx:
            axis_deltas.append((int(math.copysign(1, neighbor[0] - current[0])), 0, 0))
        if dy:
            axis_deltas.append((0, int(math.copysign(1, neighbor[1] - current[1])), 0))
        if dz:
            axis_deltas.append((0, 0, int(math.copysign(1, neighbor[2] - current[2]))))

        if len(axis_deltas) >= 2:
            for ddx, ddy, ddz in axis_deltas:
                intermediate = (current[0] + ddx, current[1] + ddy, current[2] + ddz)
                if self.radar_map.is_within_bounds(intermediate) and self._is_blocked(intermediate):
                    return False

        return True

    def _heuristic(self, node: Index3, goal: Index3) -> float:
        dx = abs(goal[0] - node[0])
        dy = abs(goal[1] - node[1])
        dz = abs(goal[2] - node[2])
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def _is_blocked(self, idx: Index3) -> bool:
        return bool(self._occ[idx])

    @staticmethod
    def _reconstruct_path(parents: Dict[Index3, Index3], current: Index3) -> List[Index3]:
        path: List[Index3] = [current]
        while current in parents:
            current = parents[current]
            path.append(current)
        path.reverse()
        return path


__all__ = [
    "RawRadarMap",
    "PassabilityProfile",
    "PathFinder",
    "RadarContact",
]

