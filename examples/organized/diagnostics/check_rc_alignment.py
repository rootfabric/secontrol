"""Проверка ориентации блока Remote Control на гриде.

Источник истины — `block.extra["local_orientation"]`, который публикуется
плагином Space Engineers и сообщает, в какую сторону грида смотрит
локальная ось +Z (forward) блока. Стандартное размещение RC:
``local_forward="Forward"`` и ``local_up="Up"`` — в этом случае ось блока
совпадает с осью корабля.

Использование из кода:

.. code-block:: python

    from secontrol import Grid
    from secontrol.redis_client import RedisEventClient
    from examples.organized.diagnostics.check_rc_alignment import diagnose_rc_placement

    client = RedisEventClient()
    grid = Grid.from_name("my_ship", redis_client=client)
    diagnostic = {"grid": grid.name}
    diagnostic = diagnose_rc_placement(grid, diagnostic)
    print(diagnostic["rc_alignment"]["status"], diagnostic["rc_alignment"]["ok"])

Использование из CLI:

.. code-block:: bash

    python check_rc_alignment.py --grid my_ship
    python check_rc_alignment.py --grid my_ship --json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, List, Optional, Tuple

from secontrol import Grid
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.redis_client import RedisEventClient


_VALID_DIRECTIONS = {"Forward", "Backward", "Up", "Down", "Left", "Right"}
_LOCAL_KEY_CANDIDATES = (
    "local_orientation",
    "localOrientation",
    "LocalOrientation",
)
_LOCAL_AXIS_KEYS = (
    "forward",
    "Forward",
    "up",
    "Up",
    "left",
    "Left",
    "right",
    "Right",
)

_DIRECTION_TO_ANGLE_DEG: Dict[str, float] = {
    "Forward": 0.0,
    "Backward": 180.0,
    "Up": 90.0,
    "Down": 90.0,
    "Left": 90.0,
    "Right": 90.0,
}

_EXPECTED_FORWARD = "Forward"
_EXPECTED_UP = "Up"

_DEGENERATE_LENGTH_TOL = 0.05
_DEGENERATE_DOT_TOL = 0.05


def _coerce_block_id(block: Any) -> Optional[str]:
    if block is None:
        return None
    raw = getattr(block, "block_id", None)
    if raw is None and isinstance(block, dict):
        raw = block.get("id") or block.get("blockId") or block.get("entityId")
    if raw is None:
        return None
    return str(raw)


def _read_local_orientation(block: Any) -> Optional[Dict[str, str]]:
    """Извлекает ``{forward: 'Forward', up: 'Up', ...}`` из метаданных блока.

    Поддерживает как ``BlockInfo`` (атрибут ``extra``), так и сырые dict-пейлоады.
    Возвращает ``None``, если поле отсутствует или имеет неожиданный формат.
    """
    if block is None:
        return None

    extra: Any
    if isinstance(block, dict):
        extra = block
    else:
        extra = getattr(block, "extra", None)
    if not isinstance(extra, dict):
        return None

    raw: Any = None
    for key in _LOCAL_KEY_CANDIDATES:
        if key in extra:
            raw = extra.get(key)
            if raw:
                break
    if not isinstance(raw, dict):
        return None

    result: Dict[str, str] = {}
    for key in _LOCAL_AXIS_KEYS:
        value = raw.get(key)
        if not isinstance(value, str):
            continue
        direction = value.strip()
        if direction in _VALID_DIRECTIONS:
            norm_key = key.lower()
            result.setdefault(norm_key, direction)
    return result or None


def _find_rc_block(grid: Grid, rc: RemoteControlDevice) -> Any:
    """Возвращает ``BlockInfo`` (или ``None``), соответствующий устройству RC."""
    wanted = str(rc.device_id)
    for block in grid.blocks.values():
        if _coerce_block_id(block) == wanted:
            return block
    return None


def _classify_placement(local_forward: str, local_up: str) -> Tuple[str, str]:
    """Возвращает ``(status, severity)`` по паре forward/up из local_orientation."""
    if local_forward == _EXPECTED_FORWARD and local_up == _EXPECTED_UP:
        return "OK", "info"
    if local_forward == "Forward" and local_up == "Down":
        return "OK_UPSIDE_DOWN", "warn"
    if local_forward == "Forward" and local_up in ("Left", "Right"):
        return "OK_ROLLED", "warn"
    if local_forward == "Backward":
        return "REVERSED", "warn"
    if local_forward in ("Up", "Down"):
        return "OFF_AXIS_VERTICAL", "warn"
    if local_forward in ("Left", "Right"):
        return "OFF_AXIS_HORIZONTAL", "warn"
    return "UNKNOWN", "warn"


def _check_world_basis(rc: RemoteControlDevice) -> Optional[Dict[str, float]]:
    """Снимает мировой базис блока и проверяет его на ортонормальность.

    Возвращает ``None``, если в телеметрии нет ``orientation``-векторов.
    """
    tel = rc.telemetry or {}
    orientation = tel.get("orientation")
    if not isinstance(orientation, dict):
        return None

    fwd_raw = orientation.get("forward")
    up_raw = orientation.get("up")
    if not isinstance(fwd_raw, dict) or not isinstance(up_raw, dict):
        return None
    try:
        fwd = (float(fwd_raw["x"]), float(fwd_raw["y"]), float(fwd_raw["z"]))
        up = (float(up_raw["x"]), float(up_raw["y"]), float(up_raw["z"]))
    except (KeyError, TypeError, ValueError):
        return None

    fwd_len = math.sqrt(sum(c * c for c in fwd))
    up_len = math.sqrt(sum(c * c for c in up))
    dot = fwd[0] * up[0] + fwd[1] * up[1] + fwd[2] * up[2]
    return {
        "world_forward_len": fwd_len,
        "world_up_len": up_len,
        "world_forward_dot_up": dot,
    }


def _build_recommendations(status: str, local_forward: str, local_up: str) -> List[str]:
    if status == "OK":
        return []
    if status == "REVERSED":
        return [
            "Разверните блок Remote Control на 180° вокруг оси Up "
            "(forward → Forward, up → Up) — иначе корабль будет лететь задом при автопилоте."
        ]
    if status.startswith("OFF_AXIS"):
        return [
            f"Переставьте RC на переднюю грань (forward=Forward, up=Up). "
            f"Сейчас forward смотрит в {local_forward} — это даёт угол 90° к оси корабля."
        ]
    if status == "OK_UPSIDE_DOWN":
        return [
            f"RC перевёрнут (up={local_up}) — большинство скриптов ожидают up=Up."
        ]
    if status == "OK_ROLLED":
        return [
            f"RC повёрнут вокруг оси forward (up={local_up}) — это нестандартная ориентация."
        ]
    return [f"Не удалось классифицировать размещение RC (forward={local_forward}, up={local_up})."]


def _build_warning_note(status: str, local_forward: str, angle_deg: float) -> Optional[str]:
    if status == "OK":
        return None
    if status == "REVERSED":
        return f"RC смонтирован задом (forward={local_forward}) — автопилот поведёт корабль назад."
    if status.startswith("OFF_AXIS"):
        return (
            f"RC смонтирован не на передней грани (forward={local_forward}, "
            f"угол к оси корабля = {angle_deg:.0f}°)."
        )
    if status == "OK_UPSIDE_DOWN":
        return f"RC перевёрнут (up=Down) — большинство скриптов ожидают up=Up."
    if status == "OK_ROLLED":
        return f"RC повёрнут вокруг оси forward — нестандартная ориентация."
    return f"Не удалось классифицировать размещение RC (forward={local_forward})."


def diagnose_rc_placement(
    grid: Grid,
    diagnostic: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Проверяет, правильно ли блок RC установлен на гриде.

    Параметры
    ----------
    grid:
        Открытый :class:`secontrol.Grid` с активной подпиской.
    diagnostic:
        Необязательный внешний словарь, в который дописывается секция
        ``"rc_alignment"``. Удобно для склейки нескольких диагностик
        в один отчёт.

    Возвращает
    -----------
    dict
        Тот же словарь, что и ``diagnostic`` (или новый ``{}``), с секцией::

            {
                "rc_alignment": {
                    "status": "OK" | "OK_UPSIDE_DOWN" | "OK_ROLLED"
                              | "REVERSED" | "OFF_AXIS_VERTICAL"
                              | "OFF_AXIS_HORIZONTAL" | "UNKNOWN"
                              | "ERROR_NO_RC" | "ERROR_NO_BLOCK_METADATA"
                              | "ERROR_NO_LOCAL_ORIENTATION" | "WARN_DEGENERATE_ORIENTATION",
                    "severity": "info" | "warn" | "error",
                    "ok": bool,
                    "rcs": [ ... ],
                    "primary_rc": dict | None,
                    "warnings": [str, ...],
                    "recommendations": [str, ...],
                }
            }
    """
    if diagnostic is None:
        diagnostic = {}

    rcs = grid.find_devices_by_type(RemoteControlDevice)

    if not rcs:
        section: Dict[str, Any] = {
            "status": "ERROR_NO_RC",
            "severity": "error",
            "ok": False,
            "rcs": [],
            "primary_rc": None,
            "warnings": ["Remote Control block not found on this grid."],
            "recommendations": [
                "Установите блок Remote Control на корабль — без него автопилот и RC-скрипты не работают."
            ],
        }
        diagnostic["rc_alignment"] = section
        diagnostic["ok"] = False
        return diagnostic

    rc_reports: List[Dict[str, Any]] = []
    top_warnings: List[str] = []
    top_recommendations: List[str] = []

    for rc in rcs:
        try:
            rc.update()
        except Exception as exc:
            top_warnings.append(f"Не удалось обновить телеметрию RC '{rc.name}': {exc}")
            continue

        report: Dict[str, Any] = {
            "name": rc.name,
            "device_id": rc.device_id,
            "block_id": None,
            "local_forward": None,
            "local_up": None,
            "local_left": None,
            "local_right": None,
            "status": "ERROR_NO_BLOCK_METADATA",
            "severity": "error",
            "ok": False,
        }

        block = _find_rc_block(grid, rc)
        if block is None:
            report["warnings"] = [
                f"BlockInfo для RC '{rc.name}' (device_id={rc.device_id}) не найден в grid.blocks."
            ]
            top_warnings.append(f"Метаданные блока RC '{rc.name}' отсутствуют.")
            top_recommendations.append(
                "Вызовите grid.refresh_devices() — возможно, грид ещё не успел подтянуть дамп."
            )
            rc_reports.append(report)
            continue

        report["block_id"] = getattr(block, "block_id", None)
        loc = _read_local_orientation(block)
        report["local_forward"] = (loc or {}).get("forward")
        report["local_up"] = (loc or {}).get("up")
        report["local_left"] = (loc or {}).get("left")
        report["local_right"] = (loc or {}).get("right")

        if not loc or "forward" not in loc or "up" not in loc:
            report["status"] = "ERROR_NO_LOCAL_ORIENTATION"
            report["warnings"] = [
                f"У блока '{rc.name}' нет local_orientation в block.extra — "
                "плагин SE, вероятно, устарел."
            ]
            top_warnings.append(f"local_orientation отсутствует для RC '{rc.name}'.")
            top_recommendations.append(
                "Обновите плагин Space Engineers до версии, которая публикует block.local_orientation."
            )
            rc_reports.append(report)
            continue

        forward = loc["forward"]
        up = loc["up"]
        status, severity = _classify_placement(forward, up)
        report["status"] = status
        report["severity"] = severity
        report["ok"] = status == "OK"
        report["angle_to_grid_forward_deg"] = _DIRECTION_TO_ANGLE_DEG.get(forward, 90.0)
        report["expected_local_forward"] = _EXPECTED_FORWARD
        report["expected_local_up"] = _EXPECTED_UP

        basis = _check_world_basis(rc)
        degenerate = False
        if basis is not None:
            report.update(basis)
            if (
                abs(basis["world_forward_len"] - 1.0) > _DEGENERATE_LENGTH_TOL
                or abs(basis["world_up_len"] - 1.0) > _DEGENERATE_LENGTH_TOL
                or abs(basis["world_forward_dot_up"]) > _DEGENERATE_DOT_TOL
            ):
                degenerate = True
                report["status"] = "WARN_DEGENERATE_ORIENTATION"
                report["severity"] = "error"
                report["ok"] = False
                report["warnings"] = [
                    f"Мировой базис RC '{rc.name}' вырожден: "
                    f"|fwd|={basis['world_forward_len']:.3f}, "
                    f"|up|={basis['world_up_len']:.3f}, "
                    f"dot(fwd,up)={basis['world_forward_dot_up']:+.3f}."
                ]
                top_warnings.extend(report["warnings"])

        if not degenerate:
            for note in _build_recommendations(status, forward, up):
                if note not in top_recommendations:
                    top_recommendations.append(note)
            warn_note = _build_warning_note(status, forward, report["angle_to_grid_forward_deg"])
            if warn_note is not None:
                top_warnings.append(warn_note)

        rc_reports.append(report)

    overall_ok = bool(rc_reports) and all(r.get("ok") for r in rc_reports)
    primary = next((r for r in rc_reports if r.get("ok")), rc_reports[0] if rc_reports else None)
    severity = "info" if overall_ok else (rc_reports[0].get("severity", "error") if rc_reports else "error")
    status = "OK" if overall_ok else (rc_reports[0].get("status", "ERROR_NO_RC") if rc_reports else "ERROR_NO_RC")

    diagnostic["rc_alignment"] = {
        "status": status,
        "severity": severity,
        "ok": overall_ok,
        "rcs": rc_reports,
        "primary_rc": primary,
        "warnings": top_warnings,
        "recommendations": top_recommendations,
    }
    if not overall_ok:
        diagnostic["ok"] = False
    return diagnostic


