"""Base device functionality for Space Engineers grid control.

This module contains the base device class and grid management functionality
that all specific devices build upon.
"""

from __future__ import annotations

import colorsys
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Sequence, Type

# DEVICE_TYPE_MAP пополняется модулями устройств и внешними плагинами при импорте
DEVICE_TYPE_MAP = {}

def get_device_class(device_type: str):
    """Возвращает класс устройства по его типу."""
    return DEVICE_TYPE_MAP.get(device_type, BaseDevice)

DEVICE_REGISTRY = {
    "MyObjectBuilder_Projector": "projector",  # будет разрешено через DEVICE_TYPE_MAP
    "MyObjectBuilder_BatteryBlock": "battery",  # будет разрешено через DEVICE_TYPE_MAP
    "MyObjectBuilder_SmallGatlingGun": "weapon",
    "MyObjectBuilder_SmallMissileLauncher": "weapon",
    "MyObjectBuilder_SmallMissileLauncherReload": "weapon",
    "MyObjectBuilder_LargeGatlingGun": "weapon",
    "MyObjectBuilder_LargeMissileLauncher": "weapon",
    "MyObjectBuilder_InteriorTurret": "interior_turret",
    "weapon": "weapon",
    "interior_turret": "interior_turret",
    # дополняй по мере надобности
}


