"""Nanobot Drill System (Drill & Fill) device helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Dict, List, Optional, Tuple

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class NanobotDrillHashResolver:
    """Сопоставление хешей руд (Voxel Materials) и их названий,
    используемых в Nanobot Drill and Fill System (FNV-1a 32-bit hashes).
    """

    # Сопоставление: Имя руды (в нижнем регистре) -> ХЕШ
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
        """Возвращает хеш для заданного имени руды. Имя нечувствительно к регистру."""
        if not ore_name:
            return None
        return cls.ORE_HASHES.get(ore_name.lower())

    @classmethod
    def resolve_name(cls, ore_hash: int) -> Optional[str]:
        """Возвращает имя руды для заданного хеша."""
        for name, hash_value in cls.ORE_HASHES.items():
            if hash_value == ore_hash:
                return name
        return None


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
        """Список текущих отфильтрованных руд (если плагин/мод отдаёт это поле)."""
        telemetry = self.telemetry or {}
        for key in ("oreFilters", "oreFilter", "OreFilter"):
            values = self._normalize_string_list(telemetry.get(key))
            if values:
                return values
        return []

    def known_ore_targets(self) -> List[str]:
        """Известные цели бурения (если мод их отдаёт)."""
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
        return self.send_command(
            {
                "cmd": "set",
                "payload": {
                    "property": qualified_name,
                    "value": value,
                },
            }
        )

    def run_action(self, action_id: str) -> int:
        """Запустить терминальное действие Nanobot Drill System."""

        action_id = str(action_id).strip()
        if not action_id:
            raise ValueError("action_id must not be empty")

        return self.send_command(
            {
                "cmd": action_id,
                "command": action_id,
                "payload": {
                    "action": action_id,
                    "command": action_id,
                },
            }
        )

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
        return self.run_action(
            "TerrainClearingMode_On" if enabled else "TerrainClearingMode_Off"
        )

    # ---------- НОВАЯ ЛОГИКА ФИЛЬТРОВ ПО РУДЕ ----------

    def _get_drill_priority_list(self) -> List[str]:
        """Получить текущий список приоритетов бурения/сбора в формате 'ХЕШ;True/False'."""
        telemetry = self.telemetry or {}

        raw_list: Any = None

        # Сначала пытаемся взять из properties
        props = telemetry.get("properties")
        if isinstance(props, dict):
            raw_list = props.get("Drill.DrillPriorityList")

        # Если не нашли — берём из корня по нормализованному ключу
        if raw_list is None:
            raw_list = telemetry.get("Drill.DrillPriorityList") or telemetry.get(
                "drill_drillprioritylist"
            )

        if isinstance(raw_list, list):
            return self._normalize_string_list(raw_list)
        return []

    @staticmethod
    def _parse_priority_entry(entry: str) -> Optional[Tuple[int, bool]]:
        """Разобрать строку вида '1137917536;True' -> (1137917536, True)."""
        if not entry:
            return None
        parts = str(entry).split(";")
        if not parts:
            return None
        try:
            ore_hash = int(parts[0])
        except ValueError:
            return None

        enabled = True
        if len(parts) >= 2:
            flag = parts[1].strip().lower()
            if flag in ("false", "0", "no", "off"):
                enabled = False
            elif flag in ("true", "1", "yes", "on"):
                enabled = True
        return ore_hash, enabled

    @staticmethod
    def _format_priority_entry(ore_hash: int, enabled: bool) -> str:
        """Сформировать строку 'ХЕШ;True/False'."""
        return f"{int(ore_hash)};{bool(enabled)}"

    def _get_drill_priority_map(self) -> Tuple[List[int], Dict[int, bool]]:
        """Построить карту приоритетов: порядок хешей + текущее состояние (по телеметрии)."""
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

    def _compute_slot_indices_for_ore_names(
        self, ore_names: Iterable[str]
    ) -> List[int]:
        """По списку имён руд вычислить индексы слотов в Drill.DrillPriorityList."""
        names = self._normalize_string_list(list(ore_names))
        if not names:
            return []

        # Множество хешей нужных руд
        target_hashes: set[int] = set()
        unknown: List[str] = []
        for name in {n.lower() for n in names}:
            ore_hash = NanobotDrillHashResolver.resolve_hash(name)
            if ore_hash is None:
                unknown.append(name)
            else:
                target_hashes.add(ore_hash)

        if unknown:
            raise ValueError(
                "Unknown ore names in filter: " + ", ".join(sorted(unknown))
            )

        entries = self._get_drill_priority_list()
        indices: List[int] = []

        for idx, entry in enumerate(entries):
            parsed = self._parse_priority_entry(entry)
            if parsed is None:
                continue
            ore_hash, _enabled = parsed
            if ore_hash in target_hashes:
                indices.append(idx)

        return indices

    def _send_orefilter_indices(self, indices: Iterable[int]) -> int:
        """Отправить в плагин спец-команду OreFilter с индексами слотов.

        Это уходит в NanobotDrillAndFillDevice.ApplyOreFilterFromPayload,
        который вызывает Drill.SetDrillEnabled(index, enabled).
        """
        idx_list = [int(i) for i in indices]
        if not idx_list:
            # Специальный случай: выключить всё
            # Плагин интерпретирует 'none' / 'off' как selectNone=True.
            return self.send_command(
                {
                    "cmd": "set",
                    "payload": {
                        "property": "OreFilter",
                        "value": ["none"],
                    },
                }
            )

        return self.send_command(
            {
                "cmd": "set",
                "payload": {
                    "property": "OreFilter",
                    "value": idx_list,
                },
            }
        )

    def set_ore_filters(self, ore_subtypes: Iterable[str]) -> int:
        """Установить фильтры по рудам по их ИМЕНАМ через спец-команду OreFilter.

        Пример:
            set_ore_filters(["Uranium"])         -> только уран
            set_ore_filters(["Uranium", "Iron"]) -> уран + железо
            set_ore_filters([])                  -> выключить все слоты
        """
        names = self._normalize_string_list(list(ore_subtypes))
        if not names:
            # Пустой список — отключаем всё.
            return self._send_orefilter_indices([])

        indices = self._compute_slot_indices_for_ore_names(names)
        return self._send_orefilter_indices(indices)

    def set_ore_filter(self, ore_subtype: str) -> int:
        """Сокращённый вариант: оставить включённой только одну руду."""
        ore = str(ore_subtype).strip()
        if not ore:
            raise ValueError("ore_subtype must not be empty")
        return self.set_ore_filters([ore])

    def clear_ore_filters(self) -> int:
        """Отключить все руды."""
        return self._send_orefilter_indices([])

    def set_ore_collection_priority(self, ore_name: str, collect: bool = True) -> int:
        """Установить флаг collect для одной руды по имени.

        Реализовано через перезапись всего фильтра:
        - читаем текущее состояние (по DrillPriorityList, если мод его обновляет);
        - добавляем/убираем одну руду;
        - вызываем set_ore_filters().

        Если мод НЕ обновляет DrillPriorityList при изменении фильтра скриптом,
        этот метод сохраняет корректность только относительно UI-состояния.
        """
        ore_name = str(ore_name).strip()
        if not ore_name:
            raise ValueError("ore_name must not be empty")

        ore_hash = NanobotDrillHashResolver.resolve_hash(ore_name)
        if ore_hash is None:
            raise ValueError(f"Unknown ore name '{ore_name}'. Cannot resolve hash.")

        # Читаем текущее состояние из DrillPriorityList
        _order, state = self._get_drill_priority_map()

        enabled_hashes: set[int] = {
            h for h, enabled in state.items() if enabled
        }

        if collect:
            enabled_hashes.add(ore_hash)
        else:
            enabled_hashes.discard(ore_hash)

        enabled_names: List[str] = []
        for h in enabled_hashes:
            name = NanobotDrillHashResolver.resolve_name(h)
            if name is not None:
                enabled_names.append(name)

        # Перезаписываем фильтр
        return self.set_ore_filters(enabled_names)

    # ---------------------------------------------------
    # Остальные high-level методы
    # ---------------------------------------------------
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
        return self.run_action(
            "RemoteControlShowArea_On" if enabled else "RemoteControlShowArea_Off"
        )

    def set_remote_control_work_disabled(self, enabled: bool) -> int:
        return self.run_action(
            "RemoteControlWorkdisabled_On"
            if enabled
            else "RemoteControlWorkdisabled_Off"
        )

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

    # ---------- Отладочные методы для твоего скрипта ----------

    # ---------- DEBUG-ХЕЛПЕРЫ ДЛЯ ПРОВЕРКИ ФИЛЬТРОВ ----------

    def debug_get_priority_list_raw(self) -> List[str]:
        """Сырой список Drill.DrillPriorityList из последней телеметрии."""
        return list(self._get_drill_priority_list())

    def debug_get_enabled_known_ores(self) -> Dict[str, bool]:
        """
        Карта {имя_руды: включена_ли} на основе:
        - oreFilterIndices из плагина, если есть;
        - иначе — флага True/False внутри Drill.DrillPriorityList.
        """
        result: Dict[str, bool] = {}

        entries = self._get_drill_priority_list()
        if not entries:
            return result

        # 1) Пробуем использовать oreFilterIndices от плагина
        telemetry = self.telemetry or {}
        indices = telemetry.get("oreFilterIndices")

        if isinstance(indices, list) and indices:
            enabled_indices = {int(i) for i in indices}

            for idx, entry in enumerate(entries):
                parsed = self._parse_priority_entry(entry)
                if parsed is None:
                    continue
                ore_hash, _ = parsed
                name = NanobotDrillHashResolver.resolve_name(ore_hash)
                if not name:
                    continue
                # считаем включённой, если индекс есть в oreFilterIndices
                result[name] = idx in enabled_indices

            return result

        # 2) Фоллбек: разбираем True/False внутри самой строки
        for entry in entries:
            parsed = self._parse_priority_entry(entry)
            if parsed is None:
                continue
            ore_hash, enabled = parsed
            name = NanobotDrillHashResolver.resolve_name(ore_hash)
            if not name:
                continue
            result[name] = enabled

        return result

    # В NanobotDrillSystemDevice добавь эти методы:

    def set_work_mode(self, mode: str) -> int:
        """
        Установить WorkMode Nanobot Drill & Fill.

        По фактической телеметрии:
          0 = Fill
          1 = Collect
          2 = Drill
        """
        # mode_map = {"drill": 2, "collect": 1, "fill": 0}
        mode_map = {"drill": 1, "collect": 2, "fill": 0}
        mode_lower = mode.lower().strip()
        if mode_lower not in mode_map:
            raise ValueError(f"Invalid mode '{mode}'. Use: drill, collect, fill")

        mode_value = mode_map[mode_lower]

        # Реальный property-id: "Drill.WorkMode"
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
        """Получить текущий WorkMode из телеметрии Nanobot Drill & Fill."""
        telemetry = self.telemetry or {}
        props = telemetry.get("properties", {})

        mode_raw = props.get("Drill.WorkMode")
        if mode_raw is None:
            mode_raw = telemetry.get("drill_workmode")

        if mode_raw is None:
            return None

        # 0 = Fill, 1 = Collect, 2 = Drill
        mode_map = {0: "Fill", 1: "Collect", 2: "Drill"}

        if isinstance(mode_raw, int):
            return mode_map.get(mode_raw, str(mode_raw))

        try:
            num = int(str(mode_raw))
            return mode_map.get(num, str(mode_raw))
        except (TypeError, ValueError):
            return str(mode_raw)

    # После всех настроек — используй ПРАВИЛЬНЫЙ фильтр для Collect-режима!
    # Это НЕ OreFilter, а отдельная команда!

    def set_collect_filter(self, ores: list):
        """Устанавливает Collect-фильтр (работает при ScriptControlled = true)"""
        # Сначала выключаем всё
        for i in range(11):
            self.send_command({
                "cmd": "set",
                "payload": {
                    "property": "Drill.SetCollectEnabled",
                    "value": [i, False]
                }
            })

        # Включаем нужные руды
        ore_indices = {
            "Stone": 0, "Ice": 1, "Iron": 2, "Nickel": 3, "Silicon": 4,
            "Cobalt": 5, "Magnesium": 6, "Silver": 7, "Gold": 8,
            "Platinum": 9, "Uranium": 10
        }

        for ore in ores:
            idx = ore_indices.get(ore)
            if idx is not None:
                self.send_command({
                    "cmd": "set",
                    "payload": {
                        "property": "Drill.SetCollectEnabled",
                        "value": [idx, True]
                    }
                })



DEVICE_TYPE_MAP[NanobotDrillSystemDevice.device_type] = NanobotDrillSystemDevice