def _format_for_console(diagnostic: Dict[str, Any]) -> str:
    section = diagnostic.get("rc_alignment", {})
    lines: List[str] = ["🧭 RC placement diagnostic", "=" * 40]
    if not section:
        return "\n".join(lines + ["(нет данных)"])

    icon = {"info": "✅", "warn": "⚠️ ", "error": "❌"}.get(section.get("severity", ""), "•")
    lines.append(f"{icon} Status: {section.get('status', '?')}  (severity={section.get('severity', '?')})")
    lines.append(f"   ok: {section.get('ok')}")

    rcs = section.get("rcs", [])
    if not rcs:
        lines.append("")
        lines.append("   На гриде не найдено ни одного блока Remote Control.")
    for r in rcs:
        lines.append("")
        lines.append(f"   🎮 {r.get('name', '?')}  device_id={r.get('device_id')}")
        lines.append(f"      status:        {r.get('status', '?')}")
        lines.append(
            f"      local_forward: {r.get('local_forward')!s}  (ожидается 'Forward')"
        )
        lines.append(
            f"      local_up:      {r.get('local_up')!s}  (ожидается 'Up')"
        )
        if "angle_to_grid_forward_deg" in r:
            lines.append(
                f"      угол к оси корабля: {r['angle_to_grid_forward_deg']:.0f}°"
            )
        if "world_forward_len" in r:
            lines.append(
                f"      мировой базис: |fwd|={r['world_forward_len']:.3f}, "
                f"|up|={r['world_up_len']:.3f}, "
                f"dot(fwd,up)={r.get('world_forward_dot_up', 0):+.3f}"
            )
        for warning in r.get("warnings", []) or []:
            lines.append(f"      ⚠ {warning}")

    if section.get("warnings"):
        lines.append("")
        lines.append("Сводка предупреждений:")
        for warning in section["warnings"]:
            lines.append(f"  • {warning}")
    if section.get("recommendations"):
        lines.append("")
        lines.append("Рекомендации:")
        for rec in section["recommendations"]:
            lines.append(f"  → {rec}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка ориентации блока Remote Control на гриде."
    )
    parser.add_argument("--grid", default="scout0",  help="Имя или id грида. По умолчанию — prepare_grid().")
    parser.add_argument("--json", action="store_true", help="Вывести результат как JSON.")
    args = parser.parse_args(argv)

    client = RedisEventClient()
    try:
        if args.grid:
            grid = Grid.from_name(args.grid, redis_client=client)
        else:
            from secontrol.common import prepare_grid

            grid = prepare_grid(client)
    except Exception as exc:
        print(f"❌ Не удалось открыть грид: {exc}", file=sys.stderr)
        client.close()
        return 1

    try:
        diagnostic: Dict[str, Any] = {"grid": grid.name, "grid_id": grid.grid_id}
        diagnostic = diagnose_rc_placement(grid, diagnostic)
        if args.json:
            print(json.dumps(diagnostic, ensure_ascii=False, indent=2, default=str))
        else:
            print(_format_for_console(diagnostic))
        return 0 if diagnostic.get("rc_alignment", {}).get("ok") else 2
    finally:
        try:
            grid.close()
        finally:
            client.close()


__all__ = [
    "diagnose_rc_placement",
    "_read_local_orientation",
    "_find_rc_block",
    "_classify_placement",
]


if __name__ == "__main__":
    raise SystemExit(main())
