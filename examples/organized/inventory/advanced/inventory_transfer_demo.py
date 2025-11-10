"""Пример последовательного переноса предметов между инвентарями.

Скрипт показывает, как работать с новым инвентарным API:
- выбирать конкретные контейнеры внутри устройства;
- передавать предметы между ними с указанием источника и получателя.
"""

from __future__ import annotations

from typing import Optional

from secontrol.common import prepare_grid
from secontrol.devices.assembler_device import AssemblerDevice
from secontrol.devices.container_device import ContainerDevice
from secontrol.devices.refinery_device import RefineryDevice
from secontrol.inventory import InventorySnapshot


def _pick_inventory(device: ContainerDevice, key: str | None) -> Optional[InventorySnapshot]:
    if key:
        snapshot = device.get_inventory(key)
        if snapshot:
            return snapshot
    return device.get_inventory()


def _describe(snapshot: Optional[InventorySnapshot]) -> str:
    if not snapshot:
        return "(инвентарь не найден)"
    items = ", ".join(f"{item.amount:.1f} {item.subtype}" for item in snapshot.items) or "пусто"
    return f"{snapshot.name}: {items}"


def main() -> None:
    grid = prepare_grid()

    container = grid.find_devices_by_type(ContainerDevice)
    refinery = grid.find_devices_by_type(RefineryDevice)
    assembler = grid.find_devices_by_type(AssemblerDevice)

    if not container or not refinery or not assembler:
        print("Для демонстрации нужен хотя бы один контейнер, перерабатывающий завод и ассемблер.")
        return

    cargo = container[0]
    ref = refinery[0]
    asm = assembler[0]

    cargo_inv = _pick_inventory(cargo, None)
    ref_input = _pick_inventory(ref, "inputInventory")
    ref_output = _pick_inventory(ref, "outputInventory")
    asm_input = _pick_inventory(asm, "inputInventory")
    asm_output = _pick_inventory(asm, "outputInventory")

    print("Исходное состояние:")
    print("  Контейнер:", _describe(cargo_inv))
    print("  Рефайнер (вход):", _describe(ref_input))
    print("  Рефайнер (выход):", _describe(ref_output))
    print("  Ассемблер (вход):", _describe(asm_input))
    print("  Ассемблер (выход):", _describe(asm_output))

    # 1. Переносим руду из контейнера в входной инвентарь перерабатывающего завода
    print("\nПереносим IronOre из контейнера в вход рефайнера...")
    cargo.move_subtype(
        ref,
        "IronOre",
        source_inventory=cargo_inv,
        destination_inventory=ref_input,
    )

    # 2. Переносим готовые слитки из выхода рефайнера в вход ассемблера
    print("Переносим SteelIngot из выхода рефайнера во вход ассемблера...")
    ref.move_subtype(
        asm,
        "SteelIngot",
        source_inventory=ref_output,
        destination_inventory=asm_input,
    )

    # 3. Возвращаем готовую продукцию из выхода ассемблера обратно в контейнер
    print("Переносим SteelPlate из выхода ассемблера в контейнер...")
    asm.move_subtype(
        cargo,
        "SteelPlate",
        source_inventory=asm_output,
        destination_inventory=cargo_inv,
    )

    print("\nКоманды отправлены. Телеметрия обновится после выполнения операций на сервере.")


if __name__ == "__main__":
    main()
