import json
import os
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import redis
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)


class FleetRedisReader:
    def __init__(self):
        url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        username = os.getenv("REDIS_USERNAME", "")
        password = os.getenv("REDIS_PASSWORD", "")
        parsed = urlparse(url)
        self.owner_id = username or parsed.username or ""
        self.player_id = os.getenv("SE_PLAYER_ID", "") or self.owner_id
        self.client = redis.Redis(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
            username=username or None,
            password=password or None,
            decode_responses=True,
            socket_keepalive=True,
            retry_on_timeout=True,
        )

    def _ensure_connected(self):
        try:
            self.client.ping()
        except (redis.ConnectionError, redis.TimeoutError):
            url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
            username = os.getenv("REDIS_USERNAME", "")
            password = os.getenv("REDIS_PASSWORD", "")
            parsed = urlparse(url)
            self.client = redis.Redis(
                host=parsed.hostname or "127.0.0.1",
                port=parsed.port or 6379,
                db=int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
                username=username or None,
                password=password or None,
                decode_responses=True,
                socket_keepalive=True,
                retry_on_timeout=True,
            )

    def _get_json(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            raw = self.client.get(key)
        except (redis.ConnectionError, redis.TimeoutError):
            self._ensure_connected()
            raw = self.client.get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    def _get_json_list(self, key: str) -> Optional[List]:
        raw = self.client.get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, list) else None
        except (json.JSONDecodeError, TypeError):
            return None

    def _publish(self, channel: str, payload: Dict[str, Any]) -> int:
        try:
            return self.client.publish(channel, json.dumps(payload))
        except (redis.ConnectionError, redis.TimeoutError):
            self._ensure_connected()
            return self.client.publish(channel, json.dumps(payload))

    # ── Telemetry discovery ──

    def _discover_telemetry(self, grid_id: str) -> Dict[str, Dict[str, Any]]:
        """Scan Redis for all telemetry keys in a grid, return {device_id: telemetry_dict}."""
        pattern = f"se:{self.owner_id}:grid:{grid_id}:*:*:telemetry"
        result: Dict[str, Dict[str, Any]] = {}
        try:
            keys = list(self.client.scan_iter(match=pattern, count=200))
        except (redis.ConnectionError, redis.TimeoutError):
            self._ensure_connected()
            keys = list(self.client.scan_iter(match=pattern, count=200))
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8", "replace")
            parts = key.split(":")
            if len(parts) != 7 or parts[6] != "telemetry":
                continue
            device_id = parts[5]
            telemetry = self._get_json(key)
            if isinstance(telemetry, dict):
                result[device_id] = telemetry
        return result

    # ── Grid list ──

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
            speed = self._extract_speed(info)
            blocks_raw = info.get("blocks", [])
            block_count = len(blocks_raw) if isinstance(blocks_raw, list) else 0
            damaged_count = 0
            if isinstance(blocks_raw, list):
                for b in blocks_raw:
                    if isinstance(b, dict) and self._is_block_damaged(b):
                        damaged_count += 1
            health = 100.0 if block_count == 0 else round((1 - damaged_count / max(block_count, 1)) * 100, 1)
            result.append({
                "grid_id": grid_id,
                "name": name or f"Grid_{grid_id}",
                "position": position,
                "is_static": is_static,
                "speed": speed,
                "block_count": block_count,
                "damaged_block_count": damaged_count,
                "health_percent": health,
            })
        return result

    # ── Fleet status ──

    def get_fleet_status(self) -> Dict[str, Any]:
        grids = self.get_grids_list()
        total_blocks = sum(g["block_count"] for g in grids)
        total_damaged = sum(g["damaged_block_count"] for g in grids)
        total_devices = 0
        for g in grids:
            info = self.get_grid_info(g["grid_id"])
            blocks = info.get("blocks", [])
            if isinstance(blocks, list):
                total_devices += sum(1 for b in blocks if isinstance(b, dict) and b.get("isDevice"))
        return {
            "total_grids": len(grids),
            "total_blocks": total_blocks,
            "total_damaged_blocks": total_damaged,
            "total_devices": total_devices,
            "health_percent": round((1 - total_damaged / max(total_blocks, 1)) * 100, 1),
            "grids": grids,
        }

    # ── Grid detail ──

    def get_grid_info(self, grid_id: str) -> Dict[str, Any]:
        key = f"se:{self.owner_id}:grid:{grid_id}:gridinfo"
        return self._get_json(key) or {}

    def get_grid_detail(self, grid_id: str) -> Dict[str, Any]:
        info = self.get_grid_info(grid_id)
        name = self._extract_name({}, info)
        position = self._extract_position(info)
        is_static = self._extract_bool(info, "isStatic", "gridIsStatic")
        speed = self._extract_speed(info)
        orientation = self._extract_grid_orientation(grid_id)

        blocks = []
        raw_blocks = info.get("blocks", [])
        if isinstance(raw_blocks, list):
            for b in raw_blocks:
                if not isinstance(b, dict):
                    continue
                raw_name = b.get("customName") or b.get("CustomName") or b.get("displayName") or b.get("DisplayName") or b.get("name") or ""
                subtype_val = b.get("subtype") or b.get("SubtypeName") or ""
                block = {
                    "id": b.get("id") or b.get("blockId") or b.get("entityId"),
                    "type": b.get("type") or b.get("blockType") or "unknown",
                    "subtype": subtype_val,
                    "name": raw_name,
                    "display_name": raw_name or self._humanize_type(subtype_val or (b.get("type") or b.get("blockType") or "")),
                    "isDevice": b.get("isDevice", False),
                    "position": self._extract_block_position(b),
                    "state": self._extract_block_state(b),
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

        damaged_count = sum(1 for b in blocks if self._is_block_damaged_raw(b))

        nearby_devices = []
        if position:
            for ng in self.get_nearby_grids(grid_id, radius=1000):
                ng_pos = ng.get("position")
                if not ng_pos:
                    continue
                ng_info = self.get_grid_info(ng["grid_id"])
                ng_blocks = ng_info.get("blocks", [])
                if not isinstance(ng_blocks, list):
                    continue
                ng_device_blocks = []
                for b in ng_blocks:
                    if not isinstance(b, dict) or not b.get("isDevice"):
                        continue
                    pos = self._extract_block_position(b)
                    if not pos:
                        continue
                    ng_device_blocks.append({
                        "id": b.get("id") or b.get("blockId") or b.get("entityId"),
                        "type": b.get("type") or b.get("blockType") or "unknown",
                        "subtype": b.get("subtype") or b.get("SubtypeName") or "",
                        "name": b.get("customName") or b.get("CustomName") or b.get("name") or "",
                        "position": pos,
                    })
                if ng_device_blocks:
                    nearby_devices.append({
                        "grid_id": ng["grid_id"],
                        "name": ng.get("name", ""),
                        "position": ng_pos,
                        "orientation": self._extract_grid_orientation(ng["grid_id"]),
                        "blocks": ng_device_blocks,
                    })

        return {
            "grid_id": grid_id,
            "name": name or f"Grid_{grid_id}",
            "position": position,
            "is_static": is_static,
            "speed": speed,
            "orientation": orientation,
            "blocks": blocks,
            "devices": devices,
            "subgrids": subgrids,
            "nearby_devices": nearby_devices,
            "block_count": len(blocks),
            "device_count": len(devices),
            "damaged_block_count": damaged_count,
            "health_percent": round((1 - damaged_count / max(len(blocks), 1)) * 100, 1),
        }

    # ── Containers / Inventory ──

    def get_grid_containers(self, grid_id: str) -> List[Dict[str, Any]]:
        info = self.get_grid_info(grid_id)
        raw_blocks = info.get("blocks", [])
        if not isinstance(raw_blocks, list):
            return []

        telemetry_map = self._discover_telemetry(grid_id)

        containers = []
        for b in raw_blocks:
            if not isinstance(b, dict) or not b.get("isDevice"):
                continue
            device_id = str(b.get("id") or b.get("blockId") or b.get("entityId") or "")
            device_type = b.get("type") or b.get("blockType") or "unknown"
            subtype = b.get("subtype") or b.get("SubtypeName") or ""
            normalized_type = self._normalize_device_type(device_type, subtype)

            raw_name = b.get("customName") or b.get("CustomName") or b.get("displayName") or b.get("DisplayName") or b.get("name") or ""
            display_name = raw_name or self._humanize_type(subtype or normalized_type)

            telemetry = telemetry_map.get(device_id, {})

            inventories = self._parse_inventories_from_telemetry(telemetry, device_id)
            if not inventories:
                continue

            containers.append({
                "device_id": device_id,
                "display_name": display_name,
                "type": normalized_type,
                "subtype": subtype,
                "inventories": inventories,
            })

        return containers

    @staticmethod
    def _parse_inventories_from_telemetry(telemetry: Dict[str, Any], device_id: str) -> List[Dict[str, Any]]:
        if not isinstance(telemetry, dict):
            return []

        INVENTORY_NAMES = {
            "inputinventory": "Вход",
            "outputinventory": "Выход",
            "fuelinventory": "Топливо",
            "ammunitioninventory": "Боеприпасы",
            "gasinventory": "Газ",
            "oxygeninventory": "Кислород",
        }

        inventories = []
        seen_keys = set()

        raw_list = telemetry.get("inventories")
        if isinstance(raw_list, list):
            for idx, entry in enumerate(raw_list):
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("inventoryKey") or entry.get("key") or f"inventories[{idx}]")
                seen_keys.add(key)
                name = entry.get("name") or entry.get("displayName") or INVENTORY_NAMES.get(key.lower()) or key
                items = FleetRedisReader._parse_items(entry.get("items"))
                current_volume = FleetRedisReader._safe_float(entry.get("currentVolume"))
                max_volume = FleetRedisReader._safe_float(entry.get("maxVolume"))
                current_mass = FleetRedisReader._safe_float(entry.get("currentMass"))
                fill_ratio = FleetRedisReader._safe_float(entry.get("fillRatio"))
                if fill_ratio is None and max_volume and max_volume > 0:
                    fill_ratio = (current_volume or 0) / max_volume
                inventories.append({
                    "key": key,
                    "name": str(name),
                    "index": entry.get("inventoryIndex", idx),
                    "current_volume": current_volume,
                    "max_volume": max_volume,
                    "current_mass": current_mass,
                    "fill_ratio": fill_ratio,
                    "items": items,
                })

        for key, value in telemetry.items():
            if not isinstance(value, dict) or key in seen_keys:
                continue
            lowered = key.lower()
            if "inventory" not in lowered:
                continue
            seen_keys.add(key)
            name = value.get("name") or value.get("displayName") or key
            items = FleetRedisReader._parse_items(value.get("items"))
            current_volume = FleetRedisReader._safe_float(value.get("currentVolume"))
            max_volume = FleetRedisReader._safe_float(value.get("maxVolume"))
            current_mass = FleetRedisReader._safe_float(value.get("currentMass"))
            fill_ratio = FleetRedisReader._safe_float(value.get("fillRatio"))
            if fill_ratio is None and max_volume and max_volume > 0:
                fill_ratio = (current_volume or 0) / max_volume
            inventories.append({
                "key": key,
                "name": str(name),
                "index": value.get("inventoryIndex", 0),
                "current_volume": current_volume,
                "max_volume": max_volume,
                "current_mass": current_mass,
                "fill_ratio": fill_ratio,
                "items": items,
            })

        if isinstance(telemetry.get("items"), list) and "inventory" not in seen_keys:
            items = FleetRedisReader._parse_items(telemetry.get("items"))
            current_volume = FleetRedisReader._safe_float(telemetry.get("currentVolume"))
            max_volume = FleetRedisReader._safe_float(telemetry.get("maxVolume"))
            current_mass = FleetRedisReader._safe_float(telemetry.get("currentMass"))
            fill_ratio = FleetRedisReader._safe_float(telemetry.get("fillRatio"))
            if fill_ratio is None and max_volume and max_volume > 0:
                fill_ratio = (current_volume or 0) / max_volume
            inventories.append({
                "key": "inventory",
                "name": telemetry.get("inventoryName") or "Inventory",
                "index": telemetry.get("inventoryIndex", 0),
                "current_volume": current_volume,
                "max_volume": max_volume,
                "current_mass": current_mass,
                "fill_ratio": fill_ratio,
                "items": items,
            })

        return inventories

    @staticmethod
    def _parse_items(items_payload) -> List[Dict[str, Any]]:
        if not isinstance(items_payload, list):
            return []
        result = []
        for item in items_payload:
            if not isinstance(item, dict):
                continue
            subtype = item.get("subtype") or item.get("subType") or item.get("name") or ""
            amount = FleetRedisReader._safe_float(item.get("amount")) or 0
            display_name = item.get("displayName") or item.get("display_name")
            item_type = item.get("type") or item.get("Type") or ""
            result.append({
                "type": str(item_type),
                "subtype": str(subtype),
                "amount": amount,
                "display_name": str(display_name) if display_name else None,
            })
        return result

    @staticmethod
    def _decode_solid_points(raw: Dict[str, Any]) -> List[List[float]]:
        solid_points = raw.get("solidPoints")
        if isinstance(solid_points, list) and solid_points:
            return solid_points

        solid = raw.get("solid")
        if not isinstance(solid, list) or not solid:
            return []

        size = raw.get("size")
        origin = raw.get("origin")
        cell_size = raw.get("cellSize")
        if not (isinstance(size, list) and len(size) >= 3 and isinstance(origin, list) and len(origin) >= 3 and cell_size is not None):
            return []

        try:
            sx, sy, sz = int(size[0]), int(size[1]), int(size[2])
            ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
            cell = float(cell_size)
        except (TypeError, ValueError):
            return []

        if sx <= 0 or sy <= 0 or sz <= 0 or cell <= 0:
            return []

        points = []
        plane = sy * sz
        for value in solid:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx < 0:
                continue
            x = idx // plane
            yz = idx % plane
            y = yz // sz
            z = yz % sz
            if 0 <= x < sx and 0 <= y < sy and 0 <= z < sz:
                points.append([
                    ox + (x + 0.5) * cell,
                    oy + (y + 0.5) * cell,
                    oz + (z + 0.5) * cell,
                ])
        return points

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ── Nearby grids ──

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
                dist = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5
                g["distance"] = dist
                if dist <= radius:
                    nearby.append(g)
            else:
                g["distance"] = None
                nearby.append(g)
        nearby.sort(key=lambda g: g.get("distance") or float("inf"))
        return nearby

    # ── Devices ──

    def get_devices_summary(self, grid_id: str) -> List[Dict[str, Any]]:
        info = self.get_grid_info(grid_id)
        raw_blocks = info.get("blocks", [])
        if not isinstance(raw_blocks, list):
            return []

        telemetry_map = self._discover_telemetry(grid_id)

        devices = []
        for b in raw_blocks:
            if not isinstance(b, dict) or not b.get("isDevice"):
                continue
            device_id = str(b.get("id") or b.get("blockId") or b.get("entityId") or "")
            device_type = b.get("type") or b.get("blockType") or "unknown"
            subtype = b.get("subtype") or b.get("SubtypeName") or ""
            normalized_type = self._normalize_device_type(device_type, subtype)
            state = self._extract_block_state(b)

            raw_name = b.get("customName") or b.get("CustomName") or b.get("displayName") or b.get("DisplayName") or b.get("name") or ""
            display_name = raw_name or self._humanize_type(subtype or normalized_type)

            telemetry = telemetry_map.get(device_id)

            devices.append({
                "device_id": device_id,
                "name": raw_name,
                "display_name": display_name,
                "type": normalized_type,
                "raw_type": device_type,
                "subtype": subtype,
                "enabled": self._extract_bool(b, "enabled", "isEnabled", "isWorking") or False,
                "is_damaged": self._is_block_damaged(b),
                "state": state,
                "telemetry": telemetry,
                "position": self._extract_block_position(b),
                "custom_data": b.get("customData") or b.get("CustomData") or "",
            })
        return devices

    def get_device_telemetry(self, device_id: str, grid_id: str, device_type: str) -> Optional[Dict[str, Any]]:
        telemetry_map = self._discover_telemetry(grid_id)
        return telemetry_map.get(device_id)

    # ── Commands ──

    def send_grid_command(self, grid_id: str, command: Dict[str, Any]) -> bool:
        if not self.player_id:
            return False
        channel = f"se.{self.player_id}.commands.grid.{grid_id}"
        self._publish(channel, command)
        return True

    def send_device_command(self, device_id: str, command: Dict[str, Any]) -> bool:
        if not self.player_id:
            return False
        channel = f"se.{self.player_id}.commands.device.{device_id}"
        self._publish(channel, command)
        return True

    # ── Voxel scan ──

    _scan_states: Dict[str, Dict[str, Any]] = {}
    _scan_lock = threading.Lock()

    def _find_ore_detector(self, grid_id: str) -> Optional[Dict[str, Any]]:
        info = self.get_grid_info(grid_id)
        raw_blocks = info.get("blocks", [])
        if not isinstance(raw_blocks, list):
            return None
        for b in raw_blocks:
            if not isinstance(b, dict) or not b.get("isDevice"):
                continue
            subtype = (b.get("subtype") or b.get("SubtypeName") or "").lower()
            btype = (b.get("type") or b.get("blockType") or "").lower()
            if "oredetector" in subtype or "ore_detector" in subtype or "ore detector" in subtype:
                return {
                    "device_id": str(b.get("id") or b.get("blockId") or b.get("entityId") or ""),
                    "name": b.get("customName") or b.get("CustomName") or b.get("name") or "Radar",
                    "type": b.get("type") or b.get("blockType") or "",
                }
        return None

    def start_voxel_scan(self, grid_id: str, radius: float = 500, cell_size: float = 10.0, ore_only: bool = True) -> Dict[str, Any]:
        detector = self._find_ore_detector(grid_id)
        if not detector:
            return {"error": "Ore detector not found on grid"}

        with self._scan_lock:
            if grid_id in self._scan_states and self._scan_states[grid_id].get("scanning"):
                return {"error": "Scan already in progress"}

        device_id = detector["device_id"]
        state = {
            "scanning": True,
            "progress": 0.0,
            "status": "starting",
            "detector_name": detector["name"],
            "detector_id": device_id,
            "error": None,
            "result": None,
            "solid_count": 0,
            "ore_count": 0,
        }
        with self._scan_lock:
            self._scan_states[grid_id] = state

        thread = threading.Thread(
            target=self._run_scan,
            args=(grid_id, device_id, radius, cell_size, ore_only),
            daemon=True,
        )
        thread.start()
        return {"ok": True, "detector": detector["name"]}

    def _run_scan(self, grid_id: str, device_id: str, radius: float, cell_size: float, ore_only: bool):
        state = self._scan_states[grid_id]
        try:
            detector_name = state.get("detector_name", "")
            command = {
                "cmd": "scan",
                "targetId": int(device_id),
                "targetName": detector_name,
                "state": {
                    "includePlayers": True,
                    "includeGrids": True,
                    "includeVoxels": True,
                    "oreOnly": ore_only,
                    "radius": radius,
                    "cellSize": cell_size,
                    "voxelStep": 1,
                    "fullSolidScan": True,
                    "resetActiveScan": True,
                    "boundingBoxX": radius * 2,
                    "boundingBoxY": radius * 2,
                    "boundingBoxZ": radius * 2,
                },
            }
            self.send_device_command(device_id, command)

            max_wait = 120.0
            t0 = time.time()
            initial_radar_rev = None
            got_started = False
            scan_completed = False

            pre_telemetry = self._discover_telemetry(grid_id).get(device_id, {})
            pre_radar = pre_telemetry.get("radar", {})
            if isinstance(pre_radar, dict):
                initial_radar_rev = pre_radar.get("revision") or pre_radar.get("rev")

            while time.time() - t0 < max_wait:
                time.sleep(0.5)

                telemetry = self._discover_telemetry(grid_id).get(device_id)
                if not telemetry:
                    continue

                scan_info = telemetry.get("scan", {})
                progress = scan_info.get("progressPercent", 0)
                tiles_done = scan_info.get("processedTiles", 0)
                tiles_total = scan_info.get("totalTiles", 0)
                in_progress = scan_info.get("inProgress", False)
                scan_done = scan_info.get("done", False)

                if tiles_total > 0:
                    got_started = True
                    state["progress"] = round(progress, 1)
                    state["status"] = f"{tiles_done}/{tiles_total} tiles"

                if not in_progress and (scan_done or (got_started and progress >= 99.9)):
                    scan_completed = True

                if scan_completed:
                    radar = telemetry.get("radar", {})
                    if isinstance(radar, dict):
                        radar_done = radar.get("done", False)
                        radar_rev = radar.get("revision") or radar.get("rev")
                        raw = radar.get("raw", {})
                        if isinstance(raw, dict):
                            sp = raw.get("solidPoints", [])
                            has_data = isinstance(sp, list) and len(sp) > 0
                        else:
                            has_data = False

                        if radar_done and (has_data or (radar_rev is not None and radar_rev != initial_radar_rev)):
                            state["progress"] = 100.0
                            state["status"] = "done"
                            state["_radar"] = radar
                            break

                    if time.time() - t0 > 20:
                        state["progress"] = 100.0
                        state["status"] = "done (timeout waiting for radar)"
                        break

            time.sleep(1.0)

            cached_radar = state.pop("_radar", None)
            if cached_radar and isinstance(cached_radar, dict):
                radar = cached_radar
            else:
                telemetry = self._discover_telemetry(grid_id).get(device_id, {})
                radar = telemetry.get("radar", {})
                if not isinstance(radar, dict):
                    radar = {}

            raw = radar.get("raw", {}) if isinstance(radar, dict) else {}
            if not raw:
                raw = radar if isinstance(radar, dict) else {}

            solid = self._decode_solid_points(raw)
            if not solid:
                solid = self._decode_solid_points(radar)

            ore_cells = radar.get("oreCells", []) if isinstance(radar, dict) else []
            if not isinstance(ore_cells, list):
                ore_cells = []

            contacts = radar.get("contacts", []) if isinstance(radar, dict) else []
            if not isinstance(contacts, list):
                contacts = []

            metadata = {
                "size": raw.get("size", [100, 100, 100]),
                "cellSize": raw.get("cellSize", cell_size),
                "origin": raw.get("origin", [0, 0, 0]),
                "rev": raw.get("rev", 0),
            }

            state["scanning"] = False
            state["progress"] = 100.0
            state["status"] = "done"
            state["result"] = {
                "solid": solid,
                "ore_cells": ore_cells,
                "contacts": contacts,
                "metadata": metadata,
            }
            state["solid_count"] = len(solid)
            state["ore_count"] = len(ore_cells)

        except Exception as e:
            state["scanning"] = False
            state["error"] = str(e)
            state["status"] = f"error: {e}"

    def get_scan_status(self, grid_id: str) -> Dict[str, Any]:
        with self._scan_lock:
            return dict(self._scan_states.get(grid_id, {}))

    def get_voxels(self, grid_id: str) -> Optional[Dict[str, Any]]:
        with self._scan_lock:
            state = self._scan_states.get(grid_id)
            if state and state.get("result"):
                return state["result"]
        return None

    def cancel_voxel_scan(self, grid_id: str) -> bool:
        detector = self._find_ore_detector(grid_id)
        if not detector:
            return False
        device_id = detector["device_id"]
        command = {"cmd": "scan", "targetId": int(device_id), "cancel": True}
        ok = self.send_device_command(device_id, command)
        with self._scan_lock:
            if grid_id in self._scan_states:
                self._scan_states[grid_id]["scanning"] = False
                self._scan_states[grid_id]["status"] = "cancelled"
        return ok

    # ── Helpers ──

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
    def _extract_block_state(block: Dict[str, Any]) -> Dict[str, Any]:
        state = block.get("state")
        if isinstance(state, dict):
            return state
        result = {}
        for key in ("integrity", "maxIntegrity", "damaged", "enabled", "isWorking",
                     "isFunctional", "buildPercent", "powerOutput", "maxPowerOutput"):
            val = block.get(key)
            if val is not None:
                result[key] = val
        return result

    @staticmethod
    def _extract_bool(data: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            val = data.get(key)
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return bool(val)
        return None

    @staticmethod
    def _extract_speed(info: Dict[str, Any]) -> Optional[float]:
        for key in ("speed", "gridSpeed", "gridSpeedKph", "linearSpeed"):
            val = info.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        for key in ("velocity", "linearVelocity", "linVel"):
            vel = info.get(key)
            if isinstance(vel, (list, tuple)) and len(vel) >= 3:
                try:
                    return (float(vel[0]) ** 2 + float(vel[1]) ** 2 + float(vel[2]) ** 2) ** 0.5
                except (TypeError, ValueError):
                    pass
            if isinstance(vel, dict) and all(k in vel for k in ("x", "y", "z")):
                try:
                    return (float(vel["x"]) ** 2 + float(vel["y"]) ** 2 + float(vel["z"]) ** 2) ** 0.5
                except (TypeError, ValueError):
                    pass
        return None

    def _extract_grid_orientation(self, grid_id: str) -> Optional[Dict[str, Any]]:
        telemetry_map = self._discover_telemetry(grid_id)
        for device_type in ("remote_control", "cockpit"):
            for did, tel in telemetry_map.items():
                if not isinstance(tel, dict):
                    continue
                t = (tel.get("type") or "").lower()
                sub = (tel.get("subtype") or "").lower()
                if device_type not in t and device_type.replace("_", "") not in sub:
                    continue
                orient = tel.get("orientation")
                speed = None
                vel = tel.get("linearVelocity")
                if isinstance(vel, dict) and "length" in vel:
                    speed = float(vel["length"])
                elif isinstance(vel, dict) and all(k in vel for k in ("x", "y", "z")):
                    speed = (float(vel["x"])**2 + float(vel["y"])**2 + float(vel["z"])**2) ** 0.5
                elif isinstance(tel.get("speed"), (int, float)):
                    speed = float(tel["speed"])
                if isinstance(orient, dict) and "forward" in orient and "up" in orient:
                    fwd = orient["forward"]
                    up = orient["up"]
                    left = orient.get("left")
                    fwd_vec = [float(fwd.get("x", 0)), float(fwd.get("y", 0)), float(fwd.get("z", 0))]
                    up_vec = [float(up.get("x", 0)), float(up.get("y", 0)), float(up.get("z", 0))]
                    if left:
                        left_vec = [float(left.get("x", 0)), float(left.get("y", 0)), float(left.get("z", 0))]
                    else:
                        left_vec = [
                            up_vec[1] * fwd_vec[2] - up_vec[2] * fwd_vec[1],
                            up_vec[2] * fwd_vec[0] - up_vec[0] * fwd_vec[2],
                            up_vec[0] * fwd_vec[1] - up_vec[1] * fwd_vec[0],
                        ]
                    result: Dict[str, Any] = {"forward": fwd_vec, "up": up_vec, "left": left_vec}
                    if speed is not None:
                        result["speed"] = speed
                    pos = tel.get("position")
                    if isinstance(pos, dict) and all(k in pos for k in ("x", "y", "z")):
                        result["device_position"] = [float(pos["x"]), float(pos["y"]), float(pos["z"])]
                    return result
                if speed is not None:
                    return {"speed": speed}
        return None

    @staticmethod
    def _is_block_damaged(block: Dict[str, Any]) -> bool:
        state = block.get("state")
        if isinstance(state, dict):
            if state.get("damaged"):
                return True
            integrity = state.get("integrity")
            max_integrity = state.get("maxIntegrity")
            if isinstance(integrity, (int, float)) and isinstance(max_integrity, (int, float)):
                return integrity < max_integrity
        return False

    @staticmethod
    def _is_block_damaged_raw(block: Dict[str, Any]) -> bool:
        state = block.get("state")
        if isinstance(state, dict):
            if state.get("damaged"):
                return True
            integrity = state.get("integrity")
            max_integrity = state.get("maxIntegrity")
            if isinstance(integrity, (int, float)) and isinstance(max_integrity, (int, float)):
                return integrity < max_integrity
        return False

    @staticmethod
    def _normalize_device_type(block_type: str, subtype: str) -> str:
        t = (subtype or block_type or "").lower()
        t = t.replace("myobjectbuilder_", "")
        mapping = {
            "batteryblock": "battery",
            "smallgatlinggun": "weapon",
            "largegatlinggun": "weapon",
            "smallmissilelauncher": "weapon",
            "smallmissilelauncherreload": "weapon",
            "largemissilelauncher": "weapon",
            "interiorturret": "weapon",
            "largeroadturret": "weapon",
            "smallroadturret": "weapon",
            "largelittleturret": "weapon",
            "smalllittleturret": "weapon",
            "interiorlight": "light",
            "searchlight": "light",
            "smallsteelcrate": "cargo",
            "largesteelcrate": "cargo",
            "mediumsmallcargocontainer": "cargo",
            "mediumlargecargocontainer": "cargo",
            "largecontainer": "cargo",
            "smallcontainer": "cargo",
            "cargocontainer": "cargo",
            "passengerseat": "seat",
            "cowboyseat": "seat",
            "flightseat": "seat",
            "cryopod": " survival",
            "medicalroom": "medical",
            "survivalkit": "medical",
            "programmableblock": "programmable",
            "timerblock": "timer",
            "sensorblock": "sensor",
            "beacon": "beacon",
            "antenna": "antenna",
            "remotecontrol": "remote_control",
            "cockpit": "cockpit",
            "warhead": "weapon",
            "ordo detector": "ore_detector",
            "projector": "projector",
            "mergeblock": "merge",
            "landinggear": "landing_gear",
            "connector": "connector",
            "piston": "piston",
            "rotor": "rotor",
            "hinge": "hinge",
            "gyroscope": "gyroscope",
            "gyro": "gyroscope",
            "thrust": "thruster",
            "solarpanel": "solar",
            "windturbine": "wind_turbine",
            "reactor": "reactor",
            "engine": "engine",
            "assembler": "assembler",
            "refinery": "refinery",
            "arcfurnace": "refinery",
            "drill": "drill",
            "welder": "welder",
            "grinder": "grinder",
            "textpanel": "lcd",
            "lcdpanel": "lcd",
            "buttonpanel": "button",
            "groupbuttonpanel": "button",
            "door": "door",
            "slidingdoor": "door",
            "airvent": "air_vent",
            "airtight": "door",
            "oxygenfarm": "oxygen_farm",
            "hydrogenengine": "engine",
            "wheel": "wheel",
            "suspension": "suspension",
            "motor": "suspension",
            "ai_basic": "ai",
            "ai_flight": "ai",
            "ai_behavior": "ai",
            "ai_defensive": "ai",
            "ai_offensive": "ai",
            "buildandrepair": "build_and_repair",
            "nanobot": "nanobot",
        }
        for key, val in mapping.items():
            if key in t:
                return val
        return t or "generic"

    @staticmethod
    def _humanize_type(raw_type: str) -> str:
        if not raw_type:
            return "Unknown"
        t = raw_type.lower().replace("myobjectbuilder_", "").replace("_", " ").strip()
        words = t.split()
        return " ".join(w.capitalize() for w in words) if words else raw_type
