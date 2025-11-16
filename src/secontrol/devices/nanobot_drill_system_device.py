"""Nanobot drill system device wrapper for Space Engineers grid control.

This module provides functionality to control nanobot drills on SE grids,
including setting operational modes and adjusting drilling area parameters.
"""

from __future__ import annotations

from typing import Any, Dict

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class NanobotDrillSystemDevice(BaseDevice):
    """Device wrapper for nanobot drill systems with parameter control."""

    device_type = "nanobot_drill_system"

    def __init__(self, grid, metadata):
        # Cache drill-specific telemetry fields
        self._enabled = False
        self._is_functional = True
        self._is_working = False
        self._use_conveyor = True
        self._terrain_clearing_mode = False
        self._collect_if_idle = False
        self._show_area = False
        self._remote_control_show_area = False
        self._remote_control_work_disabled = False
        self._script_controlled = False
        self._sound_volume = 0.0

        super().__init__(grid, metadata)

    def handle_telemetry(self, telemetry):
        """Handle telemetry update and cache drill-specific fields."""
        super().handle_telemetry(telemetry)

        # Cache fields from telemetry
        self._enabled = bool(telemetry.get("enabled", self._enabled))
        self._is_functional = bool(telemetry.get("isFunctional", self._is_functional))
        self._is_working = bool(telemetry.get("isWorking", self._is_working))

        # Load metrics if available
        load = telemetry.get("load", {})
        if isinstance(load, dict):
            self._load_metrics = load.copy()

    # ----------------------- Core Controls -----------------------

    def enable(self) -> int:
        """Enable the drill."""
        return self.send_command({"cmd": "action", "actionId": "OnOff_On"})

    def disable(self) -> int:
        """Disable the drill."""
        return self.send_command({"cmd": "action", "actionId": "OnOff_Off"})

    def toggle_enabled(self) -> int:
        """Toggle the drill on/off."""
        return self.send_command({"cmd": "action", "actionId": "OnOff"})

    def show_on_hud_on(self) -> int:
        """Show drill on HUD."""
        return self.send_command({"cmd": "action", "actionId": "ShowOnHUD_On"})

    def show_on_hud_off(self) -> int:
        """Hide drill on HUD."""
        return self.send_command({"cmd": "action", "actionId": "ShowOnHUD_Off"})

    def toggle_show_on_hud(self) -> int:
        """Toggle show on HUD."""
        return self.send_command({"cmd": "action", "actionId": "ShowOnHUD"})

    def set_use_conveyor(self, enabled: bool) -> int:
        """Enable/disable conveyor system."""
        action_id = "UseConveyor_On" if enabled else "UseConveyor_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    # ----------------------- Operational Modes -----------------------

    def drill_on(self) -> int:
        """Enable drill mode."""
        return self.send_command({"cmd": "action", "actionId": "Drill_On"})

    def fill_on(self) -> int:
        """Enable fill mode."""
        return self.send_command({"cmd": "action", "actionId": "Fill_On"})

    def collect_on(self) -> int:
        """Enable collect mode."""
        return self.send_command({"cmd": "action", "actionId": "Collect_On"})

    def set_terrain_clearing_mode(self, enabled: bool) -> int:
        """Enable/disable terrain clearing mode."""
        action_id = "TerrainClearingMode_On" if enabled else "TerrainClearingMode_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    def toggle_terrain_clearing_mode(self) -> int:
        """Toggle terrain clearing mode."""
        return self.send_command({"cmd": "action", "actionId": "TerrainClearingMode"})

    def set_collect_if_idle(self, enabled: bool) -> int:
        """Enable/disable collect if idle."""
        action_id = "CollectIfIdle_On" if enabled else "CollectIfIdle_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    def toggle_collect_if_idle(self) -> int:
        """Toggle collect if idle."""
        return self.send_command({"cmd": "action", "actionId": "CollectIfIdle_OnOff"})

    # ----------------------- Area Parameters -----------------------

    # Offset Left/Right
    def increase_area_offset_leftright(self) -> int:
        """Increase area offset left/right."""
        return self.send_command({"cmd": "action", "actionId": "AreaOffsetLeftRight_Increase"})

    def decrease_area_offset_leftright(self) -> int:
        """Decrease area offset left/right."""
        return self.send_command({"cmd": "action", "actionId": "AreaOffsetLeftRight_Decrease"})

    # Offset Up/Down
    def increase_area_offset_updown(self) -> int:
        """Increase area offset up/down."""
        return self.send_command({"cmd": "action", "actionId": "AreaOffsetUpDown_Increase"})

    def decrease_area_offset_updown(self) -> int:
        """Decrease area offset up/down."""
        return self.send_command({"cmd": "action", "actionId": "AreaOffsetUpDown_Decrease"})

    # Offset Front/Back
    def increase_area_offset_frontback(self) -> int:
        """Increase area offset front/back."""
        return self.send_command({"cmd": "action", "actionId": "AreaOffsetFrontBack_Increase"})

    def decrease_area_offset_frontback(self) -> int:
        """Decrease area offset front/back."""
        return self.send_command({"cmd": "action", "actionId": "AreaOffsetFrontBack_Decrease"})

    # Area Width
    def increase_area_width(self) -> int:
        """Increase area width."""
        return self.send_command({"cmd": "action", "actionId": "AreaWidth_Increase"})

    def decrease_area_width(self) -> int:
        """Decrease area width."""
        return self.send_command({"cmd": "action", "actionId": "AreaWidth_Decrease"})

    # Area Height
    def increase_area_height(self) -> int:
        """Increase area height."""
        return self.send_command({"cmd": "action", "actionId": "AreaHeight_Increase"})

    def decrease_area_height(self) -> int:
        """Decrease area height."""
        return self.send_command({"cmd": "action", "actionId": "AreaHeight_Decrease"})

    # Area Depth
    def increase_area_depth(self) -> int:
        """Increase area depth."""
        return self.send_command({"cmd": "action", "actionId": "AreaDepth_Increase"})

    def decrease_area_depth(self) -> int:
        """Decrease area depth."""
        return self.send_command({"cmd": "action", "actionId": "AreaDepth_Decrease"})

    # ----------------------- Visualization -----------------------

    def set_show_area(self, enabled: bool) -> int:
        """Enable/disable show area."""
        action_id = "ShowArea_On" if enabled else "ShowArea_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    def toggle_show_area(self) -> int:
        """Toggle show area."""
        return self.send_command({"cmd": "action", "actionId": "ShowArea_OnOff"})

    def set_remote_control_show_area(self, enabled: bool) -> int:
        """Enable/disable remote control show area."""
        action_id = "RemoteControlShowArea_On" if enabled else "RemoteControlShowArea_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    def toggle_remote_control_show_area(self) -> int:
        """Toggle remote control show area."""
        return self.send_command({"cmd": "action", "actionId": "RemoteControlShowArea_OnOff"})

    # ----------------------- Remote Control -----------------------

    def set_remote_control_work_disabled(self, disabled: bool) -> int:
        """Enable/disable remote control work disabled."""
        action_id = "RemoteControlWorkdisabled_On" if disabled else "RemoteControlWorkdisabled_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    def toggle_remote_control_work_disabled(self) -> int:
        """Toggle remote control work disabled."""
        return self.send_command({"cmd": "action", "actionId": "RemoteControlWorkdisabled_OnOff"})

    # ----------------------- Sound and Script -----------------------

    def increase_sound_volume(self) -> int:
        """Increase sound volume."""
        return self.send_command({"cmd": "action", "actionId": "SoundVolume_Increase"})

    def decrease_sound_volume(self) -> int:
        """Decrease sound volume."""
        return self.send_command({"cmd": "action", "actionId": "SoundVolume_Decrease"})

    def set_script_controlled(self, controlled: bool) -> int:
        """Enable/disable script controlled."""
        action_id = "ScriptControlled_On" if controlled else "ScriptControlled_Off"
        return self.send_command({"cmd": "action", "actionId": action_id})

    def toggle_script_controlled(self) -> int:
        """Toggle script controlled."""
        return self.send_command({"cmd": "action", "actionId": "ScriptControlled_OnOff"})

    # ----------------------- Telemetry Properties -----------------------

    def is_enabled(self) -> bool:
        """Get enabled state."""
        if isinstance(self.telemetry, dict) and "enabled" in self.telemetry:
            return bool(self.telemetry["enabled"])
        return self._enabled

    def is_functional(self) -> bool:
        """Get functional state."""
        if isinstance(self.telemetry, dict) and "isFunctional" in self.telemetry:
            return bool(self.telemetry["isFunctional"])
        return self._is_functional

    def is_working(self) -> bool:
        """Get working state."""
        if isinstance(self.telemetry, dict) and "isWorking" in self.telemetry:
            return bool(self.telemetry["isWorking"])
        return self._is_working

    def uses_conveyor(self) -> bool:
        """Get conveyor usage state."""
        return self._use_conveyor

    def terrain_clearing_mode_enabled(self) -> bool:
        """Get terrain clearing mode state."""
        return self._terrain_clearing_mode

    def collect_if_idle_enabled(self) -> bool:
        """Get collect if idle state."""
        return self._collect_if_idle

    def show_area_enabled(self) -> bool:
        """Get show area state."""
        return self._show_area

    def required_input_power(self) -> float:
        """Get required input power (kW)."""
        status = self.telemetry.get("status", {}) if self.telemetry else {}
        return float(status.get("max_required_input", 0.0))


DEVICE_TYPE_MAP[NanobotDrillSystemDevice.device_type] = NanobotDrillSystemDevice
