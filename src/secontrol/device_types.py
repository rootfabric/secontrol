"""Compatibility wrapper for legacy imports."""

from __future__ import annotations

from .devices import load_builtin_devices, load_external_plugins

load_builtin_devices()
load_external_plugins()
