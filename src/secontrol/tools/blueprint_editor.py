from dataclasses import dataclass, field
from typing import Dict, List, Iterable, Optional, Tuple


@dataclass(frozen=True, slots=True)
class Vec3i:
    """Простая целочисленная 3D-точка для координат блоков."""
    x: int
    y: int
    z: int

    def __add__(self, other: "Vec3i") -> "Vec3i":
        return Vec3i(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3i") -> "Vec3i":
        return Vec3i(self.x - other.x, self.y - other.y, self.z - other.z)


@dataclass(slots=True)
class Block:
    """
    Модель блока для работы в питоне.

    builder_type — строка вида "MyObjectBuilder_CubeBlock", "MyObjectBuilder_BatteryBlock" и т.п.
    subtype_name — SubtypeName блока ("LargeBlockArmorBlock", "LargeProjector" и т.п.)
    position — координата Min из чертежа.
    data — произвольный словарь с дополнительной инфой (ориентация, настройки и т.п.)
    """
    builder_type: str
    subtype_name: str
    position: Vec3i
    data: Dict[str, object] = field(default_factory=dict)


class BlueprintGridEditor:
    """
    Упрощённый редактор грида для blueprint'ов Space Engineers.

    Работает на уровне:
    - блок = Block(builder_type, subtype_name, position, data)
    - грид = множество блоков в целочисленных координатах.

    Основные возможности:
    - получить координаты всех блоков;
    - найти блок по координате;
    - найти координаты по SubtypeName;
    - найти свободные соседние клетки;
    - добавить блок (в том числе рядом с существующим);
    - удалить блоки;
    - получить габариты грида (min/max);
    - сдвинуть весь грид целиком.
    """

    _DIRECTION_OFFSETS: Dict[str, Vec3i] = {
        "Forward": Vec3i(0, 0, -1),
        "Backward": Vec3i(0, 0, 1),
        "Left": Vec3i(-1, 0, 0),
        "Right": Vec3i(1, 0, 0),
        "Up": Vec3i(0, 1, 0),
        "Down": Vec3i(0, -1, 0),
    }

    def __init__(self, blocks: Iterable[Block] | None = None) -> None:
        self._blocks_by_pos: Dict[Vec3i, Block] = {}
        if blocks:
            for block in blocks:
                self._blocks_by_pos[block.position] = block

    # ---------- базовая информация о гриде ----------

    def get_all_positions(self) -> List[Vec3i]:
        """Вернуть список позиций всех блоков."""
        if not self._blocks_by_pos:
            return []
        return list(self._blocks_by_pos.keys())

    def get_all_blocks(self) -> List[Block]:
        """Вернуть список всех блоков (с моделями Block)."""
        if not self._blocks_by_pos:
            return []
        return list(self._blocks_by_pos.values())

    # ---------- поиск блоков ----------

    def try_get_block_at(self, pos: Vec3i) -> Optional[Block]:
        """Вернуть блок по позиции или None, если блока нет."""
        return self._blocks_by_pos.get(pos)

    def get_positions_by_subtype(self, subtype_name: str) -> List[Vec3i]:
        """Вернуть все позиции блоков с указанным SubtypeName."""
        if not subtype_name:
            return []

        result: List[Vec3i] = []
        target = subtype_name.lower()

        for pos, block in self._blocks_by_pos.items():
            if block.subtype_name.lower() == target:
                result.append(pos)

        return result

    def try_get_any_position(self, subtype_name: str) -> Optional[Vec3i]:
        """
        Вернуть первую попавшуюся позицию блока с указанным SubtypeName или None.
        Удобно для старта достройки от какого-то типового блока (батарея, кит, проектор и т.п.).
        """
        if not subtype_name:
            return None

        target = subtype_name.lower()

        for pos, block in self._blocks_by_pos.items():
            if block.subtype_name.lower() == target:
                return pos

        return None

    # ---------- соседи и свободные клетки ----------

    def get_adjacent_positions(self, origin: Vec3i) -> List[Vec3i]:
        """Вернуть все 6 соседних позиций вокруг origin."""
        result: List[Vec3i] = []
        for offset in self._DIRECTION_OFFSETS.values():
            result.append(origin + offset)
        return result

    def get_free_adjacent_positions(self, origin: Vec3i) -> List[Vec3i]:
        """
        Вернуть соседние клетки, которые ещё не заняты блоками.
        Это прямые кандидаты, чтобы «пристроить» новый блок.
        """
        neighbors = self.get_adjacent_positions(origin)
        result: List[Vec3i] = []
        for pos in neighbors:
            if pos not in self._blocks_by_pos:
                result.append(pos)
        return result

    # ---------- габариты грида ----------

    def get_bounds(self) -> Tuple[Optional[Vec3i], Optional[Vec3i]]:
        """
        Вернуть (min, max) по всем блокам.
        Если грид пустой — (None, None).
        """
        if not self._blocks_by_pos:
            return None, None

        iterator = iter(self._blocks_by_pos.keys())
        first = next(iterator)

        min_x = max_x = first.x
        min_y = max_y = first.y
        min_z = max_z = first.z

        for pos in iterator:
            if pos.x < min_x:
                min_x = pos.x
            if pos.x > max_x:
                max_x = pos.x

            if pos.y < min_y:
                min_y = pos.y
            if pos.y > max_y:
                max_y = pos.y

            if pos.z < min_z:
                min_z = pos.z
            if pos.z > max_z:
                max_z = pos.z

        return Vec3i(min_x, min_y, min_z), Vec3i(max_x, max_y, max_z)

    # ---------- добавление блоков ----------

    def add_block(
        self,
        builder_type: str,
        subtype_name: str,
        position: Vec3i,
        **extra: object,
    ) -> Block:
        """
        Добавить новый блок на заданную позицию.

        builder_type — строка "MyObjectBuilder_XXXX".
        subtype_name — SubtypeName блока.
        position — координата Min.
        extra — любые доп. поля, которые потом можно использовать при сериализации в XML
                (например, orientation_forward="Right", orientation_up="Up" и т.д.)
        """
        if not builder_type:
            raise ValueError("builder_type must not be empty")
        if not subtype_name:
            raise ValueError("subtype_name must not be empty")

        if position in self._blocks_by_pos:
            raise ValueError(f"position {position} is already occupied")

        data: Dict[str, object] = dict(extra) if extra else {}

        block = Block(
            builder_type=builder_type,
            subtype_name=subtype_name,
            position=position,
            data=data,
        )

        self._blocks_by_pos[position] = block
        return block

    def add_large_armor_block(self, position: Vec3i, **extra: object) -> Block:
        """
        Шорткат: добавить обычный крупный армор-блок "LargeBlockArmorBlock".
        """
        return self.add_block(
            builder_type="MyObjectBuilder_CubeBlock",
            subtype_name="LargeBlockArmorBlock",
            position=position,
            **extra,
        )

    def add_block_adjacent_to(
        self,
        origin: Vec3i,
        side: str,
        builder_type: str,
        subtype_name: str,
        **extra: object,
    ) -> Block:
        """
        Добавить блок рядом с уже существующим, в выбранном направлении.

        side — одна из строк: "Forward", "Backward", "Left", "Right", "Up", "Down".
        """
        if side not in self._DIRECTION_OFFSETS:
            raise ValueError(f"unknown side '{side}'")

        offset = self._DIRECTION_OFFSETS[side]
        target = origin + offset

        if target in self._blocks_by_pos:
            raise ValueError(f"adjacent position {target} is already occupied")

        return self.add_block(builder_type, subtype_name, target, **extra)

    # ---------- удаление блоков ----------

    def remove_block_at(self, position: Vec3i) -> bool:
        """
        Удалить блок по позиции Min.
        Вернёт True, если блок был и его удалили.
        """
        block = self._blocks_by_pos.pop(position, None)
        return block is not None

    def remove_blocks_by_subtype(self, subtype_name: str) -> int:
        """
        Удалить все блоки с указанным SubtypeName.
        Вернёт количество удалённых блоков.
        """
        if not subtype_name:
            return 0

        to_remove: List[Vec3i] = []
        target = subtype_name.lower()

        for pos, block in self._blocks_by_pos.items():
            if block.subtype_name.lower() == target:
                to_remove.append(pos)

        for pos in to_remove:
            self._blocks_by_pos.pop(pos, None)

        return len(to_remove)

    # ---------- трансформация грида ----------

    def translate(self, offset: Vec3i) -> None:
        """
        Сдвинуть весь грид на указанный offset.
        Все блоки получают новые координаты.
        """
        if offset == Vec3i(0, 0, 0):
            return

        new_map: Dict[Vec3i, Block] = {}

        for block in self._blocks_by_pos.values():
            new_pos = block.position + offset
            new_block = Block(
                builder_type=block.builder_type,
                subtype_name=block.subtype_name,
                position=new_pos,
                data=dict(block.data),
            )
            new_map[new_pos] = new_block

        self._blocks_by_pos = new_map


# Пример использования (можно удалить, если не нужен):
if __name__ == "__main__":
    editor = BlueprintGridEditor()

    # центр базы
    center = Vec3i(0, 0, 0)
    editor.add_large_armor_block(center)

    # достроим "площадку" справа
    editor.add_large_armor_block(Vec3i(1, 0, 0))
    editor.add_large_armor_block(Vec3i(2, 0, 0))

    bounds = editor.get_bounds()
    print("Bounds:", bounds)

    neighbors = editor.get_adjacent_positions(center)
    print("Neighbors:", neighbors)

    free = editor.get_free_adjacent_positions(center)
    print("Free around center:", free)

    # пример: от любой батареи достроить ещё один блок сбоку
    # (в реальном коде батареи сначала нужно добавить или загрузить)
    some_battery_pos = editor.try_get_any_position("LargeBlockBatteryBlock")
    print("Any battery pos:", some_battery_pos)

    # сдвиг всей базы на +10 по X
    editor.translate(Vec3i(10, 0, 0))
    print("Translated positions:", editor.get_all_positions())


