"""Merge block device implementation for Space Engineers grid control."""

from __future__ import annotations

from secontrol.base_device import BaseDevice, DEVICE_TYPE_MAP


class MergeBlockDevice(BaseDevice):
    """Wrapper for ship merge blocks.

    Merge blocks do not need a separate lock API in Space Engineers: once the
    two merge faces touch and the block is powered, the game creates the merge
    constraint automatically.  Therefore ``connect``/``lock`` are power-on
    aliases and ``disconnect``/``unlock`` are power-off aliases.
    """

    device_type = "merge_block"

    def connect(self) -> int:
        """Enable the merge block so it can mate with the opposite block."""
        return self.enable()

    def disconnect(self) -> int:
        """Disable the merge block so the merged grid can detach."""
        return self.disable()

    def lock(self) -> int:
        """Alias for ``connect()``."""
        return self.connect()

    def unlock(self) -> int:
        """Alias for ``disconnect()``."""
        return self.disconnect()


DEVICE_TYPE_MAP[MergeBlockDevice.device_type] = MergeBlockDevice
DEVICE_TYPE_MAP["mergeblock"] = MergeBlockDevice
DEVICE_TYPE_MAP["shipmergeblock"] = MergeBlockDevice
