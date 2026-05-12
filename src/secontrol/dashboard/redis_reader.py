import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import redis
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)


class RedisReader:
    def __init__(self):
        url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        username = os.getenv("REDIS_USERNAME", "")
        password = os.getenv("REDIS_PASSWORD", "")
        parsed = urlparse(url)
        self.owner_id = username or parsed.username or ""
        self.client = redis.Redis(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
            username=username or None,
            password=password or None,
            decode_responses=True,
        )

    def get_grids_list(self) -> List[Dict[str, Any]]:
        grids_key = f"se:{self.owner_id}:grids"
        raw = self.client.get(grids_key)
        if raw is None:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return []

        grids = data.get("grids", data) if isinstance(data, dict) else data
        if not isinstance(grids, list):
            return []

        result = []
        for desc in grids:
            if not isinstance(desc, dict):
                continue
            grid_id = self._extract_grid_id(desc)
            if grid_id is None:
                continue
            info = self.get_grid_info(grid_id)
            name = self._extract_name(desc, info)
            position = self._extract_position(info)
            is_static = self._extract_bool(info, "isStatic", "gridIsStatic")
            block_count = len(info.get("blocks", [])) if isinstance(info.get("blocks"), list) else 0
            result.append({
                "grid_id": grid_id,
                "name": name or f"Grid_{grid_id}",
                "position": position,
                "is_static": is_static,
                "block_count": block_count,
            })
        return result

    def get_grid_info(self, grid_id: str) -> Dict[str, Any]:
        key = f"se:{self.owner_id}:grid:{grid_id}:gridinfo"
        raw = self.client.get(key)
        if raw is None:
            return {}
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_grid_detail(self, grid_id: str) -> Dict[str, Any]:
        info = self.get_grid_info(grid_id)
        name = self._extract_name({}, info)
        position = self._extract_position(info)
        is_static = self._extract_bool(info, "isStatic", "gridIsStatic")

        blocks = []
        raw_blocks = info.get("blocks", [])
        if isinstance(raw_blocks, list):
            for b in raw_blocks:
                if not isinstance(b, dict):
                    continue
                block = {
                    "id": b.get("id") or b.get("blockId") or b.get("entityId"),
                    "type": b.get("type") or b.get("blockType") or "unknown",
                    "subtype": b.get("subtype") or b.get("SubtypeName"),
                    "name": b.get("customName") or b.get("CustomName") or b.get("name"),
                    "isDevice": b.get("isDevice", False),
                    "position": self._extract_block_position(b),
                }
                blocks.append(block)

        devices = [b for b in blocks if b.get("isDevice")]

        subgrid_ids = info.get("subGridIds", [])
        subgrids = []
        for sid in subgrid_ids:
            if sid:
                sub_info = self.get_grid_info(str(sid))
                sub_name = self._extract_name({}, sub_info)
                sub_pos = self._extract_position(sub_info)
                subgrids.append({
                    "grid_id": str(sid),
                    "name": sub_name or f"Subgrid_{sid}",
                    "position": sub_pos,
                })

        return {
            "grid_id": grid_id,
            "name": name or f"Grid_{grid_id}",
            "position": position,
            "is_static": is_static,
            "blocks": blocks,
            "devices": devices,
            "subgrids": subgrids,
            "block_count": len(blocks),
            "device_count": len(devices),
        }

    def get_nearby_grids(self, grid_id: str, radius: float = 50000.0) -> List[Dict[str, Any]]:
        all_grids = self.get_grids_list()
        center = None
        for g in all_grids:
            if g["grid_id"] == grid_id:
                center = g.get("position")
                break
        if center is None:
            return [g for g in all_grids if g["grid_id"] != grid_id]

        nearby = []
        for g in all_grids:
            if g["grid_id"] == grid_id:
                continue
            pos = g.get("position")
            if pos and center:
                dx = pos["x"] - center["x"]
                dy = pos["y"] - center["y"]
                dz = pos["z"] - center["z"]
                dist = (dx**2 + dy**2 + dz**2) ** 0.5
                g["distance"] = dist
                if dist <= radius:
                    nearby.append(g)
            else:
                g["distance"] = None
                nearby.append(g)
        nearby.sort(key=lambda g: g.get("distance") or float("inf"))
        return nearby

    @staticmethod
    def _extract_grid_id(desc: Dict[str, Any]) -> Optional[str]:
        for key in ("grid_id", "gridId", "id", "GridId", "entity_id", "entityId"):
            val = desc.get(key)
            if val is not None:
                return str(val)
        return None

    @staticmethod
    def _extract_name(desc: Dict[str, Any], info: Dict[str, Any]) -> Optional[str]:
        for source in (info, desc):
            for key in ("name", "gridName", "displayName", "DisplayName"):
                val = source.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        return None

    @staticmethod
    def _extract_position(info: Dict[str, Any]) -> Optional[Dict[str, float]]:
        for key in ("pos", "worldPosition", "position", "Position"):
            pos = info.get(key)
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                try:
                    return {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2])}
                except (TypeError, ValueError):
                    continue
            if isinstance(pos, dict) and all(k in pos for k in ("x", "y", "z")):
                try:
                    return {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos["z"])}
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_block_position(block: Dict[str, Any]) -> Optional[Dict[str, float]]:
        for key in ("local_pos", "localPos", "localPosition", "relative_to_grid_center", "relativeToGridCenter"):
            pos = block.get(key)
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                try:
                    return {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2])}
                except (TypeError, ValueError):
                    continue
            if isinstance(pos, dict) and all(k in pos for k in ("x", "y", "z")):
                try:
                    return {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos["z"])}
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_bool(data: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            val = data.get(key)
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return bool(val)
        return None
