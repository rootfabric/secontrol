#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
telemetry_reader_gui.py

GUI for monitoring Space Engineers Redis bridge telemetry data.

Displays structured telemetry data that updates in real-time without UI jumping.

Takes values from existing project environment variables:
  - REDIS_URL — address Redis
  - REDIS_PORT — port Redis (overrides)
  - REDIS_DB — DB number (overrides)
  - REDIS_USERNAME — UID/username
  - REDIS_PASSWORD — user password

Load from .env file if present.

Usage:
    python -m secontrol.tools.telemetry_reader_gui
"""

from __future__ import annotations

import json
import os
import threading
import sys
from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import redis
from dotenv import load_dotenv, find_dotenv
from urllib.parse import urlparse, urlunparse


load_dotenv(find_dotenv(usecwd=True), override=False)


def _resolve_url_with_overrides() -> tuple[str, int]:
    """Returns (resolved_url, effective_db)."""
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    port_env = os.getenv("REDIS_PORT")
    db_env = os.getenv("REDIS_DB")

    pu = urlparse(url)

    # Port override
    try:
        if port_env is not None:
            port_val = int(port_env)
            if port_val > 0:
                netloc = pu.hostname or "127.0.0.1"
                if pu.username and pu.password:
                    auth = f"{pu.username}:{pu.password}@"
                elif pu.username:
                    auth = f"{pu.username}@"
                else:
                    auth = ""
                url = urlunparse((pu.scheme, f"{auth}{netloc}:{port_val}", pu.path, pu.params, pu.query, pu.fragment))
                pu = urlparse(url)
    except (TypeError, ValueError):
        pass

    # DB override
    effective_db = None
    try:
        if db_env is not None:
            db_val = int(db_env)
            if db_val >= 0:
                effective_db = db_val
                url = urlunparse((pu.scheme, pu.netloc, f"/{db_val}", pu.params, pu.query, pu.fragment))
                pu = urlparse(url)
    except (TypeError, ValueError):
        pass

    # If DB not set, take from URL
    if effective_db is None:
        try:
            path = pu.path.lstrip("/")
            effective_db = int(path) if path else 0
        except (TypeError, ValueError):
            effective_db = 0

    return url, effective_db


class TelemetryReceiver(QObject):
    """Handles Redis pubsub subscription in background thread."""

    data_received = Signal(str, dict)  # channel, payload

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self._thread: threading.Thread | None = None
        self._client: redis.Redis | None = None

    def start(self) -> None:
        resolved_url, effective_db = _resolve_url_with_overrides()
        username = os.getenv("REDIS_ADMIN_USERNAME")
        password = os.getenv("REDIS_ADMIN_PASSWORD")

        connection_kwargs = {
            "decode_responses": False,
            "socket_keepalive": True,
            "health_check_interval": 30,
            "retry_on_timeout": True,
            "socket_timeout": 5,
        }
        if username:
            connection_kwargs["username"] = username
        if password:
            connection_kwargs["password"] = password

        self._client = redis.Redis.from_url(resolved_url, **connection_kwargs)

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    def _run(self) -> None:
        if not self._client:
            return

        patterns = [
            # "se.telemetry.*",
            "se.system.status",
            "se.system.load",
        ]

        try:
            pubsub = self._client.pubsub(ignore_subscribe_messages=True)
            pubsub.psubscribe(*patterns)

            while self._running:
                message = pubsub.get_message(timeout=1.0)
                if message and message['type'] == 'pmessage':
                    channel_bytes = message.get('channel')
                    data_bytes = message.get('data')

                    if channel_bytes and data_bytes:
                        try:
                            channel = channel_bytes.decode('utf-8')
                            data_str = data_bytes.decode('utf-8')
                            payload = json.loads(data_str)
                            self.data_received.emit(channel, payload)
                        except Exception:
                            pass  # Skip invalid messages
        except Exception:
            pass
        finally:
            try:
                pubsub.close()
            except Exception:
                pass


class TelemetryWindow(QMainWindow):
    """Main GUI window for telemetry monitoring."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SE Telemetry Monitor")
        self.resize(1200, 800)

        self._receiver = TelemetryReceiver()
        self._receiver.data_received.connect(self._on_data_received)

        # Store latest data per channel
        self._latest_data: dict[str, dict] = {}
        # Pending payload for batched UI update
        self._pending_channel: Optional[str] = None
        self._pending_payload: Optional[dict] = None
        # Debounce timer for fast updates
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setInterval(100)  # ms
        self._debounce_timer.timeout.connect(self._flush_pending_telemetry)

        self._build_ui()
        self._start_monitoring()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # System load tab
        self.load_tab = QWidget()
        self.tabs.addTab(self.load_tab, "System Load")
        self._build_load_ui()

        # System status tab
        self.status_tab = QWidget()
        self.tabs.addTab(self.status_tab, "System Status")
        self._build_status_ui()

        # General telemetry tab
        self.telemetry_tab = QWidget()
        self.tabs.addTab(self.telemetry_tab, "Telemetry")
        self._build_telemetry_ui()

        # Status bar
        self.status_label = QLabel("Monitoring telemetry...")
        layout.addWidget(self.status_label)

    def _build_load_ui(self) -> None:
        layout = QVBoxLayout(self.load_tab)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        grid = QVBoxLayout(content)

        # Timestamp
        timestamp_box = QGroupBox("Last Update")
        ts_layout = QHBoxLayout(timestamp_box)
        self.load_timestamp = QLabel("(no data)")
        ts_layout.addWidget(QLabel("Time:"))
        ts_layout.addWidget(self.load_timestamp)
        grid.addWidget(timestamp_box)

        # Config section
        self.config_box = QGroupBox("Config")
        self.config_layout = QVBoxLayout(self.config_box)
        self.config_labels: dict[str, QLineEdit] = {}
        grid.addWidget(self.config_box)

        # Outgoing section
        self.outgoing_box = QGroupBox("Outgoing")
        self.outgoing_layout = QVBoxLayout(self.outgoing_box)
        self.outgoing_labels: dict[str, QLineEdit] = {}
        grid.addWidget(self.outgoing_box)

        # Incoming section
        self.incoming_box = QGroupBox("Incoming")
        self.incoming_layout = QVBoxLayout(self.incoming_box)
        self.incoming_labels: dict[str, QLineEdit] = {}
        grid.addWidget(self.incoming_box)

    def _build_status_ui(self) -> None:
        layout = QVBoxLayout(self.status_tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        grid = QVBoxLayout(content)
        self.status_timestamp = QLabel("Last Update: (no data)")
        grid.addWidget(self.status_timestamp)

        self.status_data_label = QLabel("(no data)")
        self.status_data_label.setWordWrap(True)
        grid.addWidget(self.status_data_label)

    def _build_telemetry_ui(self) -> None:
        layout = QVBoxLayout(self.telemetry_tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        grid = QVBoxLayout(content)
        self.telemetry_timestamp = QLabel("Last Update: (no data)")
        grid.addWidget(self.telemetry_timestamp)

        self.telemetry_channel = QLabel("Channel: (none)")
        grid.addWidget(self.telemetry_channel)

        # Structured, stable view for telemetry payload
        self.telemetry_inner = QWidget()
        grid.addWidget(self.telemetry_inner)

        self.telemetry_root_layout = QVBoxLayout(self.telemetry_inner)

        # Group for top-level scalar values (non-dict/non-list)
        self.telemetry_scalars_box = QGroupBox("Scalars")
        self.telemetry_scalars_layout = QVBoxLayout(self.telemetry_scalars_box)
        self.telemetry_root_layout.addWidget(self.telemetry_scalars_box)

        # Maps for dynamic widgets to update without rebuilding
        self._telemetry_scalar_fields: dict[str, QLineEdit] = {}
        self._telemetry_group_boxes: dict[str, QGroupBox] = {}
        self._telemetry_group_layouts: dict[str, QVBoxLayout] = {}
        self._telemetry_value_fields: dict[str, QLineEdit] = {}
        self._current_telemetry_channel: Optional[str] = None



    def _start_monitoring(self) -> None:
        try:
            self._receiver.start()
            self._debounce_timer.start()
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to start monitoring: {e}")

    def _on_data_received(self, channel: str, payload: dict) -> None:
        """Handle incoming telemetry data."""
        self._latest_data[channel] = payload
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

        if channel == "se.system.load":
            self._update_load_data(payload, timestamp)
            self.tabs.setCurrentIndex(0)  # Show load tab

        elif channel == "se.system.status":
            self._update_status_data(payload, timestamp)
            self.tabs.setCurrentIndex(1)  # Show status tab

        elif channel.startswith("se.telemetry."):
            # Buffer telemetry and update UI on debounce to avoid flicker
            self._pending_channel = channel
            self._pending_payload = payload
            self.tabs.setCurrentIndex(2)  # Show telemetry tab

        self.status_label.setText(f"[{timestamp}] Received: {channel}")

    def _update_load_data(self, payload: dict, timestamp: str) -> None:
        """Update load data fields."""
        self.load_timestamp.setText(timestamp)

        # Config section
        config = payload.get("config", {})
        for key in sorted(config.keys()):
            value = config[key]
            if key not in self.config_labels:
                hlayout = QHBoxLayout()
                label = QLabel(f"{key}:")
                label.setFixedWidth(200)
                value_edit = QLineEdit(self._format_value(value))
                value_edit.setFixedWidth(200)
                value_edit.setReadOnly(True)
                hlayout.addWidget(label)
                hlayout.addWidget(value_edit)
                hlayout.addStretch()
                self.config_layout.addLayout(hlayout)
                self.config_labels[key] = value_edit
            else:
                self.config_labels[key].setText(self._format_value(value))

        # Outgoing section
        outgoing = payload.get("outgoing", {})
        for key in sorted(outgoing.keys()):
            value = outgoing[key]
            if key not in self.outgoing_labels:
                hlayout = QHBoxLayout()
                label = QLabel(f"{key}:")
                label.setFixedWidth(200)
                value_edit = QLineEdit(self._format_value(value))
                value_edit.setFixedWidth(200)
                value_edit.setReadOnly(True)
                hlayout.addWidget(label)
                hlayout.addWidget(value_edit)
                hlayout.addStretch()
                self.outgoing_layout.addLayout(hlayout)
                self.outgoing_labels[key] = value_edit
            else:
                self.outgoing_labels[key].setText(self._format_value(value))

        # Incoming section
        incoming = payload.get("incoming", {})
        for key in sorted(incoming.keys()):
            value = incoming[key]
            if key not in self.incoming_labels:
                hlayout = QHBoxLayout()
                label = QLabel(f"{key}:")
                label.setFixedWidth(200)
                value_edit = QLineEdit(self._format_value(value))
                value_edit.setFixedWidth(200)
                value_edit.setReadOnly(True)
                hlayout.addWidget(label)
                hlayout.addWidget(value_edit)
                hlayout.addStretch()
                self.incoming_layout.addLayout(hlayout)
                self.incoming_labels[key] = value_edit
            else:
                self.incoming_labels[key].setText(self._format_value(value))

    def _update_status_data(self, payload: dict, timestamp: str) -> None:
        """Update status data display."""
        self.status_timestamp.setText(f"Last Update: {timestamp}")
        try:
            formatted = json.dumps(payload, ensure_ascii=False, indent=2)
            self.status_data_label.setText(formatted)
        except:
            self.status_data_label.setText(str(payload))

    def _flush_pending_telemetry(self) -> None:
        if not self._pending_channel:
            return
        channel = self._pending_channel
        payload = self._pending_payload or {}
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self._update_telemetry_data(channel, payload, timestamp)
        # Keep last rendered state; do not clear pending to allow coalescing

    def _update_telemetry_data(self, channel: str, payload: dict, timestamp: str) -> None:
        """Update telemetry data display with stable, sorted sections."""
        self.telemetry_timestamp.setText(f"Last Update: {timestamp}")
        if channel != self._current_telemetry_channel:
            self._reset_telemetry_view()
            self._current_telemetry_channel = channel
        self.telemetry_channel.setText(f"Channel: {channel}")

        if not isinstance(payload, dict):
            # Fallback: show as a single scalar value
            value = self._format_value(payload)
            field = self._ensure_scalar_field("payload")
            field.setText(value)
            return

        # Track seen paths this update to enable optional pruning if needed later
        # Path keys are dot-joined strings for readability
        seen_paths: set[str] = set()

        # First, handle top-level scalars to keep them grouped
        for key in sorted(payload.keys(), key=lambda k: str(k)):
            value = payload.get(key)
            if not isinstance(value, (dict, list)):
                path = key
                seen_paths.add(path)
                field = self._ensure_scalar_field(key)
                self._set_text_if_changed(field, self._format_value(value))

        # Then, handle dicts and lists as grouped sections
        for key in sorted(payload.keys(), key=lambda k: str(k)):
            value = payload.get(key)
            if isinstance(value, dict):
                self._update_group_dict(parent_path="", key=key, data=value, seen=seen_paths)
            elif isinstance(value, list):
                self._update_group_list(parent_path="", key=key, data=value, seen=seen_paths)

        # We intentionally avoid pruning removed fields to reduce flicker.
        # Optionally, could hide or remove widgets not in seen_paths.

    def _reset_telemetry_view(self) -> None:
        """Clear dynamic telemetry widgets for a new channel."""
        # Clear scalar fields
        for field in self._telemetry_scalar_fields.values():
            field.deleteLater()
        self._telemetry_scalar_fields.clear()

        # Remove all group boxes from the root layout
        for box in self._telemetry_group_boxes.values():
            box.setParent(None)
            box.deleteLater()
        self._telemetry_group_boxes.clear()
        self._telemetry_group_layouts.clear()

        # Clear nested value fields
        for field in self._telemetry_value_fields.values():
            field.deleteLater()
        self._telemetry_value_fields.clear()

        # Ensure Scalars box is visible and empty layout
        # Remove all layouts inside scalars layout
        while self.telemetry_scalars_layout.count():
            item = self.telemetry_scalars_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _ensure_scalar_field(self, key: str) -> QLineEdit:
        """Ensure a scalar row exists under the Scalars box for the given top-level key."""
        if key in self._telemetry_scalar_fields:
            return self._telemetry_scalar_fields[key]

        hlayout = QHBoxLayout()
        label = QLabel(f"{key}:")
        label.setFixedWidth(240)
        value_edit = QLineEdit()
        value_edit.setReadOnly(True)
        value_edit.setFixedWidth(320)
        hlayout.addWidget(label)
        hlayout.addWidget(value_edit)
        hlayout.addStretch()
        self.telemetry_scalars_layout.addLayout(hlayout)
        self._telemetry_scalar_fields[key] = value_edit
        return value_edit

    def _ensure_group(self, path: str, title: str) -> QVBoxLayout:
        """Ensure a group box exists for the given path and return its layout."""
        if path in self._telemetry_group_layouts:
            return self._telemetry_group_layouts[path]

        box = QGroupBox(title)
        vlayout = QVBoxLayout(box)
        self.telemetry_root_layout.addWidget(box)
        self._telemetry_group_boxes[path] = box
        self._telemetry_group_layouts[path] = vlayout
        return vlayout

    def _ensure_value_field(self, path: str, key: str, parent_layout: QVBoxLayout) -> QLineEdit:
        """Ensure a labeled read-only field exists under the given parent layout."""
        full_path = f"{path}.{key}" if path else key
        if full_path in self._telemetry_value_fields:
            return self._telemetry_value_fields[full_path]

        hlayout = QHBoxLayout()
        label = QLabel(f"{key}:")
        label.setFixedWidth(240)
        value_edit = QLineEdit()
        value_edit.setReadOnly(True)
        value_edit.setFixedWidth(520)
        hlayout.addWidget(label)
        hlayout.addWidget(value_edit)
        hlayout.addStretch()
        parent_layout.addLayout(hlayout)
        self._telemetry_value_fields[full_path] = value_edit
        return value_edit

    def _update_group_dict(self, parent_path: str, key: str, data: dict, seen: set[str]) -> None:
        """Update or create a group for a nested dict, and its sorted entries."""
        path = f"{parent_path}.{key}" if parent_path else key
        seen.add(path)
        layout = self._ensure_group(path, key)

        # Render fields sorted by key; recurse for nested dicts/lists
        for sub_key in sorted(data.keys(), key=lambda k: str(k)):
            value = data.get(sub_key)
            sub_path = f"{path}.{sub_key}"
            seen.add(sub_path)
            if isinstance(value, dict):
                self._update_group_dict(path, sub_key, value, seen)
            elif isinstance(value, list):
                self._update_group_list(path, sub_key, value, seen)
            else:
                field = self._ensure_value_field(path, sub_key, layout)
                self._set_text_if_changed(field, self._format_value(value))

    def _update_group_list(self, parent_path: str, key: str, data: list, seen: set[str]) -> None:
        """Update or create a group for a list, rendering items with stable indices."""
        path = f"{parent_path}.{key}" if parent_path else key
        seen.add(path)
        layout = self._ensure_group(path, f"{key} [list]")

        # Show items as index: value; for nested dict/list recurse
        MAX_ITEMS = 50
        total = len(data)
        display_count = min(total, MAX_ITEMS)
        for idx, item in enumerate(data[:display_count]):
            item_key = f"[{idx}]"
            sub_path = f"{path}.{item_key}"
            seen.add(sub_path)
            if isinstance(item, dict):
                # Use a synthetic key like [0], [1] for nested groups
                self._update_group_dict(path, item_key, item, seen)
            elif isinstance(item, list):
                self._update_group_list(path, item_key, item, seen)
            else:
                field = self._ensure_value_field(path, item_key, layout)
                self._set_text_if_changed(field, self._format_value(item))
        if total > display_count:
            # Add a summary label about hidden items
            summary_key = f"... and {total - display_count} more"
            field = self._ensure_value_field(path, summary_key, layout)
            self._set_text_if_changed(field, "")

    def _set_text_if_changed(self, widget: QLineEdit, text: str) -> None:
        if widget.text() != text:
            widget.setText(text)

    def _format_value(self, value: Any) -> str:
        """Format value for display."""
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    def closeEvent(self, event) -> None:
        self._receiver.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = TelemetryWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
