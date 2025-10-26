"""Пример отслеживания всех гридов игрока с детализацией изменений."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

from secontrol.base_device import BlockInfo, normalize_device_type
from secontrol.common import resolve_owner_id, resolve_player_id
from secontrol.grids import GridState, Grids
from secontrol.redis_client import RedisEventClient


@dataclass
class DeviceSnapshot:
    """Минимальное описание устройства грида."""

    device_id: str
    device_type: str
    raw_type: Optional[str]
    name: Optional[str]

    def label(self) -> str:
        type_hint = self.raw_type or self.device_type or "device"
        base = self.name or type_hint
        return f"{base} (#{self.device_id}, {self.device_type})"


@dataclass
class BlockSnapshot:
    """Минимальное описание блока грида."""

    block_id: int
    block_type: str
    subtype: Optional[str]
    name: Optional[str]
    integrity: Optional[float]
    max_integrity: Optional[float]
    is_damaged: bool

    def title(self) -> str:
        base = self.name or self.subtype or self.block_type or "block"
        return f"{base} (#{self.block_id})"

    def integrity_ratio(self) -> Optional[float]:
        if self.integrity is None or self.max_integrity in (None, 0):
            return None
        return self.integrity / self.max_integrity


@dataclass
class GridSnapshot:
    """Снимок состояния грида для поиска различий."""

    state: GridState
    devices: Dict[str, DeviceSnapshot]
    blocks: Dict[int, BlockSnapshot]


def describe(state: GridState) -> str:
    name = state.name or "(без имени)"
    return f"{name} [{state.grid_id}]"


def _collect_entries(section: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(section, dict):
        for value in section.values():
            if isinstance(value, dict):
                yield value
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield item
    elif isinstance(section, list):
        for item in section:
            if isinstance(item, dict):
                yield item


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_blocks_from_sources(sources: Iterable[Mapping[str, Any]]) -> Dict[int, BlockSnapshot]:
    blocks: Dict[int, BlockSnapshot] = {}
    for source in sources:
        root = source.get("blocks") if isinstance(source, Mapping) else None
        comp = source.get("comp") if isinstance(source, Mapping) else None
        candidates: List[Dict[str, Any]] = []
        if root is not None:
            candidates.extend(_collect_entries(root))
        if isinstance(comp, Mapping) and "blocks" in comp:
            candidates.extend(_collect_entries(comp.get("blocks")))

        for entry in candidates:
            try:
                info = BlockInfo.from_payload(entry)
            except Exception:
                continue
            integrity = _safe_float(info.state.get("integrity")) if info.state else None
            max_integrity = _safe_float(info.state.get("maxIntegrity")) if info.state else None
            blocks[info.block_id] = BlockSnapshot(
                block_id=info.block_id,
                block_type=str(info.block_type),
                subtype=str(info.subtype) if info.subtype else None,
                name=str(info.name) if info.name else None,
                integrity=integrity,
                max_integrity=max_integrity,
                is_damaged=info.is_damaged,
            )
    return blocks


def _extract_devices_from_sources(sources: Iterable[Mapping[str, Any]]) -> Dict[str, DeviceSnapshot]:
    devices: Dict[str, DeviceSnapshot] = {}
    for source in sources:
        root = source.get("devices") if isinstance(source, Mapping) else None
        comp = source.get("comp") if isinstance(source, Mapping) else None
        sections: List[Any] = []
        if root is not None:
            sections.append(root)
        if isinstance(comp, Mapping) and "devices" in comp:
            sections.append(comp.get("devices"))

        for section in sections:
            for entry in _collect_entries(section):
                raw_id = (
                    entry.get("deviceId")
                    or entry.get("entityId")
                    or entry.get("id")
                    or entry.get("blockId")
                )
                if raw_id in (None, ""):
                    continue
                device_id = str(raw_id)
                raw_type = entry.get("type") or entry.get("deviceType") or entry.get("subtype")
                normalized = normalize_device_type(raw_type)
                custom_name = entry.get("customName") or entry.get("CustomName")
                display_name = (
                    entry.get("displayName")
                    or entry.get("displayNameText")
                    or entry.get("DisplayName")
                    or entry.get("DisplayNameText")
                )
                name = custom_name or display_name or entry.get("name") or entry.get("Name")
                devices[device_id] = DeviceSnapshot(
                    device_id=device_id,
                    device_type=normalized,
                    raw_type=str(raw_type) if raw_type else None,
                    name=str(name) if isinstance(name, str) and name.strip() else None,
                )
    return devices


def _build_snapshot(state: GridState) -> GridSnapshot:
    sources: List[Mapping[str, Any]] = []
    if isinstance(state.descriptor, Mapping):
        sources.append(state.descriptor)
    if isinstance(state.info, Mapping):
        sources.append(state.info)
    devices = _extract_devices_from_sources(sources)
    blocks = _extract_blocks_from_sources(sources)
    return GridSnapshot(state=state, devices=devices, blocks=blocks)


def _approx_equal(a: Optional[float], b: Optional[float], *, rel_tol: float = 1e-3) -> bool:
    if a is None or b is None:
        return a == b
    if a == b:
        return True
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1.0)
    return diff <= rel_tol * scale


def _format_integrity(block: BlockSnapshot) -> str:
    ratio = block.integrity_ratio()
    if ratio is not None:
        return f"{ratio * 100:.1f}% ({block.integrity:.0f}/{block.max_integrity:.0f})"
    if block.integrity is not None:
        return f"{block.integrity:.0f}"
    return "?"


def _diff_devices(previous: Dict[str, DeviceSnapshot], current: Dict[str, DeviceSnapshot]) -> List[str]:
    messages: List[str] = []
    prev_keys = set(previous)
    curr_keys = set(current)

    for device_id in sorted(curr_keys - prev_keys, key=lambda x: (len(x), x)):
        messages.append(f"[+] Устройство добавлено: {current[device_id].label()}")

    for device_id in sorted(prev_keys - curr_keys, key=lambda x: (len(x), x)):
        messages.append(f"[-] Устройство удалено: {previous[device_id].label()}")

    for device_id in sorted(prev_keys & curr_keys, key=lambda x: (len(x), x)):
        before = previous[device_id]
        after = current[device_id]
        changes: List[str] = []
        if before.device_type != after.device_type:
            changes.append(f"тип {before.device_type} → {after.device_type}")
        if (before.name or "") != (after.name or ""):
            changes.append(
                f"имя {(before.name or '(без имени)')} → {(after.name or '(без имени)')}"
            )
        if changes:
            messages.append(f"[~] Устройство {after.label()}: {', '.join(changes)}")

    return messages


def _diff_blocks(previous: Dict[int, BlockSnapshot], current: Dict[int, BlockSnapshot]) -> List[str]:
    messages: List[str] = []
    prev_ids = set(previous)
    curr_ids = set(current)

    for block_id in sorted(curr_ids - prev_ids):
        block = current[block_id]
        messages.append(
            f"[+] Блок добавлен: {block.title()} (целостность {_format_integrity(block)})"
        )

    for block_id in sorted(prev_ids - curr_ids):
        block = previous[block_id]
        messages.append(f"[-] Блок удалён: {block.title()}")

    for block_id in sorted(prev_ids & curr_ids):
        before = previous[block_id]
        after = current[block_id]
        changes: List[str] = []
        if (before.name or "") != (after.name or ""):
            changes.append(
                f"имя {(before.name or '(без имени)')} → {(after.name or '(без имени)')}"
            )
        before_type = before.subtype or before.block_type
        after_type = after.subtype or after.block_type
        if before_type != after_type:
            changes.append(f"тип {before_type} → {after_type}")

        integrity_changed = not (
            _approx_equal(before.integrity, after.integrity)
            and _approx_equal(before.max_integrity, after.max_integrity)
        )
        damaged_changed = before.is_damaged != after.is_damaged
        if integrity_changed or damaged_changed:
            integrity_change = f"целостность {_format_integrity(before)} → {_format_integrity(after)}"
            if damaged_changed:
                damage_state = "повреждён" if after.is_damaged else "восстановлен"
                integrity_change = f"{integrity_change}, {damage_state}"
            changes.append(integrity_change)

        if changes:
            messages.append(f"[~] Блок {after.title()}: {', '.join(changes)}")

    return messages


def _describe_changes(previous: Optional[GridSnapshot], current: GridSnapshot) -> List[str]:
    if previous is None:
        return []
    messages: List[str] = []
    messages.extend(_diff_devices(previous.devices, current.devices))
    messages.extend(_diff_blocks(previous.blocks, current.blocks))
    return messages


def main() -> None:
    client = RedisEventClient()
    owner_id = resolve_owner_id()
    player_id = resolve_player_id(owner_id)
    grids = Grids(client, owner_id, player_id)

    snapshots: MutableMapping[str, GridSnapshot] = {}

    print("Текущие гриды:")
    current = grids.list()
    if not current:
        print("  (нет гридов)")
    for state in current:
        snapshot = _build_snapshot(state)
        snapshots[state.grid_id] = snapshot
        print(
            f"  * {describe(state)} — устройств: {len(snapshot.devices)}, блоков: {len(snapshot.blocks)}"
        )

    def handle_added(state: GridState) -> None:
        snapshot = _build_snapshot(state)
        snapshots[state.grid_id] = snapshot
        print(
            f"[+] Появился грид: {describe(state)} — устройств: {len(snapshot.devices)}, блоков: {len(snapshot.blocks)}"
        )

    def handle_updated(state: GridState) -> None:
        previous = snapshots.get(state.grid_id)
        snapshot = _build_snapshot(state)
        snapshots[state.grid_id] = snapshot
        changes = _describe_changes(previous, snapshot)
        if changes:
            print(f"[*] Обновился грид: {describe(state)}")
            for line in changes:
                print("    " + line)
        else:
            print(f"[*] Обновился грид: {describe(state)} (без изменений блоков и устройств)")

    def handle_removed(state: GridState) -> None:
        snapshots.pop(state.grid_id, None)
        print(f"[-] Исчез грид: {describe(state)}")

    grids.on_added(handle_added)
    grids.on_updated(handle_updated)
    grids.on_removed(handle_removed)

    print("Ожидаем изменения... Нажмите Ctrl+C для выхода.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Завершение...")
    finally:
        grids.close()
        client.close()


if __name__ == "__main__":
    main()

