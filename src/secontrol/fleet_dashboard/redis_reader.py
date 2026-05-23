import json
import os
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
        self.player_id = os.getenv("SE_PLAYER_ID", "")
        self.client = redis.Redis(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
            username=username or None,
            password=password or None,
            decode_responses=True,
            socket_keepalive=True,
        )

    def _get_json(self, key: str) -> Optional[Dict[str, Any]]:
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
        return self.client.publish(channel, json.dumps(payload))

    # ── Telemetry discovery ──

    def _discover_telemetry(self, grid_id: str) -> Dict[str, Dict[str, Any]]:
        """Scan Redis for all telemetry keys in a grid, return {device_id: telemetry_dict}."""
        pattern = f"se:{self.owner_id}:grid:{grid_id}:*:*:telemetry"
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for key in self.client.scan_iter(match=pattern, count=200):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")
                parts = key.split(":")
                if len(parts) != 7 or parts[6] != "telemetry":
                    continue
                device_id = parts[5]
                telemetry = self._get_json(key)
                if isinstance(telemetry, dict):
                    result[device_id] = telemetry
        except Exception:
            pass
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

        return {
            "grid_id": grid_id,
            "name": name or f"Grid_{grid_id}",
            "position": position,
            "is_static": is_static,
            "speed": speed,
            "blocks": blocks,
            "devices": devices,
            "subgrids": subgrids,
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

        CONTAINER_TYPES = {
            "cargo", "container", "cargo_container",
            "assembler", "refinery", "arcfurnace",
            "gas_generator", "oxygen_farm",
            "medical", "medical_room", "survival_kit",
            "drill", "ship_drill", "nanobot",
            "gas_tank", "hydrogen_tank", "oxygen_tank",
        }

        containers = []
        for b in raw_blocks:
            if not isinstance(b, dict) or not b.get("isDevice"):
                continue
            device_id = str(b.get("id") or b.get("blockId") or b.get("entityId") or "")
            device_type = b.get("type") or b.get("blockType") or "unknown"
            subtype = b.get("subtype") or b.get("SubtypeName") or ""
            normalized_type = self._normalize_device_type(device_type, subtype)

            if normalized_type not in CONTAINER_TYPES:
                continue

            raw_name = b.get("customName") or b.get("CustomName") or b.get("displayName") or b.get("DisplayName") or b.get("name") or ""
            display_name = raw_name or self._humanize_type(subtype or normalized_type)

            telemetry = telemetry_map.get(device_id, {})

            inventories = self._parse_inventories_from_telemetry(telemetry, device_id)

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

        inventories = []
        seen_keys = set()

        raw_list = telemetry.get("inventories")
        if isinstance(raw_list, list):
            for idx, entry in enumerate(raw_list):
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("inventoryKey") or entry.get("key") or f"inventories[{idx}]")
                seen_keys.add(key)
                name = entry.get("name") or entry.get("displayName") or key
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
