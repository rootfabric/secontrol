import time

from secontrol.common import prepare_grid
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.shared_map_controller import SharedMapController


class App:
    def __init__(self, grid_name: str) -> None:
        # Грид
        self.grid = prepare_grid(grid_name)

        # Находим устройства
        ore_detectors = self.grid.find_devices_by_type(OreDetectorDevice)
        remotes = self.grid.find_devices_by_type(RemoteControlDevice)
        if not ore_detectors:
            raise RuntimeError("Не найден OreDetector на гриде")
        if not remotes:
            raise RuntimeError("Не найден RemoteControl на гриде")

        self.radar_device = ore_detectors[0]
        self.remote = remotes[0]

        # Контроллер радара (сканирование вокселей)
        self.radar_ctrl = RadarController(self.radar_device, radius=200.0)

        # Контроллер общей карты (Redis)
        # owner_id берём из грида, чтобы карта была привязана к игроку
        self.map_ctrl = SharedMapController(owner_id=self.grid.owner_id)

    def scan_and_update_map(self) -> None:
        print("Выполняю скан поверхности и сохраняю в карту...")
        solid, metadata, contacts, ore_cells = self.map_ctrl.ingest_radar_scan(
            self.radar_ctrl,
            persist_metadata=True,
            save=True,
        )
        print(
            f"[map] Сохранил: "
            f"{len(solid or [])} вокселей, "
            f"{len(ore_cells or [])} ячеек руды. "
            f"Контактов: {len(contacts or []) if contacts else 0}"
        )

    def patrol_step(self) -> None:
        # Пример: делаем шаг патруля и иногда обновляем карту
        self.scan_and_update_map()
        # здесь твоя логика полёта к следующей точке и т.п.


def main() -> None:
    app = App("taburet")
    while True:
        app.patrol_step()
        time.sleep(10.0)


if __name__ == "__main__":
    main()
