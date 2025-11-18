"""Projector device implementation for Space Engineers grid control."""

from __future__ import annotations

from typing import Any, Dict, Optional

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class ProjectorDevice(BaseDevice):
    """High level helper around the projector telemetry interface."""

    device_type = "projector"

    def handle_telemetry(self, telemetry: Dict[str, Any]) -> None:  # noqa: D401 - simple assignment
        """Store the latest telemetry snapshot."""
        self.telemetry = telemetry

    # ------------------------------------------------------------------
    # Convenience wrappers around the command payloads exposed by the
    # dedicated plugin.
    # ------------------------------------------------------------------
    def set_enabled(self, enabled: bool) -> int:
        return self.send_command({
            "cmd": "set_state",
            "state": {"enabled": bool(enabled)},
        })

    def set_flags(
        self,
        *,
        keep_projection: Optional[bool] = None,
        show_only_buildable: Optional[bool] = None,
        instant_build: Optional[bool] = None,
        align_grids: Optional[bool] = None,
        lock_projection: Optional[bool] = None,
        use_adaptive_offsets: Optional[bool] = None,
        use_adaptive_rotation: Optional[bool] = None,
    ) -> int:
        state: Dict[str, Any] = {}
        if keep_projection is not None:
            state["keepProjection"] = bool(keep_projection)
        if show_only_buildable is not None:
            state["showOnlyBuildable"] = bool(show_only_buildable)
        if instant_build is not None:
            state["instantBuild"] = bool(instant_build)
        if align_grids is not None:
            state["alignGrids"] = bool(align_grids)
        if lock_projection is not None:
            state["projectionLocked"] = bool(lock_projection)
        if use_adaptive_offsets is not None:
            state["useAdaptiveOffsets"] = bool(use_adaptive_offsets)
        if use_adaptive_rotation is not None:
            state["useAdaptiveRotation"] = bool(use_adaptive_rotation)

        if not state:
            raise ValueError("at least one flag must be provided")

        return self.send_command({
            "cmd": "projector_state",
            "state": state,
        })

    def set_scale(self, scale: float) -> int:
        return self.send_command({
            "cmd": "set_scale",
            "state": {"scale": float(scale)},
        })

    def set_offset(self, x: int, y: int, z: int) -> int:
        return self.send_command({
            "cmd": "set_offset",
            "state": {"x": int(x), "y": int(y), "z": int(z)},
        })

    def move_offset(self, dx: int = 0, dy: int = 0, dz: int = 0) -> int:
        return self.send_command({
            "cmd": "nudge_offset",
            "state": {"x": int(dx), "y": int(dy), "z": int(dz)},
        })

    def set_rotation(self, x: int, y: int, z: int) -> int:
        return self.send_command({
            "cmd": "set_rotation",
            "state": {"x": int(x), "y": int(y), "z": int(z)},
        })

    def rotate(self, dx: int = 0, dy: int = 0, dz: int = 0) -> int:
        return self.send_command({
            "cmd": "nudge_rotation",
            "state": {"x": int(dx), "y": int(dy), "z": int(dz)},
        })

    def position_projection_after_display(self) -> None:
        """Опустить проекцию на один блок вниз и повернуть на 45 градусов влево после отображения."""
        # Сначала опускаем вниз (dy=-1)
        self.move_offset(dy=1)
        # Затем поворачиваем влево (dy=-45, предполагая положительное Y = поворот вправо)
        self.rotate(dy=45)

    def reset_projection(self) -> int:
        return self.send_command({"cmd": "reset_projection"})

    def clear_projection(self) -> int:
        return self.send_command({"cmd": "clear_projection"})

    def lock_projection(self) -> int:
        return self.send_command({"cmd": "lock_projection"})

    def unlock_projection(self) -> int:
        return self.send_command({"cmd": "unlock_projection"})

    # ------------------------------------------------------------------
    # Helper accessors
    # ------------------------------------------------------------------
    def remaining_blocks(self) -> Optional[int]:
        return self._get_int("remainingBlocks")

    def buildable_blocks(self) -> Optional[int]:
        return self._get_int("buildableBlocks")

    def projected_grid_name(self) -> Optional[str]:
        return self._get_str("projectedGridName")

    def _get_int(self, key: str) -> Optional[int]:
        if not self.telemetry:
            return None
        value = self.telemetry.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_str(self, key: str) -> Optional[str]:
        if not self.telemetry:
            return None
        value = self.telemetry.get(key)
        if value is None:
            return None
        return str(value)

    def load_prefab(self, prefab_id: str, *, keep: bool = True) -> int:
        """Загрузить префаб (PrefabDefinition) в проектор.
        :param prefab_id: например 'LargeGrid/StarterMiner'
        :param keep: не сбрасывать текущую проекцию при обновлении
        :return: sequence id отправленной команды
        """
        if not prefab_id or not prefab_id.strip():
            raise ValueError("prefab_id must be a non-empty string")
        return self.send_command({
            "cmd": "load_prefab",
            "prefab": prefab_id.strip(),
            "keep": bool(keep),
        })

    def load_blueprint_xml(self, xml: str, *, keep: bool = False) -> int:
        """Загрузить блюпринт из XML (текст *.sbc ShipBlueprintDefinition).
        :param xml: полный XML текста
        :param keep: не сбрасывать текущую проекцию при обновлении
        :return: sequence id отправленной команды
        """
        if not xml or "<MyObjectBuilder_ShipBlueprintDefinition" not in xml:
            raise ValueError("xml must contain a ShipBlueprintDefinition")
        return self.send_command({
            "cmd": "load_blueprint_xml",
            "xml": xml,
            "keep": bool(keep),
        })


    # ------------------------------------------------------------------
    # Blueprint export helpers
    # ------------------------------------------------------------------
    def request_grid_blueprint(self, *, include_connected: bool = True) -> int:
        """Запросить выгрузку текущего грида в XML блюпринта.

        Команда инициирует сериализацию грида, на котором установлен проектор.
        Результат появляется в отдельном ключе Redis (см. :meth:`blueprint_key`).
        """

        return self.send_command({
            "cmd": "export_grid_blueprint",
            "state": {"includeConnected": bool(include_connected)},
        })

    def blueprint_key(self) -> str:
        """Return the Redis key that stores the last exported blueprint snapshot."""

        prefix, sep, _ = self.telemetry_key.rpartition(":")
        if not sep:
            return f"{self.telemetry_key}:blueprint"
        return f"{prefix}:blueprint"

    def blueprint_snapshot(self) -> Optional[Dict[str, Any]]:
        """Fetch the most recent blueprint snapshot JSON, if available."""

        payload = self.redis.get_json(self.blueprint_key())
        if isinstance(payload, dict):
            return payload
        return None

    def blueprint_xml(self) -> Optional[str]:
        """Return the XML payload of the last exported blueprint, if present."""

        snapshot = self.blueprint_snapshot()
        if not snapshot:
            return None
        xml = snapshot.get("xml")
        if xml is None:
            return None
        return str(xml)


DEVICE_TYPE_MAP[ProjectorDevice.device_type] = ProjectorDevice
