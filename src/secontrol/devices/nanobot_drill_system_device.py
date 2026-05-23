"""Nanobot Drill System (Drill & Fill) device helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Dict, List, Optional, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class NanobotDrillHashResolver:
    """Voxel material hash resolver for Nanobot Drill and Fill System."""

    ORE_HASHES: Dict[str, int] = {
        "stone": 1137917536,
        "ice": 1579040667,
        "iron": 2112235764,
        "nickel": -723128632,
        "silicon": -122448462,
        "cobalt": -2115209756,
        "magnesium": 2104309205,
        "silver": 1033257407,
        "gold": -496794321,
        "platinum": -510410391,
        "uranium": 1880922462,
    }

    @classmethod
    def resolve_hash(cls, ore_name: str) -> Optional[int]:
        if not ore_name:
            return None
        return cls.ORE_HASHES.get(str(ore_name).strip().lower())

    @classmethod
    def resolve_name(cls, ore_hash: int) -> Optional[str]:
        for name, hash_value in cls.ORE_HASHES.items():
            if hash_value == ore_hash:
                return name
        return None


class NanobotDrillSystemDevice(BaseDevice):
    """High level helper for SELtd Nanobot Drill & Fill systems."""

    device_type = "nanobot_drill_system"
    _PROPERTY_PREFIX = "DrillSystem"

    _WORK_MODE_VALUES: Dict[str, int] = {
        "Fill": 0,
        "Collect": 1,
        "Drill": 2,
    }

    _WORK_MODE_ALIASES: Dict[str, str] = {
        "fill": "Fill",
        "0": "Fill",
        "collect": "Collect",
        "collection": "Collect",
        "1": "Collect",
        "drill": "Drill",
        "mining": "Drill",
        "2": "Drill",
    }

    _COLLECT_RESOURCE_ALIASES: Dict[str, str] = {
        "ingot": "Ingot",
        "ingots": "Ingot",
        "ore": "Ore",
        "ores": "Ore",
        "stone": "Stone",
        "stones": "Stone",
        "rock": "Stone",
        "rocks": "Stone",
        "gravel": "Gravel",
    }

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def load_window(self) -> Optional[int]:
        value = self._load_section().get("window")
        return self._coerce_int(value)

    def load_update_metrics(self) -> Dict[str, float]:
        return self._normalize_metric_section(self._load_section().get("update"))

    def load_command_metrics(self) -> Dict[str, float]:
        return self._normalize_metric_section(self._load_section().get("commands"))

    def load_total_metrics(self) -> Dict[str, float]:
        return self._normalize_metric_section(self._load_section().get("total"))

    def status_summary(self) -> Dict[str, Any]:
        telemetry = self.telemetry or {}
        raw_status = telemetry.get("status")
        if isinstance(raw_status, dict):
            return raw_status
        return {}

    def max_required_input_kw(self) -> Optional[float]:
        status = self.status_summary()
        value = status.get("max_required_input") or status.get("maxRequiredInput")
        return self._coerce_float(value)

    def available_action_ids(self) -> List[str]:
        telemetry = self.telemetry or {}
        raw_actions = telemetry.get("actions")
        action_ids: List[str] = []

        if isinstance(raw_actions, list):
            for entry in raw_actions:
                if not isinstance(entry, dict):
                    continue

                identifier = entry.get("id") or entry.get("action") or entry.get("name")
                if identifier is None:
                    continue

                text = str(identifier).strip()
                if text:
                    action_ids.append(text)

        return action_ids

    def has_action(self, action_id: str) -> bool:
        action_id = str(action_id).strip()
        if not action_id:
            return False
        return action_id in self.available_action_ids()

    def ore_filters(self) -> List[str]:
        telemetry = self.telemetry or {}
        for key in ("oreFilters", "oreFilter", "OreFilter"):
            values = self._normalize_string_list(telemetry.get(key))
            if values:
                return values
        return []

    def known_ore_targets(self) -> List[str]:
        telemetry = self.telemetry or {}
        for key in ("oreTargets", "availableOres", "oreOptions"):
            values = self._normalize_string_list(telemetry.get(key))
            if values:
                return values
        return self.ore_filters()

    # ------------------------------------------------------------------
    # Generic property and action helpers
    # ------------------------------------------------------------------

    def set_property(self, property_name: str, value: Any) -> int:
        qualified_name = f"{self._PROPERTY_PREFIX}.{property_name}"
        return self.send_command(
            {
                "cmd": "set",
                "payload": {
                    "property": qualified_name,
                    "value": value,
                },
            }
        )

    def set_raw_property(self, property_name: str, value: Any) -> int:
        property_name = str(property_name).strip()
        if not property_name:
            raise ValueError("property_name must not be empty")

        return self.send_command(
            {
                "cmd": "set",
                "payload": {
                    "property": property_name,
                    "value": value,
                },
            }
        )

    def run_action(self, action_id: str) -> int:
        action_id = str(action_id).strip()
        if not action_id:
            raise ValueError("action_id must not be empty")

        return self.send_command(
            {
                "command": action_id,
                "payload": {},
            }
        )

    # ------------------------------------------------------------------
    # Basic block controls
    # ------------------------------------------------------------------

    def turn_on(self) -> int:
        sent = self.set_show_area(True)
        sent += self.run_action("OnOff_On")
        return sent

    def turn_off(self) -> int:
        sent = self.set_show_area(False)
        sent += self.run_action("OnOff_Off")
        return sent

    def toggle_power(self) -> int:
        return self.run_action("OnOff")

    def set_script_controlled(self, enabled: bool) -> int:
        return self.set_property("ScriptControlled", bool(enabled))

    def toggle_script_controlled(self) -> int:
        return self.run_action("ScriptControlled_OnOff")

    def set_script_controlled_action(self, enabled: bool) -> int:
        return self.run_action("ScriptControlled_On" if enabled else "ScriptControlled_Off")

    def set_use_conveyor(self, enabled: bool) -> int:
        return self.set_property("UseConveyor", bool(enabled))

    def toggle_use_conveyor(self) -> int:
        return self.run_action("UseConveyor")

    def set_collect_if_idle(self, enabled: bool) -> int:
        return self.set_property("CollectIfIdle", bool(enabled))

    def toggle_collect_if_idle(self) -> int:
        return self.run_action("CollectIfIdle_OnOff")

    def set_show_area(self, enabled: bool) -> int:
        return self.set_raw_property("Drill.ShowArea", bool(enabled))

    def toggle_show_area(self) -> int:
        return self.run_action("ShowArea_OnOff")

    def set_terrain_clearing_mode(self, enabled: bool) -> int:
        return self.set_property("TerrainClearingMode", bool(enabled))

    def toggle_terrain_clearing_mode(self) -> int:
        return self.run_action("TerrainClearingMode")

    def set_terrain_clearing_mode_action(self, enabled: bool) -> int:
        return self.run_action(
            "TerrainClearingMode_On" if enabled else "TerrainClearingMode_Off"
        )

    # ------------------------------------------------------------------
    # Nanobot Drill / Collect filters
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    @staticmethod
    def _split_filter_values(values: Any) -> List[str]:
        if values is None:
            return []

        raw_items: List[str] = []

        if isinstance(values, str):
            raw_items = re.split(r"[,;|\s]+", values.strip())
        elif isinstance(values, Iterable):
            for value in values:
                if value is None:
                    continue
                if isinstance(value, str):
                    raw_items.extend(re.split(r"[,;|\s]+", value.strip()))
                else:
                    raw_items.append(str(value))
        else:
            raw_items = [str(values)]

        result: List[str] = []
        seen: set[str] = set()

        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue

            key = text.lower()
            if key in seen:
                continue

            seen.add(key)
            result.append(text)

        return result

    @classmethod
    def _normalize_work_mode(cls, mode: Any) -> str:
        text = str(mode).strip()
        key = text.lower()

        canonical = cls._WORK_MODE_ALIASES.get(key)
        if canonical is None:
            raise ValueError("Invalid work mode. Use: Fill, Collect, Drill")

        return canonical

    @classmethod
    def _work_mode_value(cls, mode: Any) -> int:
        canonical = cls._normalize_work_mode(mode)
        return cls._WORK_MODE_VALUES[canonical]

    @classmethod
    def _normalize_collect_resources(cls, resources: Any) -> List[str]:
        values = cls._split_filter_values(resources)
        if not values:
            return []

        result: List[str] = []
        seen: set[str] = set()

        for value in values:
            key = value.lower().strip()

            if key in {"all", "*", "none", "off"}:
                canonical = key
            else:
                canonical = cls._COLLECT_RESOURCE_ALIASES.get(key)
                if canonical is None:
                    raise ValueError(
                        f"Unknown collect resource '{value}'. "
                        "Use: Ingot, Ore, Stone, Gravel, all, none"
                    )

            dedupe_key = canonical.lower()
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            result.append(canonical)

        return result

    def _get_telemetry_property(self, *property_names: str) -> Any:
        telemetry = self.telemetry or {}

        props = telemetry.get("properties")
        if isinstance(props, dict):
            for name in property_names:
                if name in props:
                    return props[name]

            normalized_targets = {self._normalize_key(name) for name in property_names}
            for key, value in props.items():
                if self._normalize_key(key) in normalized_targets:
                    return value

        for name in property_names:
            if name in telemetry:
                return telemetry[name]

        normalized_targets = {self._normalize_key(name) for name in property_names}
        for key, value in telemetry.items():
            if self._normalize_key(key) in normalized_targets:
                return value

        return None

    def _get_drill_priority_list(self) -> List[str]:
        raw_list = self._get_telemetry_property(
            "Drill.DrillPriorityList",
            "DrillPriorityList",
            "drill_drill_priority_list",
            "drill_priority_list",
            "drill_drillprioritylist",
            "drillprioritylist",
        )

        if isinstance(raw_list, list):
            return self._normalize_string_list(raw_list)

        return []

    @staticmethod
    def _parse_priority_entry(entry: str) -> Optional[Tuple[int, bool]]:
        if not entry:
            return None

        parts = str(entry).split(";")
        if not parts:
            return None

        try:
            ore_hash = int(parts[0].strip())
        except ValueError:
            return None

        enabled = True
        if len(parts) >= 2:
            flag = parts[1].strip().lower()
            if flag in {"false", "0", "no", "off"}:
                enabled = False
            elif flag in {"true", "1", "yes", "on"}:
                enabled = True

        return ore_hash, enabled

    @staticmethod
    def _format_priority_entry(ore_hash: int, enabled: bool) -> str:
        return f"{int(ore_hash)};{bool(enabled)}"

    def _get_drill_priority_map(self) -> Tuple[List[int], Dict[int, bool]]:
        entries = self._get_drill_priority_list()
        order: List[int] = []
        state: Dict[int, bool] = {}

        for entry in entries:
            parsed = self._parse_priority_entry(entry)
            if parsed is None:
                continue

            ore_hash, enabled = parsed
            if ore_hash not in order:
                order.append(ore_hash)
            state[ore_hash] = enabled

        return order, state

    def set_work_mode(self, mode: str) -> int:
        mode_value = self._work_mode_value(mode)

        return self.send_command(
            {
                "cmd": "set",
                "payload": {
                    "property": "Drill.WorkMode",
                    "value": mode_value,
                },
            }
        )

    def get_work_mode(self) -> Optional[str]:
        mode_raw = self._get_telemetry_property(
            "Drill.WorkMode",
            "WorkMode",
            "drill_work_mode",
            "drill_workmode",
            "work_mode",
            "workmode",
        )

        if mode_raw is None:
            return None

        mode_map = {
            0: "Fill",
            1: "Collect",
            2: "Drill",
        }

        if isinstance(mode_raw, int):
            return mode_map.get(mode_raw, str(mode_raw))

        text = str(mode_raw).strip()

        try:
            number = int(text)
            return mode_map.get(number, text)
        except ValueError:
            pass

        return self._WORK_MODE_ALIASES.get(text.lower(), text)

    def set_ore_filters(self, ore_subtypes: Any, work_mode: str = "Collect") -> int:
        ores = self._split_filter_values(ore_subtypes)
        if not ores:
            raise ValueError("ore_subtypes must not be empty")

        mode_value = self._work_mode_value(work_mode)

        return self.send_command(
            {
                "command": "OreFilter",
                "payload": {
                    "ores": ores,
                    "workMode": mode_value,
                    "applyCollectFilter": True,
                },
            }
        )

    def set_ore_filter(self, ore_subtype: str, work_mode: str = "Collect") -> int:
        ore = str(ore_subtype).strip()
        if not ore:
            raise ValueError("ore_subtype must not be empty")

        return self.set_ore_filters([ore], work_mode=work_mode)

    def clear_ore_filters(self, work_mode: str = "Collect") -> int:
        mode_value = self._work_mode_value(work_mode)

        return self.send_command(
            {
                "command": "OreFilter",
                "payload": {
                    "ores": ["none"],
                    "workMode": mode_value,
                    "applyCollectFilter": False,
                },
            }
        )

    def enable_all_ore_filters(self, work_mode: str = "Collect") -> int:
        mode_value = self._work_mode_value(work_mode)

        return self.send_command(
            {
                "command": "OreFilter",
                "payload": {
                    "ores": ["all"],
                    "workMode": mode_value,
                    "applyCollectFilter": False,
                },
            }
        )

    def set_collect_filter(self, resources: Any = ("Ore",)) -> int:
        normalized_resources = self._normalize_collect_resources(resources)
        if not normalized_resources:
            raise ValueError("resources must not be empty")

        return self.send_command(
            {
                "command": "CollectFilter",
                "payload": {
                    "resources": normalized_resources,
                },
            }
        )

    def clear_collect_filter(self) -> int:
        return self.set_collect_filter(["none"])

    def enable_all_collect_filter(self) -> int:
        return self.set_collect_filter(["all"])

    def configure_ore_collection(
        self,
        ore_subtypes: Any,
        work_mode: str = "Collect",
        collect_resources: Any = ("Ore",),
        script_controlled: bool = True,
    ) -> int:
        sent = 0

        if script_controlled:
            sent += self.set_script_controlled(True)

        sent += self.set_collect_filter(collect_resources)
        sent += self.set_ore_filters(ore_subtypes, work_mode=work_mode)

        return sent

    def configure_only_uranium(self) -> int:
        return self.configure_ore_collection(
            ore_subtypes=["Uranium"],
            work_mode="Collect",
            collect_resources=["Ore"],
            script_controlled=True,
        )

    def set_ore_collection_priority(self, ore_name: str, collect: bool = True) -> int:
        ore_name = str(ore_name).strip()
        if not ore_name:
            raise ValueError("ore_name must not be empty")

        ore_hash = NanobotDrillHashResolver.resolve_hash(ore_name)
        if ore_hash is None:
            raise ValueError(f"Unknown ore name '{ore_name}'. Cannot resolve hash.")

        _order, state = self._get_drill_priority_map()
        enabled_hashes: set[int] = {h for h, enabled in state.items() if enabled}

        if collect:
            enabled_hashes.add(ore_hash)
        else:
            enabled_hashes.discard(ore_hash)

        enabled_names: List[str] = []
        for h in enabled_hashes:
            name = NanobotDrillHashResolver.resolve_name(h)
            if name is not None:
                enabled_names.append(name)

        if not enabled_names:
            return self.clear_ore_filters()

        return self.set_ore_filters(sorted(enabled_names))

    # ------------------------------------------------------------------
    # Drill actions
    # ------------------------------------------------------------------

    def start_drilling(self) -> int:
        return self.run_action("Drill_On")

    def stop_drilling(self) -> int:
        if self.has_action("Drill_Off"):
            return self.run_action("Drill_Off")
        return self.turn_off()

    def start_collecting(self) -> int:
        if self.has_action("Collect_On"):
            return self.run_action("Collect_On")
        return self.run_action("CollectIfIdle_On")

    def start_filling(self) -> int:
        return self.run_action("Fill_On")

    def start_drilling_ore(
        self,
        ore_subtypes: Any,
        collect_resources: Any = ("Ore",),
        work_mode: str = "Collect",
    ) -> int:
        sent = 0
        sent += self.stop_drilling()
        sent += self.turn_off()
        sent += self.set_script_controlled(True)
        sent += self.set_collect_filter(collect_resources)
        sent += self.set_ore_filters(ore_subtypes, work_mode=work_mode)
        sent += self.set_work_mode(work_mode)
        sent += self.set_script_controlled(False)
        sent += self.turn_on()
        return sent

    def set_collect_on_idle(self, enabled: bool) -> int:
        if enabled:
            return self.run_action("CollectIfIdle_On")
        return self.run_action("CollectIfIdle_Off")

    def toggle_collect_if_idle_action(self) -> int:
        return self.run_action("CollectIfIdle_OnOff")

    def set_show_on_hud(self, enabled: bool) -> int:
        return self.run_action("ShowOnHUD_On" if enabled else "ShowOnHUD_Off")

    def toggle_show_on_hud(self) -> int:
        return self.run_action("ShowOnHUD")

    def set_show_area_action(self, enabled: bool) -> int:
        return self.run_action("ShowArea_On" if enabled else "ShowArea_Off")

    def set_remote_control_show_area(self, enabled: bool) -> int:
        return self.run_action(
            "RemoteControlShowArea_On" if enabled else "RemoteControlShowArea_Off"
        )

    def set_remote_control_work_disabled(self, enabled: bool) -> int:
        return self.run_action(
            "RemoteControlWorkdisabled_On"
            if enabled
            else "RemoteControlWorkdisabled_Off"
        )

    # ------------------------------------------------------------------
    # Area controls
    # ------------------------------------------------------------------

    def increase_area_offset_left_right(self) -> int:
        return self.run_action("AreaOffsetLeftRight_Increase")

    def decrease_area_offset_left_right(self) -> int:
        return self.run_action("AreaOffsetLeftRight_Decrease")

    def increase_area_offset_up_down(self) -> int:
        return self.run_action("AreaOffsetUpDown_Increase")

    def decrease_area_offset_up_down(self) -> int:
        return self.run_action("AreaOffsetUpDown_Decrease")

    def increase_area_offset_front_back(self) -> int:
        return self.run_action("AreaOffsetFrontBack_Increase")

    def decrease_area_offset_front_back(self) -> int:
        return self.run_action("AreaOffsetFrontBack_Decrease")

    def increase_area_width(self) -> int:
        return self.run_action("AreaWidth_Increase")

    def decrease_area_width(self) -> int:
        return self.run_action("AreaWidth_Decrease")

    def increase_area_height(self) -> int:
        return self.run_action("AreaHeight_Increase")

    def decrease_area_height(self) -> int:
        return self.run_action("AreaHeight_Decrease")

    def increase_area_depth(self) -> int:
        return self.run_action("AreaDepth_Increase")

    def decrease_area_depth(self) -> int:
        return self.run_action("AreaDepth_Decrease")

    def increase_sound_volume(self) -> int:
        return self.run_action("SoundVolume_Increase")

    def decrease_sound_volume(self) -> int:
        return self.run_action("SoundVolume_Decrease")

        # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------

    def debug_get_priority_list_raw(self) -> List[str]:
        return list(self._get_drill_priority_list())

    def debug_get_collect_priority_list_raw(self) -> List[str]:
        raw_list = self._get_telemetry_property(
            "Drill.CollectPriorityList",
            "CollectPriorityList",
            "collectPriorityList",
            "collect_priority_list",
            "drill_collectprioritylist",
            "collectprioritylist",
        )

        if isinstance(raw_list, list):
            return self._normalize_string_list(raw_list)

        return []

    def debug_get_resource_filter_indices(self) -> List[int]:
        telemetry = self.telemetry or {}
        result: List[int] = []

        raw_values = (
            telemetry.get("resourceFilterIndices")
            or telemetry.get("collectFilterIndices")
            or []
        )

        if isinstance(raw_values, list):
            for value in raw_values:
                try:
                    result.append(int(value))
                except (TypeError, ValueError):
                    continue

        return result

    def debug_get_enabled_known_ores(self) -> Dict[str, bool]:
        result: Dict[str, bool] = {}
        entries = self._get_drill_priority_list()

        if not entries:
            return result

        telemetry = self.telemetry or {}
        indices = telemetry.get("oreFilterIndices")

        if isinstance(indices, list):
            enabled_indices = set()
            for value in indices:
                try:
                    enabled_indices.add(int(value))
                except (TypeError, ValueError):
                    continue

            for idx, entry in enumerate(entries):
                parsed = self._parse_priority_entry(entry)
                if parsed is None:
                    continue

                ore_hash, _enabled = parsed
                name = NanobotDrillHashResolver.resolve_name(ore_hash)
                if name:
                    result[name] = idx in enabled_indices

            return result

        for entry in entries:
            parsed = self._parse_priority_entry(entry)
            if parsed is None:
                continue

            ore_hash, enabled = parsed
            name = NanobotDrillHashResolver.resolve_name(ore_hash)
            if name:
                result[name] = enabled

        return result

    def debug_status(self) -> Dict[str, Any]:
        return {
            "workMode": self.get_work_mode(),
            "drillPriorityList": self.debug_get_priority_list_raw(),
            "collectPriorityList": self.debug_get_collect_priority_list_raw(),
            "enabledKnownOres": self.debug_get_enabled_known_ores(),
            "resourceFilterIndices": self.debug_get_resource_filter_indices(),
            "oreFilters": self.ore_filters(),
            "knownOreTargets": self.known_ore_targets(),
            "actions": self.available_action_ids(),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_section(self) -> Dict[str, Any]:
        telemetry = self.telemetry or {}
        load = telemetry.get("load")
        if isinstance(load, dict):
            return load
        return {}

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            match = re.search(r"[-+]?[0-9]*\.?[0-9]+", value)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    return None

        return None

    def _normalize_metric_section(self, section: Any) -> Dict[str, float]:
        metrics: Dict[str, float] = {}

        if isinstance(section, dict):
            for key, value in section.items():
                number = self._coerce_float(value)
                if number is None:
                    continue
                metrics[str(key)] = number

        return metrics

    @staticmethod
    def _normalize_string_list(values: Any) -> List[str]:
        if values is None:
            return []

        if isinstance(values, str):
            cleaned = values.strip()
            return [cleaned] if cleaned else []

        result: List[str] = []

        if isinstance(values, Iterable):
            for value in values:
                text = str(value).strip()
                if text:
                    result.append(text)

        return result


DEVICE_TYPE_MAP[NanobotDrillSystemDevice.device_type] = NanobotDrillSystemDevice