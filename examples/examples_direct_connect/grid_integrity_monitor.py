"""Пример комплексного отслеживания целостности грида Space Engineers.

Этот пример демонстрирует:
- Текущее состояние целостности всех блоков грида
- Мониторинг изменений целостности в реальном времени
- Отслеживание событий повреждений с информацией об атакующих
- Визуализацию общего состояния здоровья грида
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from secontrol.base_device import (
    BlockInfo,
    DamageEvent,
    Grid,
    GridIntegrityChange,
)
from secontrol.common import close, prepare_grid


@dataclass
class IntegrityStats:
    """Статистика целостности грида."""

    total_blocks: int = 0
    damaged_blocks: int = 0
    critical_blocks: int = 0  # integrity < 25%
    destroyed_blocks: int = 0  # integrity <= 0
    total_integrity: float = 0.0
    total_max_integrity: float = 0.0


    @property
    def overall_integrity_ratio(self) -> float:
        """Общий коэффициент целостности грида (0.0 - 1.0)."""
        if self.total_max_integrity == 0:
            return 1.0
        return self.total_integrity / self.total_max_integrity

    @property
    def health_percentage(self) -> float:
        """Процент здоровья грида."""
        return self.overall_integrity_ratio * 100.0


class GridIntegrityMonitor:
    """Монитор целостности грида с расширенной функциональностью."""

    def __init__(self, grid: Grid):
        self.grid = grid
        self.damage_history: List[DamageEvent] = []
        self.integrity_changes: List[GridIntegrityChange] = []
        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        """Настройка обработчиков событий."""

        # Обработчик изменений целостности
        def on_integrity_change(changes: Dict[str, Any]) -> None:
            integrity_changes = changes.get("changes", [])
            self.integrity_changes.extend(integrity_changes)
            # Ограничиваем историю последних 100 изменений
            if len(self.integrity_changes) > 100:
                self.integrity_changes = self.integrity_changes[-100:]

        self.grid.on("integrity", on_integrity_change)

        # Обработчик событий повреждений
        def on_damage_event(event: DamageEvent | Dict[str, Any] | str) -> None:
            if isinstance(event, DamageEvent):
                self.damage_history.append(event)
                # Ограничиваем историю последних 50 событий
                if len(self.damage_history) > 50:
                    self.damage_history = self.damage_history[-50:]

        self.damage_subscription = self.grid.subscribe_to_damage(on_damage_event)

    def get_current_integrity_stats(self) -> IntegrityStats:
        """Получить текущую статистику целостности грида."""
        stats = IntegrityStats()
        blocks = list(self.grid.iter_blocks())

        stats.total_blocks = len(blocks)

        for block in blocks:
            integrity = block.state.get("integrity", 0)
            max_integrity = block.state.get("maxIntegrity", 0)

            stats.total_integrity += integrity
            stats.total_max_integrity += max_integrity

            if block.is_damaged:
                stats.damaged_blocks += 1

            if max_integrity > 0:
                ratio = integrity / max_integrity
                if ratio <= 0:
                    stats.destroyed_blocks += 1
                elif ratio < 0.25:
                    stats.critical_blocks += 1

        return stats

    def get_blocks_by_integrity_status(self) -> Dict[str, List[BlockInfo]]:
        """Получить блоки, сгруппированные по статусу целостности."""
        categories = {
            "healthy": [],      # integrity >= 75%
            "damaged": [],      # 25% <= integrity < 75%
            "critical": [],     # 0 < integrity < 25%
            "destroyed": [],    # integrity <= 0
            "unknown": []       # нет данных о целостности
        }

        for block in self.grid.iter_blocks():
            integrity = block.state.get("integrity")
            max_integrity = block.state.get("maxIntegrity")

            if integrity is None or max_integrity is None or max_integrity == 0:
                categories["unknown"].append(block)
                continue

            ratio = integrity / max_integrity
            if ratio <= 0:
                categories["destroyed"].append(block)
            elif ratio < 0.25:
                categories["critical"].append(block)
            elif ratio < 0.75:
                categories["damaged"].append(block)
            else:
                categories["healthy"].append(block)

        return categories

    def get_recent_damage_events(self, limit: int = 10) -> List[DamageEvent]:
        """Получить последние события повреждений."""
        return self.damage_history[-limit:] if self.damage_history else []

    def get_recent_integrity_changes(self, limit: int = 10) -> List[GridIntegrityChange]:
        """Получить последние изменения целостности."""
        return self.integrity_changes[-limit:] if self.integrity_changes else []

    def get_integrity_trends(self) -> Dict[str, Any]:
        """Анализ трендов целостности."""
        if not self.integrity_changes:
            return {"trend": "stable", "description": "Нет данных об изменениях"}

        # Анализ последних 20 изменений
        recent_changes = self.integrity_changes[-20:]
        damage_count = sum(1 for change in recent_changes if change.is_damaged and not change.was_damaged)
        repair_count = sum(1 for change in recent_changes if not change.is_damaged and change.was_damaged)

        if damage_count > repair_count * 2:
            trend = "deteriorating"
            description = f"Грид ухудшается ({damage_count} повреждений vs {repair_count} ремонтов)"
        elif repair_count > damage_count * 2:
            trend = "improving"
            description = f"Грид восстанавливается ({repair_count} ремонтов vs {damage_count} повреждений)"
        else:
            trend = "stable"
            description = f"Состояние стабильно ({damage_count} повреждений, {repair_count} ремонтов)"

        return {
            "trend": trend,
            "description": description,
            "recent_damage_count": damage_count,
            "recent_repair_count": repair_count
        }

    def close(self) -> None:
        """Закрыть подписки."""
        try:
            self.damage_subscription.close()
        except Exception:
            pass


def format_integrity_ratio(block: BlockInfo) -> str:
    """Форматировать коэффициент целостности блока."""
    integrity = block.state.get("integrity")
    max_integrity = block.state.get("maxIntegrity")

    if integrity is None or max_integrity is None or max_integrity == 0:
        return "?"

    ratio = integrity / max_integrity
    percentage = ratio * 100

    # Цветовая индикация
    if ratio <= 0:
        status = "УНИЧТОЖЕН"
    elif ratio < 0.25:
        status = "КРИТИЧНО"
    elif ratio < 0.75:
        status = "ПОВРЕЖДЕН"
    else:
        status = "ЦЕЛ"

    return f"{percentage:.1f}% ({integrity:.0f}/{max_integrity:.0f}) [{status}]"


def format_block_name(block: BlockInfo) -> str:
    """Форматировать имя блока для отображения."""
    name = block.name or block.subtype or block.block_type or "Блок"
    return f"{name} (#{block.block_id})"


def print_grid_integrity_report(monitor: GridIntegrityMonitor) -> None:
    """Вывести отчет о целостности грида."""
    print("\n" + "="*80)
    print("ОТЧЕТ О ЦЕЛОСТНОСТИ ГРИДА")
    print("="*80)

    # Общая статистика
    stats = monitor.get_current_integrity_stats()
    print("\nОБЩАЯ СТАТИСТИКА:")
    print(f"  Всего блоков: {stats.total_blocks}")
    print(f"  Поврежденных блоков: {stats.damaged_blocks}")
    print(f"  Критических блоков: {stats.critical_blocks}")
    print(f"  Уничтоженных блоков: {stats.destroyed_blocks}")
    print(f"  Общее здоровье: {stats.health_percentage:.1f}%")

    # Статус грида
    health_pct = stats.health_percentage
    if health_pct >= 90:
        status = "ОТЛИЧНЫЙ"
    elif health_pct >= 75:
        status = "ХОРОШИЙ"
    elif health_pct >= 50:
        status = "СРЕДНИЙ"
    elif health_pct >= 25:
        status = "ПЛОХОЙ"
    else:
        status = "КРИТИЧНЫЙ"

    print(f"  Статус грида: {status}")

    # Блоки по категориям
    categories = monitor.get_blocks_by_integrity_status()
    print("\nБЛОКИ ПО КАТЕГОРИЯМ:")
    for category, blocks in categories.items():
        if not blocks:
            continue

        category_names = {
            "healthy": "Целые блоки",
            "damaged": "Поврежденные блоки",
            "critical": "Критические блоки",
            "destroyed": "Уничтоженные блоки",
            "unknown": "Блоки без данных"
        }

        print(f"  {category_names[category]}: {len(blocks)}")
        if len(blocks) <= 5:  # Показываем детали только для небольшого количества
            for block in blocks[:5]:
                print(f"    - {format_block_name(block)}: {format_integrity_ratio(block)}")

    # Тренды
    trends = monitor.get_integrity_trends()
    print("\nТРЕНДЫ ЦЕЛОСТНОСТИ:")
    print(f"  {trends['description']}")

    # Последние изменения
    recent_changes = monitor.get_recent_integrity_changes(5)
    if recent_changes:
        print("\nПОСЛЕДНИЕ ИЗМЕНЕНИЯ ЦЕЛОСТНОСТИ:")
        for change in recent_changes:
            block_name = change.name or change.subtype or change.block_type or f"Блок #{change.block_id}"
            old_ratio = "?"
            new_ratio = "?"

            if change.previous_integrity is not None and change.previous_max_integrity and change.previous_max_integrity > 0:
                old_ratio = f"{(change.previous_integrity / change.previous_max_integrity * 100):.1f}%"
            if change.current_integrity is not None and change.current_max_integrity and change.current_max_integrity > 0:
                new_ratio = f"{(change.current_integrity / change.current_max_integrity * 100):.1f}%"

            status_change = ""
            if change.was_damaged != change.is_damaged:
                if change.is_damaged:
                    status_change = " (СТАЛ ПОВРЕЖДЕННЫМ)"
                else:
                    status_change = " (ВОССТАНОВЛЕН)"

            print(f"  {block_name}: {old_ratio} → {new_ratio}{status_change}")

    # Последние повреждения
    recent_damage = monitor.get_recent_damage_events(5)
    if recent_damage:
        print("\nПОСЛЕДНИЕ СОБЫТИЯ ПОВРЕЖДЕНИЙ:")
        for event in recent_damage:
            if event.block:
                block_name = event.block.name or event.block.block_type or f"Блок #{event.block.block_id}"
            else:
                block_name = "Неизвестный блок"

            attacker = "Неизвестный"
            if event.attacker.name:
                attacker = event.attacker.name
            elif event.attacker.type:
                attacker = f"Тип: {event.attacker.type}"
            elif event.attacker.entity_id:
                attacker = f"ID: {event.attacker.entity_id}"

            deformation = " (деформация)" if event.damage.is_deformation else ""
            print(f"  {block_name}: -{event.damage.amount:.1f} HP от {event.damage.damage_type}")
            print(f"    Атакующий: {attacker}{deformation}")


def interactive_monitor(monitor: GridIntegrityMonitor) -> None:
    """Интерактивный режим мониторинга."""
    print("Запуск мониторинга целостности грида...")
    print("Команды:")
    print("  'status' - показать текущий статус")
    print("  'changes' - показать последние изменения")
    print("  'damage' - показать последние повреждения")
    print("  'blocks' - показать все блоки")
    print("  'quit' - выход")
    print("Нажмите Enter для обновления статуса...")

    last_update = 0
    while True:
        try:
            command = input("\nКоманда (или Enter для статуса): ").strip().lower()

            if command == "quit":
                break
            elif command == "status":
                print_grid_integrity_report(monitor)
            elif command == "changes":
                changes = monitor.get_recent_integrity_changes(10)
                if changes:
                    print("\nПОСЛЕДНИЕ ИЗМЕНЕНИЯ:")
                    for change in changes:
                        block_name = change.name or f"Блок #{change.block_id}"
                        print(f"  {block_name}: был поврежден={change.was_damaged} → поврежден={change.is_damaged}")
                else:
                    print("Нет изменений целостности.")
            elif command == "damage":
                damage_events = monitor.get_recent_damage_events(10)
                if damage_events:
                    print("\nПОСЛЕДНИЕ ПОВРЕЖДЕНИЯ:")
                    for event in damage_events:
                        block_name = event.block.name if event.block else "Неизвестный"
                        print(f"  {block_name}: -{event.damage.amount:.1f} HP")
                else:
                    print("Нет событий повреждений.")
            elif command == "blocks":
                categories = monitor.get_blocks_by_integrity_status()
                print("\nВСЕ БЛОКИ ПО КАТЕГОРИЯМ:")
                for category, blocks in categories.items():
                    print(f"\n{category.upper()}:")
                    for block in blocks:
                        print(f"  {format_block_name(block)}: {format_integrity_ratio(block)}")
            elif command == "":
                # Автоматическое обновление каждые 5 секунд
                current_time = time.time()
                if current_time - last_update >= 5:
                    print_grid_integrity_report(monitor)
                    last_update = current_time
                else:
                    print("Обновление слишком частое. Подождите...")
            else:
                print("Неизвестная команда. Доступные: status, changes, damage, blocks, quit")

        except KeyboardInterrupt:
            print("\nПрерывание по Ctrl+C...")
            break
        except Exception as e:
            print(f"Ошибка: {e}")


def main() -> None:
    """Основная функция."""
    print("Монитор целостности грида Space Engineers")
    print("Подключение к гриду...")

    grid = prepare_grid()
    monitor = GridIntegrityMonitor(grid)

    print(f"Подключено к гриду: {grid.name} (ID: {grid.grid_id})")
    print(f"Найдено блоков: {len(list(grid.iter_blocks()))}")

    try:
        # Показать начальный отчет
        print_grid_integrity_report(monitor)

        # Запустить интерактивный режим
        interactive_monitor(monitor)

    except KeyboardInterrupt:
        print("\nЗавершение работы...")
    finally:
        monitor.close()
        close(grid)


if __name__ == "__main__":
    main()
