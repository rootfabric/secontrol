#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
device_load_monitor_gui.py

GUI for monitoring device CPU load aggregated by grids.

Displays CPU time spent by devices on each grid, sorted by load.

Takes values from existing project environment variables:
  - REDIS_URL — address Redis
  - REDIS_PORT — port Redis (overrides)
  - REDIS_DB — DB number (overrides)
  - REDIS_USERNAME — UID/username (also ownerId)
  - REDIS_PASSWORD — user password
  - REDIS_ADMIN_USERNAME — admin username for seeing all grids
  - REDIS_ADMIN_PASSWORD — admin password

Load from .env file if present.

Usage:
    python -m secontrol.tools.device_load_monitor_gui
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import redis

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from dotenv import load_dotenv, find_dotenv
from urllib.parse import urlparse, urlunparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from secontrol.grids import Grid
from secontrol.redis_client import RedisEventClient

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


def _normalize_load_bucket(bucket_payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(bucket_payload, dict):
        return None

    bucket: Dict[str, Any] = {}
    for key in ("lastMs", "avgMs", "peakMs"):
        if key not in bucket_payload:
            continue
        value = bucket_payload.get(key)
        try:
            bucket[key] = float(value)
        except (TypeError, ValueError):
            continue

    samples = bucket_payload.get("samples")
    if samples is not None:
        try:
            bucket["samples"] = int(samples)
        except (TypeError, ValueError):
            pass

    return bucket or None


def _extract_spent_time(metrics: Dict[str, Any]) -> Optional[float]:
    candidates: list[Any] = []

    total_bucket = metrics.get("total")
    if isinstance(total_bucket, dict):
        candidates.extend(total_bucket.get(key) for key in ("avgMs", "lastMs", "peakMs"))

    update_bucket = metrics.get("update")
    if isinstance(update_bucket, dict):
        candidates.append(update_bucket.get("avgMs"))

    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_load_metrics(load_payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(load_payload, dict):
        return None

    metrics: Dict[str, Any] = {}
    window = load_payload.get("window")
    if window is not None:
        try:
            metrics["window"] = int(window)
        except (TypeError, ValueError):
            pass

    for bucket_name in ("update", "commands", "total"):
        bucket = _normalize_load_bucket(load_payload.get(bucket_name))
        if bucket:
            metrics[bucket_name] = bucket

    spent = _extract_spent_time(metrics)
    if spent is not None:
        metrics["spentMs"] = spent

    return metrics or None


def _load_metrics_from_telemetry(telemetry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(telemetry, dict):
        return None

    metrics = _normalize_load_metrics(telemetry.get("load"))
    if metrics is not None:
        return metrics

    spent_raw = telemetry.get("loadSpentMs")
    if spent_raw is not None:
        try:
            return {"spentMs": float(spent_raw)}
        except (TypeError, ValueError):
            return None

    return None


def _extract_grid_id(descriptor: Dict[str, Any]) -> Optional[str]:
    for key in ("grid_id", "gridId", "id", "GridId", "entity_id", "entityId"):
        value = descriptor.get(key)
        if value is None:
            continue
        return str(value)
    return None


def _extract_grid_name(grid_id: str, descriptor: Dict[str, Any], info: Dict[str, Any]) -> str:
    for source in (info, descriptor):
        if not isinstance(source, dict):
            continue
        for key in ("name", "gridName", "displayName", "DisplayName"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return f"Grid_{grid_id}"


def _aggregate_load(device_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, Any] = {
        "devices": len(device_rows),
        "spentMs": 0.0,
        "avgSpentMsPerDevice": 0.0,
        "total": {"avgMs": 0.0, "peakMs": 0.0},
        "update": {"avgMs": 0.0, "peakMs": 0.0},
        "commands": {"avgMs": 0.0, "peakMs": 0.0},
    }

    def _add(bucket: Dict[str, Any], key: str, value: Any) -> None:
        if value is None:
            return
        try:
            bucket[key] = float(bucket.get(key, 0.0)) + float(value)
        except (TypeError, ValueError):
            pass

    for row in device_rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue

        _add(totals, "spentMs", metrics.get("spentMs"))

        total_bucket = metrics.get("total")
        if isinstance(total_bucket, dict):
            _add(totals["total"], "avgMs", total_bucket.get("avgMs"))
            _add(totals["total"], "peakMs", total_bucket.get("peakMs"))

        update_bucket = metrics.get("update")
        if isinstance(update_bucket, dict):
            _add(totals["update"], "avgMs", update_bucket.get("avgMs"))
            _add(totals["update"], "peakMs", update_bucket.get("peakMs"))

        commands_bucket = metrics.get("commands")
        if isinstance(commands_bucket, dict):
            _add(totals["commands"], "avgMs", commands_bucket.get("avgMs"))
            _add(totals["commands"], "peakMs", commands_bucket.get("peakMs"))

    device_count = totals["devices"]
    if device_count:
        totals["avgSpentMsPerDevice"] = float(totals["spentMs"]) / int(device_count)

    return totals


class LoadDataCollector(QObject):
    """Collects device load data from all grids."""

    data_ready = Signal(list)  # List of grid dicts with aggregated load + device rows

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[RedisEventClient] = None

    def start(self) -> None:
        resolved_url, effective_db = _resolve_url_with_overrides()
        # Prefer admin credentials for full access, fallback to user.
        admin_username = os.getenv("REDIS_ADMIN_USERNAME")
        admin_password = os.getenv("REDIS_ADMIN_PASSWORD")

        if admin_username and admin_password:
            username = admin_username
            password = admin_password
        else:
            username = os.getenv("REDIS_USERNAME")
            password = os.getenv("REDIS_PASSWORD")

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

        try:
            self._client = RedisEventClient(url=resolved_url, **connection_kwargs)
        except Exception as e:
            QMessageBox.critical(None, "Connection Error", f"Failed to connect to Redis: {e}")
            return

    def _discover_owner_ids(self) -> List[str]:
        owner_ids: set[str] = set()

        for key in ("REDIS_USERNAME", "SE_OWNER_ID"):
            value = os.getenv(key)
            if value:
                owner_ids.add(value)

        if not self._client:
            return sorted(owner_ids)

        patterns = ("se:*:grids", "se:system:players:*:redis")
        for pattern in patterns:
            try:
                for key in self._client.client.scan_iter(match=pattern, count=1000):
                    if isinstance(key, bytes):
                        key = key.decode("utf-8", "replace")
                    parts = str(key).split(":")
                    if pattern == "se:*:grids":
                        if len(parts) >= 3 and parts[0] == "se" and parts[2] == "grids":
                            owner_ids.add(parts[1])
                    elif pattern == "se:system:players:*:redis":
                        if (
                            len(parts) >= 5
                            and parts[0] == "se"
                            and parts[1] == "system"
                            and parts[2] == "players"
                            and parts[4] == "redis"
                        ):
                            owner_ids.add(parts[3])
            except Exception:
                continue

        if not owner_ids:
            # Try with admin credentials
            admin_username = os.getenv("REDIS_ADMIN_USERNAME")
            admin_password = os.getenv("REDIS_ADMIN_PASSWORD")
            if admin_username and admin_password:
                resolved_url, _ = _resolve_url_with_overrides()
                try:
                    admin_connection_kwargs = {
                        "decode_responses": False,
                        "socket_keepalive": True,
                        "health_check_interval": 30,
                        "retry_on_timeout": True,
                        "socket_timeout": 5,
                    }
                    admin_connection_kwargs["username"] = admin_username
                    admin_connection_kwargs["password"] = admin_password
                    admin_client = redis.Redis.from_url(resolved_url, **admin_connection_kwargs)
                    patterns = ("se:*:grids", "se:system:players:*:redis")
                    for pattern in patterns:
                        try:
                            for key in admin_client.scan_iter(match=pattern, count=1000):
                                if isinstance(key, bytes):
                                    key = key.decode("utf-8", "replace")
                                parts = str(key).split(":")
                                if pattern == "se:*:grids":
                                    if len(parts) >= 3 and parts[0] == "se" and parts[2] == "grids":
                                        owner_ids.add(parts[1])
                                elif pattern == "se:system:players:*:redis":
                                    if (
                                        len(parts) >= 5
                                        and parts[0] == "se"
                                        and parts[1] == "system"
                                        and parts[2] == "players"
                                        and parts[4] == "redis"
                                    ):
                                        owner_ids.add(parts[3])
                        except Exception:
                            continue
                    admin_client.close()
                except Exception:
                    pass

        return sorted(owner_ids)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    def collect_once(self) -> None:
        """Collect data once and emit signal."""
        if not self._client:
            return

        start_time = time.time()
        try:
            owner_ids = self._discover_owner_ids()
            print(f"Discover owner_ids: {len(owner_ids)} in {time.time() - start_time:.2f}s")
            results: List[Dict[str, Any]] = []

            start_grids = time.time()
            total_grids = 0
            for owner_id in owner_ids:
                try:
                    descriptors = self._client.list_grids(owner_id, exclude_subgrids=True)
                    total_grids += len(descriptors)
                except Exception:
                    continue

                print(f"List grids for {len(owner_ids)} owners: {total_grids} grids in {time.time() - start_grids:.2f}s")
                for descriptor in descriptors:
                    start_grid = time.time()
                    grid_id = _extract_grid_id(descriptor)
                    if not grid_id:
                        continue
                    gridinfo_key = f"se:{owner_id}:grid:{grid_id}:gridinfo"
                    gridinfo = self._client.get_json(gridinfo_key)
                    gridinfo = gridinfo if isinstance(gridinfo, dict) else {}

                    grid_name = _extract_grid_name(grid_id, descriptor, gridinfo)
                    try:
                        grid = Grid(self._client, owner_id, grid_id, owner_id, grid_name)
                    except Exception:
                        continue

                    try:
                        device_rows: List[Dict[str, Any]] = []
                        for device in grid.devices.values():
                            metrics = device.load_metrics()
                            if metrics is None:
                                telemetry = device.telemetry
                                if not telemetry:
                                    telemetry = self._client.get_json(device.telemetry_key)
                                metrics = _load_metrics_from_telemetry(telemetry)

                            device_rows.append(
                                {
                                    "name": device.name or f"{device.device_type}:{device.device_id}",
                                    "device_id": device.device_id,
                                    "device_type": device.device_type or "unknown",
                                    "metrics": metrics,
                                }
                            )

                        device_rows.sort(
                            key=lambda row: float((row.get("metrics") or {}).get("spentMs", 0.0)),
                            reverse=True,
                        )

                        load_data = _aggregate_load(device_rows)
                        spent_ms = float(load_data.get("spentMs", 0.0))

                        results.append(
                            {
                                "grid_name": grid_name,
                                "grid_id": grid_id,
                                "owner_id": owner_id,
                                "device_count": len(device_rows),
                                "spent_ms": spent_ms,
                                "load_data": load_data,
                                "devices": device_rows,
                            }
                        )
                    finally:
                        print(f"Process grid {grid_name}: {time.time() - start_grid:.2f}s")
                        try:
                            grid.close()
                        except Exception:
                            pass

        except Exception:
            return

        results.sort(key=lambda row: row.get("spent_ms", 0.0), reverse=True)
        print(f"Total collect time: {time.time() - start_time:.2f}s")
        self.data_ready.emit(results)


class DeviceLoadMonitorWindow(QMainWindow):
    """Main GUI window for device load monitoring."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SE Device Load Monitor")
        self.resize(1000, 600)

        self._collector = LoadDataCollector()
        self._collector.data_ready.connect(self._on_data_received)

        self._build_ui()
        self._start_monitoring()

        # Initial collect in background
        import threading
        threading.Thread(target=self._initial_collect, daemon=True).start()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Header
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Device CPU Load by Grid"))
        header_layout.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._manual_refresh)
        header_layout.addWidget(self.refresh_button)
        layout.addLayout(header_layout)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels([
            "Grid / Device",
            "ID",
            "Devices / Type",
            "Total CPU (ms)",
            "Avg CPU/Device (ms)",
            "Update Avg (ms)",
            "Commands Avg (ms)",
            "Peak CPU (ms)",
        ])
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.tree.setSortingEnabled(False)
        layout.addWidget(self.tree)

        # Status
        self.status_label = QLabel("Monitoring device load...")
        layout.addWidget(self.status_label)

    def _start_monitoring(self) -> None:
        try:
            self._collector.start()
        except Exception as e:
            QMessageBox.critical(self, "Start Error", f"Failed to start monitoring: {e}")

    def _manual_refresh(self) -> None:
        self.status_label.setText("Refreshing...")
        self._collector.collect_once()

    def _initial_collect(self) -> None:
        try:
            self._collector.collect_once()
        except Exception:
            pass

    def _set_numeric_cell(self, item: QTreeWidgetItem, column: int, value: float) -> None:
        item.setText(column, f"{value:.2f}")
        item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
        item.setData(column, Qt.UserRole, float(value))

    def _on_data_received(self, data: List[Dict[str, Any]]) -> None:
        self.tree.clear()

        total_devices = 0
        multiple_owners = len({row.get("owner_id") for row in data if row.get("owner_id")}) > 1

        for row in data:
            name = row.get("grid_name") or "Unknown Grid"
            grid_id = str(row.get("grid_id") or "")
            owner_id = row.get("owner_id") or ""
            device_count = int(row.get("device_count") or 0)
            total_devices += device_count

            load_data = row.get("load_data") or {}
            spent_ms = float(load_data.get("spentMs", 0.0))
            avg_spent = float(load_data.get("avgSpentMsPerDevice", 0.0))
            update_avg = float(load_data.get("update", {}).get("avgMs", 0.0))
            commands_avg = float(load_data.get("commands", {}).get("avgMs", 0.0))
            total_peak = float(load_data.get("total", {}).get("peakMs", 0.0))

            grid_item = QTreeWidgetItem(self.tree, [
                name,
                grid_id,
                str(device_count),
                f"{spent_ms:.2f}",
                f"{avg_spent:.2f}",
                f"{update_avg:.2f}",
                f"{commands_avg:.2f}",
                f"{total_peak:.2f}",
            ])

            if multiple_owners and owner_id:
                grid_item.setToolTip(0, f"Owner: {owner_id}")

            grid_item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            self._set_numeric_cell(grid_item, 3, spent_ms)
            self._set_numeric_cell(grid_item, 4, avg_spent)
            self._set_numeric_cell(grid_item, 5, update_avg)
            self._set_numeric_cell(grid_item, 6, commands_avg)
            self._set_numeric_cell(grid_item, 7, total_peak)

            for device in row.get("devices", []):
                metrics = device.get("metrics") or {}
                dev_spent = float(metrics.get("spentMs", 0.0))
                dev_total_avg = float(metrics.get("total", {}).get("avgMs", 0.0))
                dev_update_avg = float(metrics.get("update", {}).get("avgMs", 0.0))
                dev_commands_avg = float(metrics.get("commands", {}).get("avgMs", 0.0))
                dev_peak = float(metrics.get("total", {}).get("peakMs", 0.0))

                dev_item = QTreeWidgetItem(grid_item, [
                    device.get("name") or "Unknown Device",
                    str(device.get("device_id") or ""),
                    str(device.get("device_type") or ""),
                    f"{dev_spent:.2f}",
                    f"{dev_total_avg:.2f}",
                    f"{dev_update_avg:.2f}",
                    f"{dev_commands_avg:.2f}",
                    f"{dev_peak:.2f}",
                ])
                dev_item.setTextAlignment(2, Qt.AlignLeft | Qt.AlignVCenter)
                self._set_numeric_cell(dev_item, 3, dev_spent)
                self._set_numeric_cell(dev_item, 4, dev_total_avg)
                self._set_numeric_cell(dev_item, 5, dev_update_avg)
                self._set_numeric_cell(dev_item, 6, dev_commands_avg)
                self._set_numeric_cell(dev_item, 7, dev_peak)

        self.tree.expandAll()
        self.status_label.setText(
            f"Last update: {len(data)} grids, {total_devices} devices"
        )

    def closeEvent(self, event) -> None:
        self._collector.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = DeviceLoadMonitorWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
