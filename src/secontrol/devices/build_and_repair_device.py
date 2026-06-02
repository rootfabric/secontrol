"""Build and Repair (Nanobot) device helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


COMPONENT_DISPLAY_NAMES_RU: dict[str, str] = {
    "SteelPlate": "Стальная пластина",
    "InteriorPlate": "Внутренняя пластина",
    "Construction": "Строительный компонент",
    "Motor": "Мотор",
    "Computer": "Компьютер",
    "Display": "Дисплей",
    "Girder": "Балка",
    "SmallTube": "Малая стальная труба",
    "LargeTube": "Большая стальная труба",
    "MetalGrid": "Металлическая решётка",
    "BulletproofGlass": "Бронированное стекло",
    "Reactor": "Компонент реактора",
    "Thrust": "Компонент двигателя",
    "GravityGenerator": "Компонент генератора гравитации",
    "Medical": "Медицинский компонент",
    "RadioCommunication": "Радиокомпонент",
    "Detector": "Компонент детектора",
    "Explosives": "Взрывчатка",
    "SolarCell": "Солнечная ячейка",
    "PowerCell": "Энергоячейка",
    "Superconductor": "Сверхпроводник",
    "ZoneChip": "Чип зоны",
}


def _amount_as_number(value: Any) -> float | int | Any:
    if isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if abs(number - round(number)) < 0.000001:
        return int(round(number))
    return round(number, 6)


def _display_name(name: str) -> str:
    return COMPONENT_DISPLAY_NAMES_RU.get(name, name)


def normalize_missing_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize BaR missing component telemetry to a stable list."""
    items = data.get("missingItemsList")
    if isinstance(items, list) and items:
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("definitionId") or item.get("key") or "?")
            amount = _amount_as_number(item.get("amount"))
            result.append({
                "name": name,
                "display_name": _display_name(name),
                "amount": amount,
                "key": str(item.get("key") or name),
                "definition_id": item.get("definitionId"),
            })
        return result

    missing = data.get("missingComponents") or data.get("missingItems") or {}
    if isinstance(missing, dict):
        result = []
        for key, value in missing.items():
            name = str(key)
            result.append({
                "name": name,
                "display_name": _display_name(name),
                "amount": _amount_as_number(value),
                "key": name,
                "definition_id": name,
            })
        return result
    return []


