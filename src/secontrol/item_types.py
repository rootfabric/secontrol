"""Типы предметов Space Engineers для безопасной работы с инвентарем.

Этот модуль предоставляет централизованное хранилище типов предметов,
позволяя заменить строковые проверки на типизированные методы.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

from .inventory import InventoryItem


@dataclass(frozen=True)
class ItemType:
    """Базовый класс для типа предмета."""
    type: str
    subtype: str
    display_name: str = ""
    blueprint_id: str = ""

    def __post_init__(self):
        # Если blueprint_id не указан, используем subtype
        if not self.blueprint_id:
            object.__setattr__(self, 'blueprint_id', self.subtype)

    def matches(self, item: InventoryItem) -> bool:
        """Проверяет, соответствует ли предмет этому типу."""
        return item.type == self.type and item.subtype == self.subtype

    def __str__(self) -> str:
        return f"{self.display_name or self.subtype} ({self.type})"


class ItemCategory:
    """Категория предметов с общими методами проверки."""

    def __init__(self, type_prefix: str, items: List[ItemType]):
        self.type_prefix = type_prefix
        self.items = items
        self._by_subtype = {item.subtype: item for item in items}

    def is_type(self, item: InventoryItem) -> bool:
        """Проверяет, принадлежит ли предмет к этой категории."""
        return item.type == self.type_prefix

    def get_subtype(self, subtype: str) -> ItemType | None:
        """Возвращает тип предмета по подтипу."""
        return self._by_subtype.get(subtype)

    def get_subtypes(self) -> Set[str]:
        """Возвращает все подтипы в категории."""
        return set(self._by_subtype.keys())

    def matches_any(self, item: InventoryItem, subtypes: List[str] | None = None) -> bool:
        """Проверяет, соответствует ли предмет категории и любому из подтипов."""
        if not self.is_type(item):
            return False
        if subtypes is None:
            return True
        return item.subtype in subtypes


# Руда (Ore)
ORE_ITEMS = [
    ItemType("MyObjectBuilder_Ore", "Stone", "Камень"),
    ItemType("MyObjectBuilder_Ore", "Iron", "Железная руда"),
    ItemType("MyObjectBuilder_Ore", "Nickel", "Никелевая руда"),
    ItemType("MyObjectBuilder_Ore", "Cobalt", "Кобальтовая руда"),
    ItemType("MyObjectBuilder_Ore", "Magnesium", "Магниевая руда"),
    ItemType("MyObjectBuilder_Ore", "Silicon", "Кремниевая руда"),
    ItemType("MyObjectBuilder_Ore", "Silver", "Серебряная руда"),
    ItemType("MyObjectBuilder_Ore", "Gold", "Золотая руда"),
    ItemType("MyObjectBuilder_Ore", "Platinum", "Платиновая руда"),
    ItemType("MyObjectBuilder_Ore", "Uranium", "Урановая руда"),
]

ORE = ItemCategory("MyObjectBuilder_Ore", ORE_ITEMS)

# Слитки (Ingots)
INGOT_ITEMS = [
    ItemType("MyObjectBuilder_Ingot", "Stone", "Гравий"),
    ItemType("MyObjectBuilder_Ingot", "Iron", "Железный слиток"),
    ItemType("MyObjectBuilder_Ingot", "Nickel", "Никелевый слиток"),
    ItemType("MyObjectBuilder_Ingot", "Cobalt", "Кобальтовый слиток"),
    ItemType("MyObjectBuilder_Ingot", "Magnesium", "Магниевый слиток"),
    ItemType("MyObjectBuilder_Ingot", "Silicon", "Кремниевый wafer"),
    ItemType("MyObjectBuilder_Ingot", "Silver", "Серебряный слиток"),
    ItemType("MyObjectBuilder_Ingot", "Gold", "Золотой слиток"),
    ItemType("MyObjectBuilder_Ingot", "Platinum", "Платиновый слиток"),
    ItemType("MyObjectBuilder_Ingot", "Uranium", "Урановый слиток"),
]

INGOT = ItemCategory("MyObjectBuilder_Ingot", INGOT_ITEMS)

# Компоненты (Components)
COMPONENT_ITEMS = [
    ItemType("MyObjectBuilder_Component", "SteelPlate", "Стальная пластина"),
    ItemType("MyObjectBuilder_Component", "InteriorPlate", "Внутренняя пластина"),
    ItemType("MyObjectBuilder_Component", "SmallTube", "Малая труба"),
    ItemType("MyObjectBuilder_Component", "LargeTube", "Большая труба"),
    ItemType("MyObjectBuilder_Component", "Motor", "Мотор"),
    ItemType("MyObjectBuilder_Component", "Construction", "Конструкционный компонент"),
    ItemType("MyObjectBuilder_Component", "MetalGrid", "Металлическая решетка"),
    ItemType("MyObjectBuilder_Component", "PowerCell", "Энергоячейка"),
    ItemType("MyObjectBuilder_Component", "RadioCommunication", "Радиосвязь"),
    ItemType("MyObjectBuilder_Component", "Detector", "Детектор"),
    ItemType("MyObjectBuilder_Component", "Medical", "Медицинский компонент"),
    ItemType("MyObjectBuilder_Component", "Display", "Дисплей"),
    ItemType("MyObjectBuilder_Component", "BulletproofGlass", "Бронированное стекло"),
    ItemType("MyObjectBuilder_Component", "Computer", "Компьютер"),
    ItemType("MyObjectBuilder_Component", "Reactor", "Реакторный компонент"),
    ItemType("MyObjectBuilder_Component", "Thrust", "Компонент тяги"),
    ItemType("MyObjectBuilder_Component", "GravityGenerator", "Генератор гравитации"),
    ItemType("MyObjectBuilder_Component", "SolarCell", "Солнечная панель"),
    ItemType("MyObjectBuilder_Component", "Superconductor", "Сверхпроводник"),
    ItemType("MyObjectBuilder_Component", "Girder", "Балка"),
    ItemType("MyObjectBuilder_Component", "Explosives", "Взрывчатка"),
]

COMPONENT = ItemCategory("MyObjectBuilder_Component", COMPONENT_ITEMS)

# Инструменты (Tools) - добавим базовые
TOOL_ITEMS = [
    ItemType("MyObjectBuilder_PhysicalGunObject", "Welder", "Сварщик"),
    ItemType("MyObjectBuilder_PhysicalGunObject", "AngleGrinder", "Углошлифовальная машина"),
    ItemType("MyObjectBuilder_PhysicalGunObject", "HandDrill", "Ручной бур"),
]

TOOL = ItemCategory("MyObjectBuilder_PhysicalGunObject", TOOL_ITEMS)

# Аммуниция (Ammo)
AMMO_ITEMS = [
    ItemType("MyObjectBuilder_AmmoMagazine", "NATO_5p56x45mm", "Патроны 5.56x45мм NATO"),
    ItemType("MyObjectBuilder_AmmoMagazine", "NATO_25x184mm", "Патроны 25x184мм NATO"),
    ItemType("MyObjectBuilder_AmmoMagazine", "Missile200mm", "Ракеты 200мм"),
]

AMMO = ItemCategory("MyObjectBuilder_AmmoMagazine", AMMO_ITEMS)


# Удобные функции для проверки типов
def is_ore(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет рудой."""
    return ORE.is_type(item)


