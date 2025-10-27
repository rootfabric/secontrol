"""GUI-пример мониторинга телеметрии устройства грида Space Engineers.

Приложение использует :mod:`PySide6` для отображения списка гридов и устройств,
подключённых через Redis-шлюз. После выбора устройства выполняется
подписка на его телеметрию; данные отображаются в текстовом поле и
дополнительно протоколируются во встроенном лог-журнале и файле
``telemetry_gui.log``.

Перед запуском необходимо указать параметры подключения через переменные
окружения (см. ``README.md``): ``REDIS_URL``, ``REDIS_USERNAME``,
``REDIS_PASSWORD``, ``SE_PLAYER_ID`` и ``SE_GRID_ID`` (опционально).

Запуск:

.. code-block:: bash

    python -m secontrol.examples_direct_connect.gui_telemetry_viewer

"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QWidget,
)

from secontrol.base_device import BaseDevice, Grid
from secontrol.common import close, prepare_grid, resolve_owner_id, resolve_player_id
from secontrol.redis_client import RedisEventClient

LOGGER = logging.getLogger("telemetry_gui")


class TelemetryListener(QObject):
    """Подписка на телеметрию устройства с доставкой событий в GUI-поток."""

    telemetry_received = Signal(dict, str)
    telemetry_deleted = Signal(str)
    subscription_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._device: BaseDevice | None = None
        self._telemetry_handler: Optional[Callable[[BaseDevice, dict[str, Any], str], None]] = None
        self._cleared_handler: Optional[Callable[[BaseDevice, dict[str, Any], str], None]] = None

    def subscribe(self, device: BaseDevice | None) -> None:
        """Переключает подписку на новое устройство."""

        self.unsubscribe()
        if device is None:
            return

        self._device = device

        def _on_telemetry(dev: BaseDevice, telemetry: dict[str, Any], event: str) -> None:
            normalized = self._normalize_payload(telemetry)
            if normalized is not None:
                self.telemetry_received.emit(normalized, event)

        def _on_cleared(dev: BaseDevice, _telemetry: dict[str, Any], event: str) -> None:
            self.telemetry_deleted.emit(event)

        self._telemetry_handler = _on_telemetry
        self._cleared_handler = _on_cleared

        device.on("telemetry", _on_telemetry)
        device.on("telemetry_cleared", _on_cleared)

        snapshot = device.telemetry
        if snapshot is not None:
            normalized = self._normalize_payload(snapshot)
            if normalized is not None:
                self.telemetry_received.emit(normalized, "initial")

    def unsubscribe(self) -> None:
        if self._device is not None:
            if self._telemetry_handler is not None:
                try:
                    self._device.off("telemetry", self._telemetry_handler)
                except Exception:  # pragma: no cover - защитный код
                    pass
            if self._cleared_handler is not None:
                try:
                    self._device.off("telemetry_cleared", self._cleared_handler)
                except Exception:  # pragma: no cover
                    pass
        self._device = None
        self._telemetry_handler = None
        self._cleared_handler = None

    def _normalize_payload(self, payload: Any) -> Optional[dict[str, Any]]:
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return {"value": payload}
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"items": payload}
        return {"value": payload}


class TelemetryWindow(QMainWindow):
    """Основное окно приложения мониторинга."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Space Engineers — монитор телеметрии")
        self.resize(1100, 700)

        self._client: Optional[RedisEventClient] = None
        self._grid: Optional[Grid] = None
        self._listener: Optional[TelemetryListener] = None
        self._owner_id: Optional[str] = None
        self._player_id: Optional[str] = None
        self._last_snapshot: dict[str, Any] | None = None
        self._pending_snapshot: tuple[Optional[dict[str, Any]], str] | None = None
        self._paused = False
        self._known_devices: set[str] = set()

        self._create_logger()
        self._build_ui()
        self._setup_actions()

        self._device_refresh_timer = QTimer(self)
        self._device_refresh_timer.setInterval(1000)
        self._device_refresh_timer.timeout.connect(self._refresh_devices)

        self._initialize_connection()

    # ------------------------------------------------------------------
    def _create_logger(self) -> None:
        log_path = Path("telemetry_gui.log")
        handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        LOGGER.setLevel(logging.INFO)
        LOGGER.addHandler(handler)

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QGridLayout(central)
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Панель выбора
        selection_box = QGroupBox("Подключение")
        selection_layout = QGridLayout(selection_box)

        self.grid_combo = QComboBox()
        self.device_combo = QComboBox()
        self.device_combo.setEnabled(False)

        selection_layout.addWidget(QLabel("Грид:"), 0, 0)
        selection_layout.addWidget(self.grid_combo, 0, 1)
        selection_layout.addWidget(QLabel("Устройство:"), 1, 0)
        selection_layout.addWidget(self.device_combo, 1, 1)

        self.status_label = QLabel("Нет активной подписки")
        selection_layout.addWidget(self.status_label, 2, 0, 1, 2)

        layout.addWidget(selection_box, 0, 0)

        # Кнопки управления
        controls = QHBoxLayout()
        self.pause_button = QPushButton("Пауза")
        self.pause_button.setEnabled(False)
        controls.addWidget(self.pause_button)
        controls.addStretch(1)
        layout.addLayout(controls, 1, 0)

        # Отображение телеметрии
        telemetry_box = QGroupBox("Текущее состояние")
        telemetry_layout = QGridLayout(telemetry_box)
        self.telemetry_view = QPlainTextEdit()
        self.telemetry_view.setReadOnly(True)
        telemetry_layout.addWidget(self.telemetry_view, 0, 0)
        layout.addWidget(telemetry_box, 2, 0)

        # Лог-журнал
        log_box = QGroupBox("Журнал изменений")
        log_layout = QGridLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view, 0, 0)
        layout.addWidget(log_box, 3, 0)

    def _setup_actions(self) -> None:
        self.grid_combo.currentIndexChanged.connect(self._on_grid_selected)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        self.pause_button.clicked.connect(self._toggle_pause)

        pause_action = QAction("Пауза", self)
        pause_action.setShortcut("Ctrl+P")
        pause_action.triggered.connect(self._toggle_pause)
        self.addAction(pause_action)

    # ------------------------------------------------------------------
    def _initialize_connection(self) -> None:
        try:
            grid = prepare_grid()
            self._grid = grid
            self._client = grid.redis
            self._listener = TelemetryListener()
            self._listener.telemetry_received.connect(self._on_telemetry_update)
            self._listener.telemetry_deleted.connect(self._on_telemetry_deleted)
            self._listener.subscription_error.connect(self._show_error)

            self._owner_id = resolve_owner_id()
            self._player_id = resolve_player_id(self._owner_id)
            self._populate_grids()

            self.status_label.setText(
                "Подключено. Выберите устройство для просмотра телеметрии."
            )
        except Exception as exc:
            self._show_error(f"Не удалось инициализировать соединение: {exc}")

    def _populate_grids(self) -> None:
        if not self._client or not self._owner_id:
            return
        grids = self._client.list_grids(self._owner_id)
        self.grid_combo.blockSignals(True)
        self.grid_combo.clear()
        for grid in grids:
            grid_id = str(grid.get("id"))
            grid_name = grid.get("name") or grid.get("gridName") or grid_id
            label = f"{grid_name} ({grid_id})"
            self.grid_combo.addItem(label, userData=grid_id)
        self.grid_combo.blockSignals(False)

        if self.grid_combo.count() == 0:
            self.status_label.setText("Гриды не найдены. Проверьте настройки подключения.")
            return

        # Автовыбор грида, соответствующего текущему grid_id
        current_id = getattr(self._grid, "grid_id", None)
        if current_id:
            index = self.grid_combo.findData(str(current_id))
            if index >= 0:
                self.grid_combo.setCurrentIndex(index)
                return
        self.grid_combo.setCurrentIndex(0)

    # ------------------------------------------------------------------
    def _on_grid_selected(self, index: int) -> None:
        if index < 0:
            return
        grid_id = self.grid_combo.itemData(index)
        if not grid_id:
            return
        self._switch_grid(str(grid_id))

    def _switch_grid(self, grid_id: str) -> None:
        self._clear_device_state()
        if self._grid and self._grid.grid_id == grid_id:
            self._device_refresh_timer.start()
            self._refresh_devices()
            return

        if self._grid is not None:
            try:
                self._grid.close()
            except Exception:  # pragma: no cover - защитный код
                pass

        if not self._client or not self._owner_id or not self._player_id:
            return

        try:
            self._grid = Grid(self._client, self._owner_id, grid_id, self._player_id)
        except Exception as exc:  # pragma: no cover - подключение к Redis
            self._show_error(f"Не удалось подключиться к гриду {grid_id}: {exc}")
            return

        self._device_refresh_timer.start()
        self._refresh_devices()
        self.status_label.setText(f"Подписка на грид {grid_id} активна. Выберите устройство.")

    # ------------------------------------------------------------------
    def _refresh_devices(self) -> None:
        if not self._grid:
            return
        devices = list(self._grid.devices.values())
        print(f"Devices for grid {self._grid.grid_id}: {len(devices)} - {[d.name or d.device_type for d in devices]}")
        if not devices and not self.device_combo.count():
            return

        device_map: Dict[str, BaseDevice] = {}
        for device in devices:
            device_id = str(getattr(device, "device_id", "")) or getattr(device, "id", "")
            if not device_id:
                continue
            device_map[device_id] = device

        if set(device_map) == self._known_devices:
            return

        self._known_devices = set(device_map)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device_id, device in sorted(device_map.items(), key=lambda item: item[1].name or item[0]):
            device_name = device.name or f"{device.device_type}:{device_id}"
            label = f"{device_name} — #{device_id}"
            self.device_combo.addItem(label, userData=device_id)
        self.device_combo.blockSignals(False)

        is_available = self.device_combo.count() > 0
        self.device_combo.setEnabled(is_available)
        self.pause_button.setEnabled(is_available)

        if is_available and self.device_combo.currentIndex() < 0:
            self.device_combo.setCurrentIndex(0)

    # ------------------------------------------------------------------
    def _on_device_selected(self, index: int) -> None:
        if index < 0:
            return
        if not self._grid:
            return

        device_id = self.device_combo.itemData(index)
        if not device_id:
            return

        device = self._grid.get_device(device_id)
        if device is None:
            self._show_error("Не удалось найти устройство по выбранному идентификатору")
            return

        if self._listener is None:
            self._show_error("Подписчик телеметрии не инициализирован")
            return

        self._listener.subscribe(device)
        self._last_snapshot = getattr(device, "telemetry", None)
        self.telemetry_view.setPlainText(self._format_snapshot(self._last_snapshot))
        self.log_view.clear()
        self.status_label.setText(
            f"Подписка на устройство {device.name or device.device_type} (#{device.device_id})"
        )
        self._paused = False
        self.pause_button.setText("Пауза")

    def _toggle_pause(self) -> None:
        if self._listener is None:
            return
        self._paused = not self._paused
        if self._paused:
            self.pause_button.setText("Возобновить")
            self.status_label.setText("Отображение приостановлено")
        else:
            self.pause_button.setText("Пауза")
            self.status_label.setText("Отображение возобновлено")
            if self._pending_snapshot is not None:
                payload, event = self._pending_snapshot
                self._pending_snapshot = None
                if payload is None:
                    self._on_telemetry_deleted(event)
                else:
                    self._apply_snapshot(payload, event)

    # ------------------------------------------------------------------
    def _on_telemetry_update(self, payload: dict[str, Any], event: str) -> None:
        if self._paused:
            self._pending_snapshot = (payload, event)
            return
        self._apply_snapshot(payload, event)

    def _apply_snapshot(self, payload: dict[str, Any], event: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        changes = self._calculate_changes(self._last_snapshot or {}, payload)
        self.telemetry_view.setPlainText(self._format_snapshot(payload))

        for change in changes:
            entry = f"{timestamp} ({event}) → {change}"
            self._append_log(entry)
            LOGGER.info("%s", entry)

        if not changes:
            entry = f"{timestamp} ({event}) — изменений нет"
            self._append_log(entry)
            LOGGER.info("%s", entry)

        self._last_snapshot = payload

    def _on_telemetry_deleted(self, event: str) -> None:
        if self._paused:
            self._pending_snapshot = (None, event)
            return
        self.telemetry_view.clear()
        message = f"{datetime.now().strftime('%H:%M:%S')} ({event}) — телеметрия удалена"
        self._append_log(message)
        LOGGER.warning("%s", message)
        self._last_snapshot = None

    # ------------------------------------------------------------------
    def _calculate_changes(
        self, previous: dict[str, Any], current: dict[str, Any]
    ) -> list[str]:
        changes = []
        keys = sorted({*previous.keys(), *current.keys()})
        for key in keys:
            old = previous.get(key, "<нет>")
            new = current.get(key, "<нет>")
            if old != new:
                changes.append(f"{key}: {old!r} → {new!r}")
        return changes

    def _calculate_diff(
        self, previous: dict[str, Any], current: dict[str, Any]
    ) -> str:
        changes = self._calculate_changes(previous, current)
        return "; ".join(changes)

    def _format_snapshot(self, payload: Optional[dict[str, Any]]) -> str:
        if not payload:
            return ""
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        except TypeError:
            return str(payload)

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)

    def _clear_device_state(self) -> None:
        self._device_refresh_timer.stop()
        if self._listener is not None:
            self._listener.unsubscribe()
        self._known_devices.clear()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.blockSignals(False)
        self.device_combo.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.telemetry_view.clear()
        self.log_view.clear()
        self._last_snapshot = None
        self._pending_snapshot = None
        self._paused = False
        self.pause_button.setText("Пауза")

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Ошибка", message)
        LOGGER.error("%s", message)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._device_refresh_timer.stop()
        if self._listener is not None:
            self._listener.unsubscribe()
        if self._grid:
            close(self._grid)
            self._grid = None
            self._client = None
        elif self._client:
            try:
                self._client.close()
            except Exception:  # pragma: no cover - защитный код
                pass
        super().closeEvent(event)


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = TelemetryWindow()
    if window._client is None:
        # Соединение не удалось – окно неинициализировано
        return
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