class BuildAndRepairDevice(BaseDevice):
    """Build and Repair (Nanobot) system device."""

    device_type = "nanobot_build_and_repair"

    def __init__(self, grid, metadata) -> None:
        super().__init__(grid, metadata)


    # ------------------------------------------------------------------
    # Telemetry/status helpers
    # ------------------------------------------------------------------
    def request_full_telemetry(self, wait: float = 2.0) -> dict[str, Any]:
        """Ask the plugin to publish full BaR telemetry and return the latest snapshot."""
        self.send_command({"cmd": "request_full_telemetry", "payload": {}})
        self.wait_for_telemetry(timeout=wait, wait_for_new=True, need_update=True)
        return dict(self.telemetry or {})

    def status_snapshot(self, wait: float = 2.0) -> dict[str, Any]:
        """Return current BuildAndRepair status, including DetailedInfo/missing items when available."""
        return self.request_full_telemetry(wait=wait)

    def missing_components(self, wait: float = 2.0) -> dict[str, Any]:
        """Return missing build/repair components reported by the mod."""
        data = self.status_snapshot(wait=wait)
        missing = data.get("missingComponents") or data.get("missingItems") or {}
        return dict(missing) if isinstance(missing, dict) else {}

    def missing_items_list(self, wait: float = 2.0) -> list[dict[str, Any]]:
        """Return normalized missing items as {name, display_name, amount, key}."""
        data = self.status_snapshot(wait=wait)
        return normalize_missing_items(data)

    def missing_report(self, wait: float = 2.0) -> dict[str, Any]:
        """Return a compact report with missing items and diagnostics."""
        data = self.status_snapshot(wait=wait)
        items = normalize_missing_items(data)
        return {
            "device_id": self.device_id,
            "name": self.name,
            "enabled": data.get("enabled"),
            "is_functional": data.get("isFunctional"),
            "is_working": data.get("isWorking"),
            "has_missing": bool(items) or bool(data.get("hasMissingItems")),
            "source": data.get("missingComponentsSource"),
            "items": items,
            "diagnostics": data.get("missingComponentsDiagnostics") or [],
            "projectors_checked": data.get("nanobotProjectorsChecked") or [],
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Generic property and action methods
    # ------------------------------------------------------------------
    def set_property(self, property_name: str, value: Any) -> int:
        """Set a BuildAndRepair property."""
        return self.send_command({
            "cmd": "set",
            "payload": {
                "property": f"BuildAndRepair.{property_name}",
                "value": value
            }
        })

    def run_action(self, action_id: str) -> int:
        """Run a BuildAndRepair action."""
        return self.send_command({
            "command": action_id,
            "payload": {}
        })

    # ------------------------------------------------------------------
    # Script control
    # ------------------------------------------------------------------
    def set_script_controlled(self, enabled: bool) -> int:
        """Enable or disable script control."""
        return self.set_property("ScriptControlled", enabled)

    def toggle_script_controlled(self) -> int:
        """Toggle script control."""
        return self.run_action("ScriptControlled_OnOff")

    # ------------------------------------------------------------------
    # Operation modes
    # ------------------------------------------------------------------
    def set_mode(self, mode: int) -> int:
        """Set operation mode (0=idle, 1=weld, 2=grind, etc.)."""
        return self.set_property("Mode", mode)

    def set_work_mode(self, work_mode: int) -> int:
        """Set work mode (0=off, 1=work, etc.)."""
        return self.set_property("WorkMode", work_mode)

    # ------------------------------------------------------------------
    # Color settings
    # ------------------------------------------------------------------
    def set_ignore_color(self, r: int, g: int, b: int) -> int:
        """Set ignore color (RGB)."""
        return self.send_command({
            "cmd": "set",
            "payload": {
                "property": "BuildAndRepair.IgnoreColor",
                "color": [r, g, b]
            }
        })

    def set_grind_color(self, r: int, g: int, b: int) -> int:
        """Set grind color (RGB)."""
        return self.send_command({
            "cmd": "set",
            "payload": {
                "property": "BuildAndRepair.GrindColor",
                "color": [r, g, b]
            }
        })

    def set_use_ignore_color(self, enabled: bool) -> int:
        """Enable or disable ignore color usage."""
        return self.set_property("UseIgnoreColor", enabled)

    def toggle_use_ignore_color(self) -> int:
        """Toggle ignore color usage."""
        return self.run_action("UseIgnoreColor_OnOff")

    def set_use_grind_color(self, enabled: bool) -> int:
        """Enable or disable grind color usage."""
        return self.set_property("UseGrindColor", enabled)

    def toggle_use_grind_color(self) -> int:
        """Toggle grind color usage."""
        return self.run_action("UseGrindColor_OnOff")

    # ------------------------------------------------------------------
    # Build settings
    # ------------------------------------------------------------------
    def set_allow_build(self, enabled: bool) -> int:
        """Enable or disable building."""
        return self.set_property("AllowBuild", enabled)

    def toggle_allow_build(self) -> int:
        """Toggle building."""
        return self.run_action("AllowBuild_OnOff")

    def set_weld_functional_only(self, enabled: bool) -> int:
        """Enable or disable welding functional blocks only."""
        return self.set_property("WeldOptionFunctionalOnly", enabled)

    def toggle_weld_functional_only(self) -> int:
        """Toggle welding functional blocks only."""
        return self.run_action("WeldOptionFunctionalOnly_OnOff")

    # ------------------------------------------------------------------
    # Grind settings
    # ------------------------------------------------------------------
    def set_grind_near_first(self, enabled: bool) -> int:
        """Enable or disable grinding nearest first."""
        return self.set_property("GrindNearFirst", enabled)

    def toggle_grind_near_first(self) -> int:
        """Toggle grinding nearest first."""
        return self.run_action("GrindNearFirst_OnOff")

    def set_grind_far_first(self, enabled: bool) -> int:
        """Enable or disable grinding farthest first."""
        return self.set_property("GrindFarFirst", enabled)

    def toggle_grind_far_first(self) -> int:
        """Toggle grinding farthest first."""
        return self.run_action("GrindFarFirst_OnOff")

    def set_grind_smallest_grid_first(self, enabled: bool) -> int:
        """Enable or disable grinding smallest grid first."""
        return self.set_property("GrindSmallestGridFirst", enabled)

    def toggle_grind_smallest_grid_first(self) -> int:
        """Toggle grinding smallest grid first."""
        return self.run_action("GrindSmallestGridFirst_OnOff")

    # ------------------------------------------------------------------
    # Janitor settings
    # ------------------------------------------------------------------
    def set_grind_janitor_enemies(self, enabled: bool) -> int:
        """Enable or disable grinding enemy ships."""
        return self.set_property("GrindJanitorEnemies", enabled)

    def toggle_grind_janitor_enemies(self) -> int:
        """Toggle grinding enemy ships."""
        return self.run_action("GrindJanitorEnemies_OnOff")

    def set_grind_janitor_not_owned(self, enabled: bool) -> int:
        """Enable or disable grinding not owned ships."""
        return self.set_property("GrindJanitorNotOwned", enabled)

    def toggle_grind_janitor_not_owned(self) -> int:
        """Toggle grinding not owned ships."""
        return self.run_action("GrindJanitorNotOwned_OnOff")

    def set_grind_janitor_neutrals(self, enabled: bool) -> int:
        """Enable or disable grinding neutral ships."""
        return self.set_property("GrindJanitorNeutrals", enabled)

    def toggle_grind_janitor_neutrals(self) -> int:
        """Toggle grinding neutral ships."""
        return self.run_action("GrindJanitorNeutrals_OnOff")

    def set_grind_janitor_disable_only(self, enabled: bool) -> int:
        """Enable or disable grinding disable only."""
        return self.set_property("GrindJanitorOptionDisableOnly", enabled)

    def toggle_grind_janitor_disable_only(self) -> int:
        """Toggle grinding disable only."""
        return self.run_action("GrindJanitorOptionDisableOnly_OnOff")

    def set_grind_janitor_hack_only(self, enabled: bool) -> int:
        """Enable or disable grinding hack only."""
        return self.set_property("GrindJanitorOptionHackOnly", enabled)

    def toggle_grind_janitor_hack_only(self) -> int:
        """Toggle grinding hack only."""
        return self.run_action("GrindJanitorOptionHackOnly_OnOff")

    # ------------------------------------------------------------------
    # Collection and push settings
    # ------------------------------------------------------------------
    def set_collect_if_idle(self, enabled: bool) -> int:
        """Enable or disable collecting if idle."""
        return self.set_property("CollectIfIdle", enabled)

    def toggle_collect_if_idle(self) -> int:
        """Toggle collecting if idle."""
        return self.run_action("CollectIfIdle_OnOff")

    def set_push_ingot_ore_immediately(self, enabled: bool) -> int:
        """Enable or disable pushing ingot/ore immediately."""
        return self.set_property("PushIngotOreImmediately", enabled)

    def toggle_push_ingot_ore_immediately(self) -> int:
        """Toggle pushing ingot/ore immediately."""
        return self.run_action("PushIngotOreImmediately_OnOff")

    def set_push_items_immediately(self, enabled: bool) -> int:
        """Enable or disable pushing items immediately."""
        return self.set_property("PushItemsImmediately", enabled)

    def toggle_push_items_immediately(self) -> int:
        """Toggle pushing items immediately."""
        return self.run_action("PushItemsImmediately_OnOff")

    def set_push_components_immediately(self, enabled: bool) -> int:
        """Enable or disable pushing components immediately."""
        return self.set_property("PushComponentImmediately", enabled)

    def toggle_push_components_immediately(self) -> int:
        """Toggle pushing components immediately."""
        return self.run_action("PushComponentImmediately_OnOff")

    # ------------------------------------------------------------------
    # Area settings
    # ------------------------------------------------------------------
    def set_area_offset(self, left_right: int, up_down: int, front_back: int) -> int:
        """Set area offset (left/right, up/down, front/back)."""
        commands = []
        if left_right != 0:
            commands.append(self.set_property("AreaOffsetLeftRight", left_right))
        if up_down != 0:
            commands.append(self.set_property("AreaOffsetUpDown", up_down))
        if front_back != 0:
            commands.append(self.set_property("AreaOffsetFrontBack", front_back))
        return sum(commands) if commands else 0

    def set_area_size(self, width: int, height: int, depth: int) -> int:
        """Set area size (width, height, depth)."""
        commands = []
        if width > 0:
            commands.append(self.set_property("AreaWidth", width))
        if height > 0:
            commands.append(self.set_property("AreaHeight", height))
        if depth > 0:
            commands.append(self.set_property("AreaDepth", depth))
        return sum(commands) if commands else 0

    def set_show_area(self, enabled: bool) -> int:
        """Show or hide work area."""
        return self.set_property("ShowArea", enabled)

    def toggle_show_area(self) -> int:
        """Toggle showing work area."""
        return self.run_action("ShowArea_OnOff")

    # ------------------------------------------------------------------
    # Sound settings
    # ------------------------------------------------------------------
    def set_sound_volume(self, volume: int) -> int:
        """Set sound volume (0-100)."""
        return self.set_property("SoundVolume", max(0, min(100, volume)))

    # ------------------------------------------------------------------
    # Quick actions
    # ------------------------------------------------------------------
    def enable_script_control(self) -> int:
        """Enable script control."""
        return self.run_action("ScriptControlled_On")

    def disable_script_control(self) -> int:
        """Disable script control."""
        return self.run_action("ScriptControlled_Off")

    def set_walk_mode(self) -> int:
        """Set walk mode."""
        return self.run_action("Grids_On")

    def set_fly_mode(self) -> int:
        """Set fly mode."""
        return self.run_action("BoundingBox_On")

    def set_weld_before_grind(self) -> int:
        """Set weld before grind."""
        return self.run_action("WeldBeforeGrind_On")

    def set_grind_before_weld(self) -> int:
        """Set grind before weld."""
        return self.run_action("GrindBeforeWeld_On")

    def set_grind_if_weld_stuck(self) -> int:
        """Set grind if weld stuck."""
        return self.run_action("GrindIfWeldGetStuck_On")

    def set_weld_only(self) -> int:
        """Set welding only."""
        return self.run_action("WeldOnly_On")

    def set_grind_only(self) -> int:
        """Set grinding only."""
        return self.run_action("GrindOnly_On")


DEVICE_TYPE_MAP[BuildAndRepairDevice.device_type] = BuildAndRepairDevice
