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

Ready-made scripts are located in the [`examples/organized`](examples/organized) directory, organized by device type and complexity level:

- `basic/` - Basic examples for getting started
  - `basic/` - Simple introductory examples
  - `intermediate/` - Moderately complex examples
  - `advanced/` - Complex examples with advanced features

- `lamp/` - Examples for controlling lamp devices
  - `basic/` - Simple lamp control examples
  - `intermediate/` - More complex lamp automation
  - `advanced/` - Advanced lamp control with complex logic

- `container/` - Examples for managing container devices
  - `basic/` - Simple container operations
  - `intermediate/` - Container inventory management
  - `advanced/` - Complex inventory tracking and transfers

- `assembler/` - Examples for controlling assembler devices
  - `basic/` - Simple production commands
  - `intermediate/` - Queue management and monitoring
  - `advanced/` - Complex production workflows

- `rover/` - Examples for controlling rover devices
  - `basic/` - Simple rover movement
  - `intermediate/` - Wheel control and steering
  - `advanced/` - Complex rover automation

- `display/` - Examples for controlling display devices
  - `basic/` - Simple display content
  - `intermediate/` - Dynamic content updates
  - `advanced/` - Complex graphics and animations

- `grid/` - Examples for grid-level operations
  - `basic/` - Grid information and listings
  - `intermediate/` - Grid resource management
  - `advanced/` - Grid damage tracking and advanced operations

- `ai/` - Examples for AI automation
  - `basic/` - Simple AI tasks
  - `intermediate/` - AI behavior control
  - `advanced/` - Complex AI automation

- `refinery/` - Examples for controlling refinery devices
  - `basic/` - Simple refinery operations
  - `intermediate/` - Priority and queue management
  - `advanced/` - Complex refinement workflows

- `radar/` - Examples for radar and detection devices
  - `basic/` - Simple detection
  - `intermediate/` - Radar telemetry processing
  - `advanced/` - Complex detection and visualization

- `inventory/` - Examples for inventory management
  - `basic/` - Simple inventory operations
  - `intermediate/` - Inventory tracking
  - `advanced/` - Complex inventory automation and transfers

To run an example:

## Wiki
https://github.com/rootfabric/secontrol/wiki/home

## License

The project is distributed under the MIT license. See the [LICENSE](LICENSE) file.
