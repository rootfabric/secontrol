import time

from secontrol.common import prepare_grid
from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.devices.cockpit_device import CockpitDevice
from secontrol.controllers.shared_map_controller import SharedMapController
from secontrol.tools.radar_visualizer import RadarVisualizer
from secontrol.tools.navigation_tools import get_world_position




MAX_SOLID_POINTS = 2000


def _downsample_points(points, max_points: int = MAX_SOLID_POINTS):
    """Уменьшить количество точек до max_points, удаляя близкие.

    Используем грубую 3D-квантовку: пространство делится на кубики,
    и из каждой ячейки берётся только одна точка.
    """
    points = list(points)
    if len(points) <= max_points:
        return points

    # Границы облака точек
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)

    range_x = max(max_x - min_x, 1e-3)
    range_y = max(max_y - min_y, 1e-3)
    range_z = max(max_z - min_z, 1e-3)

    volume = range_x * range_y * range_z

    if volume <= 0.0:
        # Все точки почти в одном месте — просто прореживаем по шагу
        step = max(1, len(points) // max_points)
        return points[::step]

    # Подбираем размер ячейки так, чтобы число ячеек примерно соответствовало max_points
    cell_size = (volume / float(max_points)) ** (1.0 / 3.0)
    cell_size = max(cell_size, 1e-3)

    cells = {}
    for p in points:
        x, y, z = p
        ix = int((x - min_x) / cell_size)
        iy = int((y - min_y) / cell_size)
        iz = int((z - min_z) / cell_size)
        key = (ix, iy, iz)
        if key not in cells:
            cells[key] = p
            if len(cells) >= max_points:
                break

    return list(cells.values())


class App:
    def __init__(self, grid_name: str) -> None:
        # Грид
        self.grid = prepare_grid(grid_name)

        # Находим устройства
        ore_detectors = self.grid.find_devices_by_type(OreDetectorDevice)
        remotes = self.grid.find_devices_by_type(RemoteControlDevice)
        cockpits = self.grid.find_devices_by_type(CockpitDevice)
        if not ore_detectors:
            raise RuntimeError("Не найден OreDetector на гриде")
        if not remotes:
            raise RuntimeError("Не найден RemoteControl на гриде")

        self.radar_device = ore_detectors[0]
        self.remote = remotes[0]
        self.cockpit = cockpits[0] if cockpits else None

        # Контроллер радара (сканирование вокселей)
        self.radar_ctrl = RadarController(self.radar_device, radius=500.0)

        # Контроллер общей карты (Redis)
        # owner_id берём из грида, чтобы карта была привязана к игроку
        self.map_ctrl = SharedMapController(owner_id=self.grid.owner_id)

        # Проверить общее количество данных
        data_all = self.map_ctrl.load()
        print(f"Всего сохранено: {len(data_all.voxels)} вокселей, {len(data_all.ores)} руд, {len(data_all.visited)} посещенных")

        # Размер данных
        # redis_size = self.map_ctrl.get_storage_usage()
        # print(f"Размер карты в Redis: {redis_size} байт ({redis_size / 1024:.1f} KB)")

        # Радиус визуализации
        self.visualization_radius = 1000.0

        # Визуализатор карты
        self.visualizer = RadarVisualizer()
        self.visualize_loaded_map()

    def visualize_loaded_map(self) -> None:
        """Визуализировать загруженную карту с помощью RadarVisualizer."""
        # Получить позицию из кокпита или remote
        device = self.cockpit or self.remote
        device.update()
        own_position = get_world_position(device)
        if not own_position:
            print("Не удалось получить позицию для визуализации")
            return

        own_position = list(own_position)
        print(f"Позиция для загрузки: {own_position}")

        # Загрузить регион карты вокруг позиции
        data = self.map_ctrl.load_region(center=own_position, radius=self.visualization_radius)
        print(f"Загружено: {len(data.voxels)} вокселей, {len(data.ores)} руд, {len(data.visited)} посещенных")

        # Подготовка данных для визуализации
        solid = [list(point) for point in data.voxels]

        # # Если точек слишком много — проредим до MAX_SOLID_POINTS
        if len(solid) > MAX_SOLID_POINTS:
            print(f"Слишком много точек для визуализации ({len(solid)}), "
                  f"сжимаю до {MAX_SOLID_POINTS}...")
            solid = _downsample_points(solid, max_points=MAX_SOLID_POINTS)
            print(f"После даунсэмплинга осталось {len(solid)} точек.")


        # Вычислить метаданные для региона
        cell_size = 10.0  # Увеличить для уменьшения размера сетки
        origin = [
            own_position[0] - self.visualization_radius,
            own_position[1] - self.visualization_radius,
            own_position[2] - self.visualization_radius,
        ]
        size_dim = int(2 * self.visualization_radius / cell_size) + 1
        size = [size_dim, size_dim, size_dim]
        metadata = {
            "size": size,
            "cellSize": cell_size,
            "origin": origin,
        }

        # Контакты: добавить visited как контакты типа "grid"
        contacts = [{"type": "grid", "position": list(point)} for point in data.visited]

        # Добавить текущую позицию грида как контакт типа "grid"
        if own_position:
            contacts.append({"type": "grid", "position": list(own_position)})

        # Ячейки руды
        ore_cells = [{"position": list(ore.position)} for ore in data.ores]

        # Визуализация
        self.visualizer.visualize(solid, metadata, contacts, own_position, ore_cells)

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
        # self.scan_and_update_map()
        # здесь твоя логика полёта к следующей точке и т.п.
        """"""


def main() -> None:
    app = App("taburet")
    try:
        while True:
            app.patrol_step()
            time.sleep(10.0)
    finally:
        app.visualizer.close()


if __name__ == "__main__":
    main()