def is_ingot(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет слитком."""
    return INGOT.is_type(item)


def is_component(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет компонентом."""
    return COMPONENT.is_type(item)


def is_tool(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет инструментом."""
    return TOOL.is_type(item)


def is_ammo(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет боеприпасами."""
    return AMMO.is_type(item)


# Специфические проверки для распространенных предметов
def is_platinum_ore(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет платиновой рудой."""
    return item.type == "MyObjectBuilder_Ore" and item.subtype == "Platinum"


def is_uranium_ingot(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет урановым слитком."""
    return item.type == "MyObjectBuilder_Ingot" and item.subtype == "Uranium"


def is_steel_plate(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет стальной пластиной."""
    return item.type == "MyObjectBuilder_Component" and item.subtype == "SteelPlate"


# Все категории для удобства
ALL_CATEGORIES = [ORE, INGOT, COMPONENT, TOOL, AMMO]


class _ItemRegistry:
    """Класс для удобного доступа к типам предметов через атрибуты.

    Примеры использования:
        Item.SteelPlate      # -> ItemType для стальной пластины
        Item.PlatinumOre     # -> ItemType для платиновой руды
        Item.UraniumIngot    # -> ItemType для уранового слитка
    """

    # Создаем словарь всех предметов для быстрого доступа
    _all_items = {}

    @classmethod
    def _initialize(cls):
        """Инициализирует словарь всех предметов и добавляет их как атрибуты класса."""
        if cls._all_items:  # Уже инициализировано
            return

        # Собираем все предметы из всех категорий
        for category in ALL_CATEGORIES:
            for item_type in category.items:
                # Создаем имя атрибута: PlatinumOre, SteelPlate, UraniumIngot и т.д.
                attr_name = item_type.subtype
                if category == ORE:
                    attr_name += "Ore"
                elif category == INGOT:
                    attr_name += "Ingot"
                elif category == COMPONENT:
                    pass  # SteelPlate уже правильное имя
                elif category == TOOL:
                    pass  # Welder уже правильное имя
                elif category == AMMO:
                    pass  # NATO_5p56x45mm уже правильное имя

                cls._all_items[attr_name] = item_type
                # Добавляем как атрибут класса для автодополнения IDE
                setattr(cls, attr_name, item_type)

    def __getattr__(self, name: str) -> ItemType:
        """Возвращает ItemType по имени атрибута (fallback для динамических случаев)."""
        self._initialize()
        if name in self._all_items:
            return self._all_items[name]
        raise AttributeError(f"'{self.__class__.__name__}' has no attribute '{name}'")

    def __dir__(self) -> list[str]:
        """Возвращает список доступных атрибутов для автодополнения."""
        self._initialize()
        return list(self._all_items.keys())


# Создаем глобальный экземпляр для удобного доступа
Item = _ItemRegistry()

# Инициализируем атрибуты класса для автодополнения IDE
_ItemRegistry._initialize()


def item_matches(item: InventoryItem, item_type: ItemType) -> bool:
    """Универсальная функция для проверки соответствия предмета типу.

    Args:
        item: Предмет из инвентаря
        item_type: Тип предмета для сравнения

    Returns:
        True если предмет соответствует типу

    Примеры:
        item_matches(inventory_item, Item.SteelPlate)
        item_matches(inventory_item, Item.PlatinumOre)
    """
    return item_type.matches(item)


# Для обратной совместимости оставляем старые функции,
# но помечаем их как deprecated
def is_platinum_ore(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет платиновой рудой.

    Deprecated: используйте item_matches(item, Item.PlatinumOre)
    """
    return item_matches(item, Item.PlatinumOre)


def is_uranium_ingot(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет урановым слитком.

    Deprecated: используйте item_matches(item, Item.UraniumIngot)
    """
    return item_matches(item, Item.UraniumIngot)


def is_steel_plate(item: InventoryItem) -> bool:
    """Проверяет, является ли предмет стальной пластиной.

    Deprecated: используйте item_matches(item, Item.SteelPlate)
    """
    return item_matches(item, Item.SteelPlate)


__all__ = [
    "ItemType",
    "ItemCategory",
    "Item",
    "ORE",
    "INGOT",
    "COMPONENT",
    "TOOL",
    "AMMO",
    "ALL_CATEGORIES",
    "item_matches",
    "is_ore",
    "is_ingot",
    "is_component",
    "is_tool",
    "is_ammo",
    # Устаревшие функции для обратной совместимости
    "is_platinum_ore",
    "is_uranium_ingot",
    "is_steel_plate",
]
