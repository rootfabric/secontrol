from __future__ import annotations

import time

from secontrol.common import prepare_grid
from secontrol.devices.connector_device import ConnectorDevice


def main() -> None:
    grid = prepare_grid("136772854332817581")

    print(grid)

    # Найти первый коннектор на гриде
    connectors = list(grid.find_devices_by_type(ConnectorDevice))
    if not connectors:
        print("No connectors found on the grid")
        return

    connector = connectors[0]
    print(f"Using connector: {connector.name or 'Unnamed'} (ID: {connector.device_id})")

    # Отправить команду сканирования
    # print("Scanning for nearby connectors...")
    # connector.scan(radius=100.0)
    # time.sleep(0.2)
    print(connector.telemetry)

    # connector.disconnect()
    connector.connect()
    exit(0)

    # Взять предмет из первого слота и передать на первый обнаруженный коннектор
    items = connector.inventory_items()
    if items:
        first_item = items[0]
        item_dict = {"subtype": first_item.subtype, "amount": first_item.amount}
        print(f"Transferring {first_item.amount} x {first_item.subtype} to nearby connector...")
        connector.transfer_to_nearby([item_dict])
    else:
        print("No items in connector inventory.")

    print("Scan complete. Check server logs for detailed results.")


if __name__ == "__main__":
    main()
