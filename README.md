# secontrol

`secontrol` is a high-level client for interacting with the Space Engineers Redis gateway. The library simplifies obtaining telemetry, sending commands, and implementing automations using persistent subscriptions to key events.

## Features

- Connecting to Redis using configuration from `.env` or constructor arguments.
- Monitoring keys and channels with automatic subscription recovery.
- Utilities for obtaining owner, player, and grid identifiers.
- Examples demonstrating command publishing and state monitoring.

## Installation

```bash
pip install secontrol
```

## Quick Start

```python
from secontrol.common import prepare_grid

# First player's grid
grid = prepare_grid()
# Devices on the grid
print(", ".join((d.name or f"{d.device_type}:{d.device_id}") for d in grid.devices.values()) or "(no devices)")

```

### Environment Variables

| Variable         | Purpose                                               |
| ---------------- | ----------------------------------------------------- |
| `REDIS_USERNAME` | Username for authorization.                           |
| `REDIS_PASSWORD` | Password for connection.                              |

Variables can be defined in the `.env` file in the project or system root.
Variable values must be obtained in the personal account on the page https://www.outenemy.ru/se/

## Examples

Ready-made scripts are located in the [`examples`](examples) directory. To run an example:

## Wiki
https://github.com/rootfabric/secontrol/wiki/home

## License

The project is distributed under the MIT license. See the [LICENSE](LICENSE) file.
