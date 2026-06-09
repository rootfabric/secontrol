"""Управление очередью конструктора: сборка, разбор, удаление и очистка.

Примеры:
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 view
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 add SteelPlate 100
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 disassemble SteelPlate 10
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 remove 0 --amount 5
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 clear
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode assemble
  python examples/organized/assembler/intermediate/assembler_queue_control.py --grid farpost0 mode disassemble
"""

from __future__ import annotations

import argparse
import json
from typing import Iterable

from secontrol.common import close, prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice


def find_assemblers(grid) -> list[AssemblerDevice]:
    """Ассемблеры только самого грида (исключая subgrid'ы)."""
    target_grid_id = str(getattr(grid, "grid_id", "") or "")
    result: list[AssemblerDevice] = []
    for device in grid.devices.values():
        if not isinstance(device, AssemblerDevice):
            continue
        if str(getattr(device, "grid_id", "") or "") != target_grid_id:
            continue
        telemetry = getattr(device, "telemetry", None) or {}
        tel_grid = str(telemetry.get("gridId", "") or "")
        if tel_grid and tel_grid != target_grid_id:
            continue
        result.append(device)
    return result


def choose_assembler(grid, assembler_id: str | None = None, name: str | None = None) -> AssemblerDevice | None:
    assemblers = find_assemblers(grid)
    if not assemblers:
        return None

    if assembler_id:
        wanted = str(assembler_id).strip()
        for assembler in assemblers:
            if str(assembler.device_id) == wanted:
                return assembler
        return None

    if name:
        wanted_name = name.strip().lower()
        for assembler in assemblers:
            if wanted_name in str(assembler.name or "").lower():
                return assembler
        return None

    for assembler in assemblers:
        telemetry = assembler.telemetry or {}
        enabled = bool(telemetry.get("enabled", True))
        functional = bool(telemetry.get("isFunctional", True))
        if enabled and functional:
            return assembler
    return assemblers[0]


def refresh(assembler: AssemblerDevice, timeout: float = 1.0) -> None:
    try:
        assembler.wait_for_telemetry(timeout=timeout, wait_for_new=True, need_update=True)
    except Exception:
        pass


def print_state(assembler: AssemblerDevice, *, full: bool = False) -> None:
    refresh(assembler)
    telemetry = assembler.telemetry or {}
    print(f"Конструктор: {assembler.name} ({assembler.device_id})")
    print(
        "  "
        f"enabled={telemetry.get('enabled', 'N/A')} "
        f"conveyor={telemetry.get('useConveyorSystem', 'N/A')} "
        f"disassemble={telemetry.get('disassembleEnabled', 'N/A')} "
        f"repeat={telemetry.get('repeatEnabled', 'N/A')} "
        f"cooperative={telemetry.get('cooperativeMode', 'N/A')} "
        f"producing={telemetry.get('isProducing', 'N/A')} "
        f"progress={float(telemetry.get('currentProgress', 0.0) or 0.0):.3f}"
    )
    assembler.print_queue()
    if full:
        print("\nПолная телеметрия:")
        print(json.dumps(telemetry, indent=2, ensure_ascii=False))


def bool_text(value: bool | None) -> str:
    if value is None:
        return "toggle"
    return "on" if value else "off"


def parse_on_off(value: str) -> bool | None:
    text = value.strip().lower()
    if text in {"on", "true", "1", "yes", "y", "enable", "enabled", "disassemble"}:
        return True
    if text in {"off", "false", "0", "no", "n", "disable", "disabled", "assemble"}:
        return False
    if text in {"toggle", "switch"}:
        return None
    raise argparse.ArgumentTypeError(f"ожидалось on/off/toggle, получено: {value}")


