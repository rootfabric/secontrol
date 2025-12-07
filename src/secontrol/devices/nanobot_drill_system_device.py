"""Nanobot Drill System (Drill & Fill) device helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Dict, List, Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class NanobotDrillSystemDevice(BaseDevice):
    """High level helper for SELtd Nanobot Drill & Fill systems."""

    device_type = "nanobot_drill_system"
    _PROPERTY_PREFIX = "DrillSystem"

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
        number = self._coerce_float(value)
        return number

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
    # Property and command helpers
    # ------------------------------------------------------------------
    def set_property(self, property_name: str, value: Any) -> int:
        qualified_name = f"{self._PROPERTY_PREFIX}.{property_name}"
        return self.send_command({
            "cmd": "set",
            "payload": {
                "property": qualified_name,
                "value": value,
            },
        })

    def run_action(self, action_id: str) -> int:
        """Запустить терминальное действие Nanobot Drill System.

        В отличие от общих команд ``cmd``/``set`` для действий над нано-буром
        плагин ожидает текст идентификатора действия. Чтобы повысить
        совместимость, отправляем его в полях ``command`` и ``cmd`` и
        продублируем в ``payload``.
        """

        action_id = str(action_id).strip()
        if not action_id:
            raise ValueError("action_id must not be empty")

        return self.send_command({
            "cmd": action_id,
            "command": action_id,
            "payload": {
                "action": action_id,
                "command": action_id,
            },
        })

    def turn_on(self) -> int:
        return self.run_action("OnOff_On")

    def turn_off(self) -> int:
        return self.run_action("OnOff_Off")

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
        return self.set_property("ShowArea", bool(enabled))

    def toggle_show_area(self) -> int:
        return self.run_action("ShowArea_OnOff")

    def set_terrain_clearing_mode(self, enabled: bool) -> int:
        return self.set_property("TerrainClearingMode", bool(enabled))

    def toggle_terrain_clearing_mode(self) -> int:
        return self.run_action("TerrainClearingMode")

    def set_terrain_clearing_mode_action(self, enabled: bool) -> int:
        return self.run_action("TerrainClearingMode_On" if enabled else "TerrainClearingMode_Off")

    def set_ore_filters(self, ore_subtypes: Iterable[str]) -> int:
        normalized = self._normalize_string_list(list(ore_subtypes))
        if not normalized:
            raise ValueError("ore_subtypes must contain at least one ore name")
        return self.set_property("OreFilter", normalized)

    def set_ore_filter(self, ore_subtype: str) -> int:
        ore = str(ore_subtype).strip()
        if not ore:
            raise ValueError("ore_subtype must not be empty")
        return self.set_ore_filters([ore])

    def clear_ore_filters(self) -> int:
        return self.set_property("OreFilter", [])

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
        return self.run_action("RemoteControlShowArea_On" if enabled else "RemoteControlShowArea_Off")

    def set_remote_control_work_disabled(self, enabled: bool) -> int:
        return self.run_action("RemoteControlWorkdisabled_On" if enabled else "RemoteControlWorkdisabled_Off")

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