def _safe_int(value: Any) -> Optional[int]:
    """Преобразует значение к ``int`` или возвращает ``None``."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_unit(value: float) -> float:
    value = float(value)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _normalize_unit(value: float) -> float:
    value = float(value)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        if value <= 100.0:
            return _clamp_unit(value / 100.0)
        return _clamp_unit(value / 255.0)
    return value


def _normalize_hue(value: float) -> float:
    value = float(value)
    if value > 1.0 or value < 0.0:
        value %= 360.0
        if value < 0.0:
            value += 360.0
        return value / 360.0
    return _clamp_unit(value)


def _normalize_hsv_triplet(values: Sequence[Any]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("HSV value must contain exactly three components")
    h, s, v = (float(values[0]), float(values[1]), float(values[2]))
    return (
        _normalize_hue(h),
        _normalize_unit(s),
        _normalize_unit(v),
    )


def _normalize_rgb_triplet(values: Sequence[Any]) -> tuple[int, int, int]:
    if len(values) != 3:
        raise ValueError("RGB value must contain exactly three components")
    r, g, b = (float(values[0]), float(values[1]), float(values[2]))
    if max(abs(r), abs(g), abs(b)) <= 1.0:
        r *= 255.0
        g *= 255.0
        b *= 255.0
    return (
        max(0, min(255, int(round(r)))),
        max(0, min(255, int(round(g)))),
        max(0, min(255, int(round(b)))),
    )


def _parse_triplet_text(text: str) -> list[float]:
    parts = [p for p in re.split(r"[;,\s]+", text.strip()) if p]
    if len(parts) < 3:
        raise ValueError("Failed to parse color components from text")
    return [float(parts[0]), float(parts[1]), float(parts[2])]


def _parse_hex_color(text: str) -> tuple[int, int, int]:
    cleaned = text.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:]
    elif cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) not in (6, 8):
        raise ValueError("Hex color must be in RRGGBB or AARRGGBB format")
    cleaned = cleaned[-6:]
    r = int(cleaned[0:2], 16)
    g = int(cleaned[2:4], 16)
    b = int(cleaned[4:6], 16)
    return r, g, b


def _prepare_color_payload(
    *,
    color: Any = None,
    hsv: Sequence[Any] | None = None,
    rgb: Sequence[Any] | None = None,
    space: str | None = None,
) -> Dict[str, Any]:
    """Формирует полезную нагрузку с цветом для команды покраски."""

    if hsv is not None:
        h, s, v = _normalize_hsv_triplet(hsv)
        return {"hsv": {"h": h, "s": s, "v": v}}

    if rgb is not None:
        r, g, b = _normalize_rgb_triplet(rgb)
        return {"rgb": {"r": r, "g": g, "b": b}}

    if color is None:
        raise ValueError("Either hsv, rgb or color must be provided")

    if isinstance(color, str):
        color = color.strip()
        if not color:
            raise ValueError("color string must not be empty")
        if color.startswith("#") or color.lower().startswith("0x"):
            r, g, b = _parse_hex_color(color)
            return {"rgb": {"r": r, "g": g, "b": b}}
        values = _parse_triplet_text(color)
    elif isinstance(color, (list, tuple)):
        values = list(color)
    else:
        raise TypeError("color must be a string or a sequence of three numbers")

    if len(values) != 3:
        raise ValueError("color must contain exactly three components")

    normalized_space = (space or "").strip().lower()
    if normalized_space == "hsv":
        h, s, v = _normalize_hsv_triplet(values)
        return {"hsv": {"h": h, "s": s, "v": v}}

    if normalized_space == "rgb":
        r, g, b = _normalize_rgb_triplet(values)
        return {"rgb": {"r": r, "g": g, "b": b}}

    # Автоопределение: значения <= examples_direct_connect.0 трактуем как HSV, иначе как RGB.
    if max(abs(float(values[0])), abs(float(values[1])), abs(float(values[2]))) <= 1.0:
        h, s, v = _normalize_hsv_triplet(values)
        return {"hsv": {"h": h, "s": s, "v": v}}

    r, g, b = _normalize_rgb_triplet(values)
    return {"rgb": {"r": r, "g": g, "b": b}}
# Import from our own modules

@dataclass
class DeviceMetadata:
    """Representation of a device extracted from the grid info payload."""

    device_type: str
    device_id: str
    telemetry_key: str
    grid_id: str
    name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class Grid:
    """Representation of a Space Engineers grid."""

    def __init__(
        self,
        redis_client,
        owner_id: str,
        grid_id: str,
        player_id: str,
        name: str = None,
    ) -> None:
        self.redis = redis_client
        self.owner_id = owner_id
        self.grid_id = grid_id
        self.player_id = player_id
        self.name = name or f"Grid_{grid_id}"
        self.grid_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
        self.metadata: Optional[Dict[str, Any]] = None
        self.devices: Dict[str, BaseDevice] = {}
        # NEW: индекс по числовому id
        self.devices_by_num: Dict[int, BaseDevice] = {}

        self._subscription = self.redis.subscribe_to_key(
            self.grid_key, self._on_grid_change
        )
        initial = self.redis.get_json(self.grid_key)
        if initial is not None:
            self._on_grid_change(self.grid_key, initial, "initial")

    # ------------------------------------------------------------------
    def _on_grid_change(self, key: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            return
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return
        # При наличии имени грида в payload — обновим локальное имя
        try:
            new_name = (
                payload.get("name")
                or payload.get("gridName")
                or payload.get("displayName")
                or payload.get("DisplayName")
            )
            if isinstance(new_name, str) and new_name.strip():
                self.name = new_name
        except Exception:
            pass

        # Отладка: покажем, откуда берём устройства
        if "devices" not in payload:
            if isinstance(payload.get("comp"), dict) and "devices" in payload["comp"]:
                print("[gridinfo] устройства найдены в comp.devices")
            # else:
            #     print(
            #         f"[gridinfo] нет поля 'devices' ни в корне, ни в comp. Ключи: {list(payload.keys())}"
            #     )

        self.metadata = payload
        device_metadata = list(self._extract_devices(payload))

        # добавление/обновление
        for metadata in device_metadata:
            device = self.devices.get(metadata.device_id)
            if device is None:
                device = create_device(self, metadata)
                self.devices[metadata.device_id] = device
            else:
                device.update_metadata(metadata)

            # NEW: индексируем числовой ID (если конвертится)
            try:
                did_int = int(metadata.device_id)
            except Exception:
                # иногда device_id может быть нечисловой строкой — просто пропустим
                pass
            else:
                self.devices_by_num[did_int] = device

        # удаление исчезнувших
        existing_ids = {meta.device_id for meta in device_metadata}
        for device_id in list(self.devices):
            if device_id not in existing_ids:
                dev = self.devices.pop(device_id)
                # NEW: очистим числовой индекс, если был
                try:
                    self.devices_by_num.pop(int(device_id), None)
                except Exception:
                    pass
                dev.close()

        if "devices" not in payload:
            # print(f"[gridinfo] нет поля 'devices'. Ключи: {list(payload.keys())}")
            pass
        else:
            print(f"[gridinfo] devices type: {type(payload['devices'])}")
            # например, покажем первые examples_direct_connect-2 записи
            try:
                it = (
                    payload["devices"].values()
                    if isinstance(payload["devices"], dict)
                    else payload["devices"]
                )
                preview = []
                for i, d in enumerate(it):
                    if i >= 2:
                        break
                    preview.append(
                        {
                            k: d.get(k)
                            for k in (
                                "type",
                                "deviceType",
                                "subtype",
                                "deviceId",
                                "entityId",
                                "id",
                                "telemetryKey",
                                "key",
                                "name",
                                "customName",
                            )
                        }
                    )
                print("[gridinfo] devices preview:", preview)
            except Exception as e:
                print("[gridinfo] preview error:", e)

    # ------------------------------------------------------------------
    def get_device(self, device_id: str) -> Optional["BaseDevice"]:
        return self.devices.get(str(device_id))

    # NEW: поиск по числовому идентификатору
    def get_device_num(self, device_id: int) -> Optional["BaseDevice"]:
        """Вернёт устройство по числовому device/entity ID или None, если не найдено."""

        return self.devices_by_num.get(int(device_id))

    # NEW: универсальный помощник — принимает и str, и int
    def get_device_any(self, device_id: int | str) -> Optional["BaseDevice"]:
        """
        Если пришёл int — ищем через devices_by_num.
        Если str — сначала точное совпадение, затем пробуем int(device_id).
        """

        if isinstance(device_id, int):
            return self.devices_by_num.get(device_id)
        dev = self.devices.get(device_id)
        if dev:
            return dev
        try:
            return self.devices_by_num.get(int(device_id))
        except Exception:
            return None

    # NEW: поиск устройств по типу
    def find_devices_by_type(self, device_type: str) -> list["BaseDevice"]:
        """
        Возвращает список устройств указанного типа.

        Принимает как нормализованные типы (например, "battery", "projector"),
        так и исходные имена из Space Engineers (например, "MyObjectBuilder_BatteryBlock").
        Тип приводится к нормализованному виду через ``normalize_device_type``.
        """

        try:
            normalized = normalize_device_type(device_type)
        except Exception:
            normalized = str(device_type).lower()

        return [d for d in self.devices.values() if getattr(d, "device_type", "").lower() == normalized]

    # ------------------------------------------------------------------
    def _grid_command_channel(self) -> str:
        return f"se.{self.player_id}.commands.grid.{self.grid_id}"

    # ------------------------------------------------------------------
    def send_grid_command(
        self,
        command: str,
        *,
        state: Any | None = None,
        payload: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> int:
        """Публикует команду на уровень грида."""

        if not command:
            raise ValueError("command must be a non-empty string")

        message: Dict[str, Any] = {}
        if payload:
            for key, value in payload.items():
                if value is not None:
                    message[key] = value

        for key, value in extra.items():
            if value is not None and key not in message:
                message[key] = value

        if state is not None:
            message.setdefault("state", state)

        now_ms = int(time.time() * 1000)
        message.setdefault("cmd", command)
        message.setdefault("seq", now_ms)
        message.setdefault("ts", now_ms)
        message.setdefault("targetType", "grid")

        grid_int = _safe_int(self.grid_id)
        if grid_int is not None:
            message.setdefault("gridId", grid_int)
            message.setdefault("gridEntityId", grid_int)
            message.setdefault("grid_id", grid_int)
            message.setdefault("targetId", grid_int)
            message.setdefault("target_id", grid_int)

        owner_int = _safe_int(self.owner_id)
        if owner_int is not None:
            message.setdefault("ownerId", owner_int)
            message.setdefault("owner_id", owner_int)

        player_int = _safe_int(self.player_id)
        if player_int is not None:
            message.setdefault("playerId", player_int)
            message.setdefault("player_id", player_int)
            message.setdefault("userId", player_int)

        meta = message.get("meta")
        if isinstance(meta, dict):
            meta.setdefault("user", "grid-wrapper")
        else:
            message["meta"] = {"user": "grid-wrapper"}

        channel = self._grid_command_channel()
        return self.redis.publish(channel, message)

    # ------------------------------------------------------------------
    def rename(self, new_name: str) -> int:
        """Изменяет отображаемое имя грида."""

        if not new_name or not new_name.strip():
            raise ValueError("new_name must be a non-empty string")

        trimmed = new_name.strip()
        return self.send_grid_command(
            "set_name",
            state=trimmed,
            payload={"name": trimmed, "gridName": trimmed},
        )

    # ------------------------------------------------------------------
    def set_owner(
        self,
        owner_id: int | str,
        *,
        share_mode: Optional[str] = None,
        share_with_all: Optional[bool] = None,
        share_with_faction: Optional[bool] = None,
    ) -> int:
        """Передаёт владение гридом выбранному игроку."""

        owner_int = _safe_int(owner_id)
        if owner_int is None or owner_int <= 0:
            raise ValueError("owner_id must be a positive integer")

        payload: Dict[str, Any] = {"ownerId": owner_int}
        if share_mode is not None:
            payload["shareMode"] = str(share_mode).strip()
        if share_with_all is not None:
            payload["shareWithAll"] = bool(share_with_all)
        if share_with_faction is not None:
            payload["shareWithFaction"] = bool(share_with_faction)

        return self.send_grid_command("set_owner", payload=payload)

    # ------------------------------------------------------------------
    def convert_to_ship(self) -> int:
        """Переводит грид в режим корабля."""

        return self.send_grid_command("convert_to_ship")

    # ------------------------------------------------------------------
    def convert_to_station(self) -> int:
        """Переводит грид в режим станции."""

        return self.send_grid_command("convert_to_station")

    # ------------------------------------------------------------------
    def paint_block(
        self,
        block_id: int | str,
        *,
        color: Any = None,
        hsv: Sequence[Any] | None = None,
        rgb: Sequence[Any] | None = None,
        space: str | None = None,
        play_sound: bool | None = None,
    ) -> int:
        """Меняет цвет одного блока по его ``EntityId``."""

        block_int = _safe_int(block_id)
        if block_int is None or block_int <= 0:
            raise ValueError("block_id must be a positive integer")

        color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)

        payload: Dict[str, Any] = {"blockId": block_int}
        payload.update(color_payload)

        if play_sound is not None:
            payload["playSound"] = bool(play_sound)

        return self.send_grid_command("paint_block", payload=payload)

    # ------------------------------------------------------------------
    def create_gps_marker(
        self,
        name: str | None = None,
        *,
        gps: str | None = None,
        coordinates: Sequence[Any] | str | None = None,
        position: Sequence[Any] | str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        description: str | None = None,
        color: Any = None,
        rgb: Sequence[Any] | None = None,
        hsv: Sequence[Any] | None = None,
        space: str | None = None,
        show_on_hud: bool | None = None,
        show_on_terminal: bool | None = None,
        show_on_map: bool | None = None,
        temporary: bool | None = None,
        always_visible: bool | None = None,
        entity_id: int | str | None = None,
    ) -> int:
        """Создаёт GPS-метку для владельца грида.

        Если координаты не указаны, серверная часть использует текущую позицию
        грида. Можно передать готовую GPS-строку Space Engineers (`gps`),
        текстовые или числовые координаты (`coordinates`/`position`) либо три
        значения `x`, `y`, `z`.
        """

        payload: Dict[str, Any] = {}

        if name:
            payload["name"] = name.strip()
        if description:
            payload["description"] = description

        if gps:
            gps_text = gps.strip()
            if gps_text:
                payload["gps"] = gps_text

        def _normalize_vector(value: Sequence[Any] | str | None) -> Optional[tuple[float, float, float]]:
            if value is None:
                return None
            if isinstance(value, str):
                parts = [p for p in re.split(r"[;,\s]+", value.strip()) if p]
                if len(parts) < 3:
                    raise ValueError("coordinates string must contain three numbers")
                try:
                    vector = (float(parts[0]), float(parts[1]), float(parts[2]))
                except ValueError as exc:
                    raise ValueError("failed to parse coordinates from string") from exc
                return vector

            if isinstance(value, Sequence):
                if len(value) < 3:
                    raise ValueError("coordinate sequence must contain at least three values")
                try:
                    vector = (float(value[0]), float(value[1]), float(value[2]))
                except (TypeError, ValueError) as exc:
                    raise ValueError("failed to convert coordinates to float") from exc
                return vector

            raise TypeError("coordinates must be a string or a sequence of three numbers")

        vector = None
        for candidate in (coordinates, position):
            vector = _normalize_vector(candidate)
            if vector is not None:
                break

        if vector is None and any(v is not None for v in (x, y, z)):
            missing = [axis for axis, value in (("x", x), ("y", y), ("z", z)) if value is None]
            if missing:
                raise ValueError(f"coordinates require all three components (missing: {', '.join(missing)})")
            vector = (float(x), float(y), float(z))

        if vector is not None:
            payload["position"] = {"x": vector[0], "y": vector[1], "z": vector[2]}

        if show_on_hud is not None:
            payload["showOnHud"] = bool(show_on_hud)
        if show_on_terminal is not None:
            payload["showOnTerminal"] = bool(show_on_terminal)
        if show_on_map is not None:
            payload["showOnMap"] = bool(show_on_map)
        if temporary is not None:
            payload["temporary"] = bool(temporary)
        if always_visible is not None:
            payload["alwaysVisible"] = bool(always_visible)

        if entity_id is not None:
            entity_int = _safe_int(entity_id)
            if entity_int is None or entity_int <= 0:
                raise ValueError("entity_id must be a positive integer")
            payload["entityId"] = entity_int

        if color is not None or rgb is not None or hsv is not None:
            color_payload = _prepare_color_payload(color=color, hsv=hsv, rgb=rgb, space=space)
            if "hsv" in color_payload:
                hsv_values = color_payload["hsv"]
                h = float(hsv_values.get("h", 0.0))
                s = float(hsv_values.get("s", 0.0))
                v = float(hsv_values.get("v", 0.0))
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                color_payload = {
                    "rgb": {
                        "r": max(0, min(255, int(round(r * 255.0)))),
                        "g": max(0, min(255, int(round(g * 255.0)))),
                        "b": max(0, min(255, int(round(b * 255.0)))),
                    }
                }
            payload.update(color_payload)

        return self.send_grid_command("create_gps", payload=payload)

    # ------------------------------------------------------------------
    def list_gps_markers(
        self,
        *,
        show_on_hud: bool | None = None,
        show_on_map: bool | None = None,
        always_visible: bool | None = None,
        request_id: str | None = None,
    ) -> int:
        """Запрашивает у сервера список GPS-меток игрока."""

        payload: Dict[str, Any] = {}

        if show_on_hud is not None:
            payload["showOnHud"] = bool(show_on_hud)
        if show_on_map is not None:
            payload["showOnMap"] = bool(show_on_map)
        if always_visible is not None:
            payload["alwaysVisible"] = bool(always_visible)
        if request_id:
            payload["requestId"] = str(request_id)

        effective_payload = payload if payload else None
        return self.send_grid_command("list_gps", payload=effective_payload)

    # ------------------------------------------------------------------
    def _extract_devices(self, payload: Dict[str, Any]) -> Iterable[DeviceMetadata]:
        # собираем кандидатов из всех известных мест: payload['devices'] и payload['comp']['devices']
        candidates: list[Dict[str, Any]] = []

        # examples_direct_connect) корневой devices (если вдруг существует)
        root_devices = payload.get("devices")
        if isinstance(root_devices, dict):
            candidates.extend([d for d in root_devices.values() if isinstance(d, dict)])
        elif isinstance(root_devices, list):
            candidates.extend([d for d in root_devices if isinstance(d, dict)])

        # 2) devices под comp
        comp = payload.get("comp")
        if isinstance(comp, dict):
            comp_devices = comp.get("devices")
            if isinstance(comp_devices, dict):
                candidates.extend([d for d in comp_devices.values() if isinstance(d, dict)])
            elif isinstance(comp_devices, list):
                candidates.extend([d for d in comp_devices if isinstance(d, dict)])

        # Отладка: если кандидатов нет — покажем, что есть
        if not candidates:
            print(f"[gridinfo] devices не найдены. Корневые ключи: {list(payload.keys())}")
            if isinstance(comp, dict):
                print(f"[gridinfo] comp-ключи: {list(comp.keys())}")
            return []

        for entry in candidates:
            # из вашего JSON: поля называются id/type/subtype/name
            raw_type = (
                entry.get("type")
                or entry.get("deviceType")
                or entry.get("subtype")
                or "generic"
            )
            device_type = normalize_device_type(raw_type)

            # id может быть int — приводим к строке
            raw_id = (
                entry.get("deviceId")
                or entry.get("entityId")
                or entry.get("id")
                or ""
            )
            if raw_id in ("", None):
                continue
            device_id = str(raw_id)

            # telemetryKey в вашем примере нет — синтезируем по нашей схеме
            telemetry_key = entry.get("telemetryKey") or entry.get("key")
            if not telemetry_key:
                telemetry_key = self.build_device_key(device_type, device_id)

            custom_name = entry.get("customName") or entry.get("CustomName")
            display_name = (
                entry.get("displayName")
                or entry.get("displayNameText")
                or entry.get("DisplayName")
                or entry.get("DisplayNameText")
            )
            raw_name = entry.get("name") or entry.get("Name")
            name = custom_name or display_name or raw_name
            extra = {
                k: v
                for k, v in entry.items()
                if k
                not in {
                    "type",
                    "deviceType",
                    "subtype",
                    "deviceId",
                    "entityId",
                    "id",
                    "telemetryKey",
                    "key",
                }
            }
            if custom_name is not None:
                extra.setdefault("customName", custom_name)
            if raw_name is not None:
                extra.setdefault("name", raw_name)
            if display_name is not None:
                extra.setdefault("displayName", display_name)

            yield DeviceMetadata(
                device_type=device_type,
                device_id=device_id,
                telemetry_key=str(telemetry_key),
                grid_id=self.grid_id,
                name=name,
                extra=extra,
            )

    # ------------------------------------------------------------------
    def build_device_key(self, device_type: str, device_id: str) -> str:
        return f"se:{self.owner_id}:grid:{self.grid_id}:{device_type}:{device_id}:telemetry"

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._subscription.close()
        except Exception:
            pass
        for device in list(self.devices.values()):
            device.close()
        self.devices.clear()
        self.devices_by_num.clear()

    def get_device_by_id(self, device_id: int) -> BaseDevice | None:
        """Быстрый поиск устройства по числовому ID."""

        return self.devices_by_num.get(int(device_id))

    def refresh_devices(self) -> int:
        """
        Перечитывает gridinfo и обновляет self.devices.
        Возвращает число обнаруженных (актуализированных) устройств.
        """

        info_key = f"se:{self.owner_id}:grid:{self.grid_id}:gridinfo"
        payload = self.redis.get_json(info_key) or {}

        # Нормализуем секцию с устройствами:
        devices_section = None
        if isinstance(payload, dict):
            if "devices" in payload:
                devices_section = payload["devices"]
            elif isinstance(payload.get("comp"), dict) and "devices" in payload["comp"]:
                devices_section = payload["comp"]["devices"]

        if not devices_section:
            # Нет устройств в gridinfo — ничего не делаем
            return 0

        # Преобразуем devices_section к списку словарей устройств
        dev_items: list[dict] = []
        if isinstance(devices_section, list):
            dev_items = [d for d in devices_section if isinstance(d, dict)]
        elif isinstance(devices_section, dict):
            # варианты: { "Projector": [ {...}, ... ], "Battery": [ ... ] } ИЛИ { "8788": {...}, ... }
            if devices_section and all(
                isinstance(k, str) and k.isdigit() for k in devices_section.keys()
            ):
                dev_items = [v for v in devices_section.values() if isinstance(v, dict)]
            else:
                for v in devices_section.values():
                    if isinstance(v, list):
                        dev_items.extend([d for d in v if isinstance(d, dict)])
                    elif isinstance(v, dict):
                        dev_items.append(v)

        updated = 0
        for d in dev_items:
            try:
                dev_id = int(d.get("id"))
            except Exception:
                continue

            dev_type = d.get("type") or d.get("blockType") or ""
            dev_subtype = d.get("subtype") or d.get("subType") or ""
            dev_name = d.get("name") or f"{dev_type}:{dev_id}"

            device = self.devices_by_num.get(dev_id)
            if device is None:
                # Подбираем класс
                device_cls_or_name = DEVICE_REGISTRY.get(dev_type, None)
                if device_cls_or_name is None:
                    # Используем DEVICE_TYPE_MAP для разрешения по типу
                    cls = DEVICE_TYPE_MAP.get(normalize_device_type(dev_type), BaseDevice)
                else:
                    # Если в DEVICE_REGISTRY есть запись, проверим, является ли она строкой (именем типа)
                    if isinstance(device_cls_or_name, str):
                        cls = DEVICE_TYPE_MAP.get(device_cls_or_name, BaseDevice)
                    else:
                        # иначе это уже сам класс устройства
                        cls = device_cls_or_name

                # Конструктор BaseDevice/наследников может отличаться — приведи под свой
                # Создаем DeviceMetadata для передачи в конструктор
                telemetry_key = self.build_device_key(
                    normalize_device_type(dev_type), str(dev_id)
                )
                metadata = DeviceMetadata(
                    device_type=normalize_device_type(dev_type),
                    device_id=str(dev_id),
                    telemetry_key=telemetry_key,
                    grid_id=self.grid_id,
                    name=dev_name,
                    extra={
                        "type": dev_type,
                        "subtype": dev_subtype,
                    },
                )
                device = cls(
                    grid=self,
                    metadata=metadata,
                )
                self.devices[str(dev_id)] = device
                self.devices_by_num[dev_id] = device
            else:
                # Обновим имя/типы, если поменялись
                setattr(device, "name", dev_name)
                setattr(device, "type", dev_type)
                setattr(device, "subtype", dev_subtype)

            # Пробуем подтянуть снимок телеметрии
            self._refresh_device_telemetry(device, dev_type, dev_id)
            updated += 1

        return updated

    def _refresh_device_telemetry(
        self, device: BaseDevice, dev_type: str, dev_id: int
    ) -> None:
        """
        Заполняет последнюю известную телеметрию устройства, если ключ существует.
        Ключ: se:{owner}:grid:{grid}:{device_type}:{device_id}:telemetry
        """

        # dev_type в телеметрии обычно «чистый» (например, battery_block, projector и т.п.).
        # Если у тебя в Redis тип — уже нормализован, замапь тут при необходимости.
        type_key = self._normalize_type_for_telemetry(dev_type)
        tkey = f"se:{self.owner_id}:grid:{self.grid_id}:{type_key}:{dev_id}:telemetry"
        snap = self.redis.get_json(tkey)
        if isinstance(snap, dict):
            # под свою модель: device.telemetry / device.state / device.cache …
            setattr(device, "telemetry", snap)

    def _normalize_type_for_telemetry(self, dev_type: str) -> str:
        """
        Приведение типа к части ключа телеметрии.
        Например: 'MyObjectBuilder_BatteryBlock' -> 'battery_block'
        """

        if dev_type.startswith("MyObjectBuilder_"):
            dev_type = dev_type.removeprefix("MyObjectBuilder_")
        # Простейшая snake_case нормализация
        return "".join([("_" + c.lower() if c.isupper() else c) for c in dev_type]).lstrip("_")

class BaseDevice:
    """Base class for all telemetry driven devices."""

    device_type: str = "generic"

    def __init__(self, grid: Grid, metadata: DeviceMetadata) -> None:
        self.grid = grid
        self.redis = grid.redis
        self.device_id = metadata.device_id
        self.device_type = metadata.device_type
        self.telemetry_key = metadata.telemetry_key
        self.grid_id = metadata.grid_id
        self.name = (
            metadata.name
            or metadata.extra.get("customName")
            or metadata.extra.get("name")
            or metadata.extra.get("displayName")
            or metadata.extra.get("displayNameText")
        )
        self.metadata = metadata
        self.telemetry: Optional[Dict[str, Any]] = None
        self._enabled: bool = self._extract_optional_bool(
            metadata.extra,
            "enabled",
            "isEnabled",
            "isWorking",
            "isFunctional",
        ) or False
        self._show_in_terminal: bool = self._extract_optional_bool(metadata.extra, "showInTerminal") or False
        self._show_in_toolbar: bool = self._extract_optional_bool(metadata.extra, "showInToolbar") or False
        self._show_on_screen: bool = self._extract_optional_bool(metadata.extra, "showOnScreen") or False
        raw_custom = metadata.extra.get("customData")
        self._custom_data: str = "" if raw_custom is None else str(raw_custom)

        # examples_direct_connect) Подписка на «ожидаемый» ключ
        self._subscription = self.redis.subscribe_to_key(self.telemetry_key, self._on_telemetry_change)
        snapshot = self.redis.get_json(self.telemetry_key)

        # 2) Если по ожидаемому ключу ничего нет — попробуем обнаружить реальный ключ через SCAN
        if snapshot is None:
            resolved = self._resolve_existing_telemetry_key()
            if resolved and resolved != self.telemetry_key:
                # переедем на найденный ключ
                try:
                    self._subscription.close()
                except Exception:
                    pass
                self.telemetry_key = resolved
                self._subscription = self.redis.subscribe_to_key(self.telemetry_key, self._on_telemetry_change)
                snapshot = self.redis.get_json(self.telemetry_key)

        if self.name:
            self._cache_name_in_metadata()

        if snapshot is not None:
            self._on_telemetry_change(self.telemetry_key, snapshot, "initial")

    # --- новый метод: ищем точный ключ в Redis по device_id ---
    def _resolve_existing_telemetry_key(self) -> Optional[str]:
        """
        Ищет существующий ключ телеметрии по шаблону:
        se:{owner}:grid:{grid}:*:{device_id}:telemetry
        Возвращает точное имя ключа либо None.
        """
        owner = self.grid.owner_id
        grid_id = self.grid.grid_id
        did = self.device_id
        pattern = f"se:{owner}:grid:{grid_id}:*:{did}:telemetry"
        try:
            # используем SCAN, чтобы не блокировать Redis
            for key in self.redis.client.scan_iter(match=pattern, count=100):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "replace")
                return key  # берём первый найденный
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    def update_metadata(self, metadata: DeviceMetadata) -> None:
        self.metadata = metadata
        new_name = (
            metadata.name
            or metadata.extra.get("customName")
            or metadata.extra.get("name")
            or metadata.extra.get("displayName")
            or metadata.extra.get("displayNameText")
        )
        if new_name:
            self.name = new_name
            self._cache_name_in_metadata()
        if self.telemetry is not None:
            if self._sync_name_with_telemetry():
                self._persist_common_telemetry()

    # ------------------------------------------------------------------
    def _on_telemetry_change(self, key: str, payload: Optional[Any], event: str) -> None:
        if payload is None:
            return
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {"raw": payload}
        if isinstance(payload, dict):
            telemetry_payload = dict(payload)
            changed = self._merge_common_telemetry(telemetry_payload)
            self.telemetry = telemetry_payload
            if changed:
                self._persist_common_telemetry()
            self.handle_telemetry(telemetry_payload)

    # ------------------------------------------------------------------
    def handle_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Hook for subclasses to parse telemetry."""

    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        if isinstance(self.telemetry, dict) and "enabled" in self.telemetry:
            return bool(self.telemetry["enabled"])
        return self._enabled

    @property
    def enabled(self) -> bool:
        return self.is_enabled()

    def enable(self) -> int:
        return self.set_enabled(True)

    def disable(self) -> int:
        return self.set_enabled(False)

    def toggle_enabled(self) -> int:
        result = self.send_command({"cmd": "toggle"})
        if result:
            self._update_common_flag("enabled", not self.is_enabled())
        return result

    def set_enabled(self, enabled: bool) -> int:
        command = "enable" if enabled else "disable"
        result = self.send_command({"cmd": command})
        if result:
            self._update_common_flag("enabled", bool(enabled))
        return result

    # ------------------------------------------------------------------

    def show_in_terminal(self) -> Optional[bool]:
        return self._read_bool_flag("showInTerminal")

    def set_show_in_terminal(self, visible: bool) -> int:
        return self._send_boolean_command("set_show_in_terminal", "showInTerminal", visible)

    def show_in_toolbar(self) -> Optional[bool]:
        return self._read_bool_flag("showInToolbar")

    def set_show_in_toolbar(self, visible: bool) -> int:
        return self._send_boolean_command("set_show_in_toolbar", "showInToolbar", visible)

    def show_on_screen(self) -> Optional[bool]:
        return self._read_bool_flag("showOnScreen")

    def set_show_on_screen(self, visible: bool) -> int:
        return self._send_boolean_command("set_show_on_screen", "showOnScreen", visible)

    def custom_data(self) -> str:
        if isinstance(self.telemetry, dict):
            value = self.telemetry.get("customData")
            if value is None:
                if "customData" not in self.telemetry:
                    self.telemetry["customData"] = self._custom_data
                return self._custom_data
            text_value = str(value)
            if text_value != self._custom_data:
                self._custom_data = text_value
            return self._custom_data
        return self._custom_data

    def set_custom_data(self, data: str) -> int:
        payload = {
            "cmd": "set_custom_data",
            "state": {"customData": str(data)},
        }
        result = self.send_command(payload)
        if result:
            self._update_common_flag("customData", str(data))
        return result

    # ------------------------------------------------------------------

    def _read_bool_flag(self, key: str) -> Optional[bool]:
        if isinstance(self.telemetry, dict) and key in self.telemetry:
            return bool(self.telemetry[key])
        attr = {
            "showInTerminal": self._show_in_terminal,
            "showInToolbar": self._show_in_toolbar,
            "showOnScreen": self._show_on_screen,
        }.get(key)
        return attr if attr is None else bool(attr)

    def _send_boolean_command(self, command: str, telemetry_key: str, value: bool) -> int:
        payload = {
            "cmd": command,
            "state": {telemetry_key: bool(value)},
        }
        result = self.send_command(payload)
        if result:
            self._update_common_flag(telemetry_key, bool(value))
        return result

    def _update_common_flag(self, key: str, value: Any) -> None:
        telemetry = self._ensure_telemetry_dict()
        telemetry[key] = value
        if key == "enabled":
            self._enabled = bool(value)
        elif key == "showInTerminal":
            self._show_in_terminal = bool(value)
        elif key == "showInToolbar":
            self._show_in_toolbar = bool(value)
        elif key == "showOnScreen":
            self._show_on_screen = bool(value)
        elif key == "customData":
            self._custom_data = str(value)
        self._persist_common_telemetry()

    def _ensure_telemetry_dict(self) -> Dict[str, Any]:
        if not isinstance(self.telemetry, dict):
            self.telemetry = {}
        return self.telemetry

    def _merge_common_telemetry(self, telemetry: Dict[str, Any]) -> bool:
        changed = False

        if "enabled" in telemetry:
            self._enabled = bool(telemetry["enabled"])
        else:
            telemetry["enabled"] = bool(self._enabled)
            changed = True

        if "showInTerminal" in telemetry:
            self._show_in_terminal = bool(telemetry["showInTerminal"])
        else:
            telemetry["showInTerminal"] = bool(self._show_in_terminal)
            changed = True

        if "showInToolbar" in telemetry:
            self._show_in_toolbar = bool(telemetry["showInToolbar"])
        else:
            telemetry["showInToolbar"] = bool(self._show_in_toolbar)
            changed = True

        if "showOnScreen" in telemetry:
            self._show_on_screen = bool(telemetry["showOnScreen"])
        else:
            telemetry["showOnScreen"] = bool(self._show_on_screen)
            changed = True

        if "customData" in telemetry:
            raw_custom = telemetry["customData"]
            if raw_custom is None:
                telemetry["customData"] = ""
                self._custom_data = ""
                changed = True
            else:
                text_value = str(raw_custom)
                if text_value != self._custom_data:
                    self._custom_data = text_value
        else:
            telemetry["customData"] = self._custom_data
            changed = True

        if self._sync_name_with_telemetry(telemetry):
            changed = True

        return changed

    def _sync_name_with_telemetry(self, telemetry: Optional[Dict[str, Any]] = None) -> bool:
        target = telemetry if telemetry is not None else self._ensure_telemetry_dict()
        changed = False

        if self.name:
            for key in ("name", "customName", "displayName", "displayNameText", "CustomName", "DisplayName"):
                if target.get(key) != self.name:
                    target[key] = self.name
                    changed = True
            self._cache_name_in_metadata()
        else:
            for key in ("customName", "name", "displayName", "displayNameText", "CustomName", "DisplayName"):
                value = target.get(key)
                if value:
                    text_value = str(value)
                    if text_value != self.name:
                        self.name = text_value
                        self._cache_name_in_metadata()
                    break

        return changed

    def _cache_name_in_metadata(self) -> None:
        if not getattr(self, "metadata", None):
            return
        if self.name:
            try:
                self.metadata.name = self.name
            except Exception:
                pass
        extra = getattr(self.metadata, "extra", None)
        if not isinstance(extra, dict):
            extra = {}
            try:
                self.metadata.extra = extra  # type: ignore[assignment]
            except Exception:
                return
        if not self.name:
            return
        for key in ("customName", "name", "displayName", "displayNameText"):
            extra[key] = self.name

    def _persist_common_telemetry(self) -> None:
        if not isinstance(self.telemetry, dict):
            return
        try:
            self.redis.set_json(self.telemetry_key, self.telemetry)
        except Exception:
            pass

    @staticmethod
    def _extract_optional_bool(data: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
        return None

    # ------------------------------------------------------------------

    def command_channel(self) -> str:
        # было: return f"se.commands.device.{self.device_id}"
        return f"se.{self.grid.player_id}.commands.device.{self.device_id}"

    def _command_channels(self) -> list[str]:
        # используем только один канал, чтобы не дублировать команды
        return [self.command_channel()]

    def send_command(self, command: Dict[str, Any]) -> int:
        def to_int(x):
            try: return int(x)
            except Exception: return None

        did = to_int(self.device_id)
        gid = to_int(self.grid_id)
        pid = to_int(self.grid.player_id)

        if did is not None:
            command.setdefault("deviceId", did)
            command.setdefault("entityId", did)
        if gid is not None:
            command.setdefault("gridId", gid)
            command.setdefault("gridEntityId", gid)
            command.setdefault("grid_id", gid)
        if pid is not None:
            command.setdefault("playerId", pid)
            command.setdefault("player_id", pid)
            command.setdefault("userId", pid)

        command.setdefault("meta", {}).setdefault("user", "grid-wrapper")
        now_ms = int(time.time() * 1000)
        command.setdefault("seq", now_ms)
        command.setdefault("ts", now_ms)

        sent = 0
        for ch in self._command_channels():
            sent += self.redis.publish(ch, command)
            print(command)
        return sent

    # ------------------------------------------------------------------
    def close(self) -> None:
        self._subscription.close()


class TakeGrid:
    """A utility class that returns a ready-to-use Grid object based on an index or the first available grid."""

    def __init__(self, index: int = None, redis_client=None, owner_id=None) -> None:
        from .common import resolve_owner_id
        from .redis_client import RedisEventClient

        # Используем переданные значения или получаем их из конфигурации
        self.redis = redis_client or RedisEventClient()
        self.owner_id = owner_id or resolve_owner_id()

        # Получаем список гридов
        grids = self.redis.list_grids(self.owner_id)

        if not grids:
            raise ValueError(f"No grids found for owner {self.owner_id}")

        # Определяем, какой грид использовать
        if index is None:
            # Берем первый доступный грид
            selected_grid = grids[0]
        else:
            # Проверяем, что индекс в допустимом диапазоне
            if index < 0 or index >= len(grids):
                raise ValueError(
                    f"Grid index {index} is out of range (available indices: 0-{len(grids)-1})"
                )
            selected_grid = grids[index]

        # Извлекаем информацию о выбранном гриде
        grid_id = selected_grid.get("id")
        grid_name = selected_grid.get("name") or f"Grid_{grid_id}"
        player_id = selected_grid.get("playerId") or self.owner_id

        # Создаем внутренний объект Grid
        self._internal_grid = Grid(
            self.redis,
            self.owner_id,
            str(grid_id),
            player_id,
            grid_name,
        )

    def __getattr__(self, name):
        """Делегируем все неопределенные атрибуты внутреннему объекту Grid."""

        return getattr(self._internal_grid, name)

# Карта: нормализованный тип -> класс устройства
DEVICE_TYPE_MAP: Dict[str, Type[BaseDevice]] = {}

TYPE_ALIASES = {
    "MyObjectBuilder_Thrust": "thruster",
    "MyObjectBuilder_Gyro": "gyro",
    "MyObjectBuilder_BatteryBlock": "battery",
    "MyObjectBuilder_Reactor": "reactor",
    "MyObjectBuilder_ShipConnector": "connector",
    "MyObjectBuilder_RemoteControl": "remote_control",
    "MyObjectBuilder_CargoContainer": "container",
    "MyObjectBuilder_Cockpit": "cockpit",
    "MyObjectBuilder_OxygenGenerator": "gas_generator",
    "MyObjectBuilder_Refinery": "refinery",
    "MyObjectBuilder_ConveyorSorter": "conveyor_sorter",
    "MyObjectBuilder_ShipWelder": "ship_welder",
    "MyObjectBuilder_ShipGrinder": "ship_grinder",
    "MyObjectBuilder_ShipDrill": "ship_drill",
    "MyObjectBuilder_LargeTurretBase": "large_turret",
    "MyObjectBuilder_LargeGatlingTurret": "large_turret",
    "MyObjectBuilder_LargeMissileTurret": "large_turret",
    "MyObjectBuilder_InteriorTurret": "interior_turret",
    "MyObjectBuilder_SmallGatlingGun": "weapon",
    "MyObjectBuilder_LargeGatlingGun": "weapon",
    "MyObjectBuilder_SmallMissileLauncher": "weapon",
    "MyObjectBuilder_LargeMissileLauncher": "weapon",
    "MyObjectBuilder_SmallMissileLauncherReload": "weapon",
    "MyObjectBuilder_OreDetector": "ore_detector",
    "MyObjectBuilder_InteriorLight": "lamp",
    "MyObjectBuilder_ReflectorLight": "lamp",
    "MyObjectBuilder_LightingBlock": "lamp",
    "cargo_container": "container",
    "container": "container",
    "MyObjectBuilder_Projector": "projector",
    "projector": "projector",
    "cockpit": "cockpit",
    "oxygen_generator": "gas_generator",
    "gas_generator": "gas_generator",
    "conveyorsorter": "conveyor_sorter",
    "conveyor_sorter": "conveyor_sorter",
    "shipwelder": "ship_welder",
    "ship_welder": "ship_welder",
    "shipgrinder": "ship_grinder",
    "ship_grinder": "ship_grinder",
    "shipdrill": "ship_drill",
    "ship_drill": "ship_drill",
    "largeturret": "large_turret",
    "large_turret": "large_turret",
    "interior_turret": "interior_turret",
    "interiorturret": "interior_turret",
    "weapon": "weapon",
    "weapons": "weapon",
    "usercontrollablegun": "weapon",
    "user_controllable_gun": "weapon",
    "lamp": "lamp",
    "light": "lamp",
    "lighting_block": "lamp",
    "interior_light": "lamp",
    "reflector_light": "lamp",
}


def normalize_device_type(raw_type: Optional[str]) -> str:
    if not raw_type:
        return "generic"
    t = str(raw_type)
    # точное совпадение по объект билдеру
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    # запасной вариант: "MyObjectBuilder_Xxx" -> "xxx"
    if t.startswith("MyObjectBuilder_"):
        return t.split("_", 1)[1].lower()
    return t.lower()


def create_device(grid: Grid, metadata: DeviceMetadata) -> BaseDevice:
    # Проверим, есть ли в DEVICE_REGISTRY прямое сопоставление
    device_cls_or_name = DEVICE_REGISTRY.get(metadata.device_type, None)
    if device_cls_or_name is None:
        # Используем DEVICE_TYPE_MAP для разрешения по типу из метаданных
        device_cls = DEVICE_TYPE_MAP.get(metadata.device_type.lower(), GenericDevice)
    else:
        # Если в DEVICE_REGISTRY есть запись, проверим, является ли она строкой (именем типа)
        if isinstance(device_cls_or_name, str):
            device_cls = DEVICE_TYPE_MAP.get(device_cls_or_name, GenericDevice)
        else:
            # иначе это уже сам класс устройства
            device_cls = device_cls_or_name
    
    return device_cls(grid, metadata)


class GenericDevice(BaseDevice):
    """Fallback device that simply exposes telemetry."""