def run(args: argparse.Namespace) -> int:
    grid = prepare_grid(args.grid)
    try:
        assembler = choose_assembler(grid, args.assembler_id, args.name)
        if not assembler:
            print("Конструктор не найден на гриде")
            return 1

        print(f"Грид: {grid.name}")
        print(f"Выбран конструктор: {assembler.name} ({assembler.device_id})")

        if args.command == "view":
            print_state(assembler, full=args.full)
            return 0

        if args.command == "add":
            if not assembler.set_disassemble_verified(False, timeout=args.timeout):
                print("[!] Не удалось подтвердить режим сборки. Задачу не добавляю, чтобы не отправить её на разбор.")
                return 2
            blueprint_id = assembler.resolve_blueprint_id(args.blueprint, request=True)
            print(f"Добавляю на сборку: {args.blueprint} -> {blueprint_id} x{args.amount}")
            ok = assembler.add_queue_item_verified(blueprint_id, args.amount, timeout=args.timeout, disassemble=False)
            print_state(assembler, full=False)
            return 0 if ok else 3

        if args.command == "disassemble":
            if not assembler.set_disassemble_verified(True, timeout=args.timeout):
                print("[!] Не удалось подтвердить режим разбора. Задачу не добавляю.")
                return 2
            blueprint_id = assembler.resolve_blueprint_id(args.blueprint, request=True)
            print(f"Добавляю на разбор: {args.blueprint} -> {blueprint_id} x{args.amount}")
            ok = assembler.add_disassemble_item_verified(blueprint_id, args.amount, timeout=args.timeout)
            print_state(assembler, full=False)
            return 0 if ok else 3

        if args.command == "remove":
            print(f"Удаляю из очереди: index={args.index}, amount={args.amount}")
            ok = assembler.remove_queue_item_verified(args.index, args.amount, timeout=args.timeout)
            print_state(assembler, full=False)
            return 0 if ok else 3

        if args.command == "clear":
            print("Очищаю очередь конструктора")
            ok = assembler.clear_queue_verified(timeout=args.timeout)
            print_state(assembler, full=False)
            return 0 if ok else 3

        if args.command == "mode":
            enabled = args.mode == "disassemble"
            print(f"Ставлю режим: {'разбор' if enabled else 'сборка'}")
            ok = assembler.set_disassemble_verified(enabled, timeout=args.timeout)
            print_state(assembler, full=False)
            return 0 if ok else 3

        if args.command == "conveyor":
            enabled = parse_on_off(args.value)
            print(f"Переключаю conveyor: {bool_text(enabled)}")
            if enabled is None:
                sent = assembler.set_use_conveyor(None)
                ok = sent > 0
            else:
                ok = assembler.set_use_conveyor_verified(enabled, timeout=args.timeout)
            print_state(assembler, full=False)
            return 0 if ok else 3

        print(f"Неизвестная команда: {args.command}")
        return 1
    finally:
        close(grid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление очередью конструктора Space Engineers")
    parser.add_argument("--grid", required=True, help="Имя или ID грида")
    parser.add_argument("--assembler-id", help="ID конкретного конструктора")
    parser.add_argument("--name", help="Часть имени конструктора")
    parser.add_argument("--timeout", type=float, default=5.0, help="Сколько секунд ждать подтверждения телеметрией")

    subparsers = parser.add_subparsers(dest="command", required=True)

    view_parser = subparsers.add_parser("view", help="Показать состояние и очередь")
    view_parser.add_argument("--full", action="store_true", help="Показать полную телеметрию")

    add_parser = subparsers.add_parser("add", help="Добавить задачу на сборку")
    add_parser.add_argument("blueprint", help="Subtype или полный blueprintId, например SteelPlate")
    add_parser.add_argument("amount", type=float, help="Количество")

    dis_parser = subparsers.add_parser("disassemble", help="Добавить задачу на разбор")
    dis_parser.add_argument("blueprint", help="Subtype или полный blueprintId, например SteelPlate")
    dis_parser.add_argument("amount", type=float, help="Количество")

    remove_parser = subparsers.add_parser("remove", help="Удалить позицию из очереди")
    remove_parser.add_argument("index", type=int, help="Index из очереди")
    remove_parser.add_argument("--amount", type=float, help="Сколько убрать; если не указано, убирается вся позиция")

    subparsers.add_parser("clear", help="Очистить очередь")

    mode_parser = subparsers.add_parser("mode", help="Переключить режим сборка/разбор")
    mode_parser.add_argument("mode", choices=["assemble", "disassemble"], help="assemble или disassemble")

    conveyor_parser = subparsers.add_parser("conveyor", help="Переключить Use Conveyor System")
    conveyor_parser.add_argument("value", help="on/off/toggle")

    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
