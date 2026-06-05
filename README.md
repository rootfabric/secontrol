# Space Engineers AI Robotics

Space Engineers AI Robotics (`secontrol`) is an open-source research project for building autonomous AI agents that can live and operate inside a complex simulated world.

The repository provides a Python control library, examples, workflows, and documentation for interacting with the Space Engineers Redis gateway. It is designed to collect telemetry, send commands, automate devices, and evolve scripted behaviors into long-running AI agents.

Public entry point: <https://www.outenemy.ru/se/>

## Status

This project is in active early-stage development. Several low-level and mid-level automation workflows already work, including telemetry, navigation experiments, docking, production, refinery control, inventory logistics, radar scanning, projector workflows, and early mission loops.

The long-term goal is full long-running autonomy, not a single scripted mission.

## Project goal

The goal of this project is to create an open-source platform for developing AI agents that can live and operate inside a complex simulated world.

Space Engineers provides a physics-based sandbox environment with construction, resource extraction, navigation, logistics, damage, energy management, tools, vehicles, bases, players, and other agents. This makes it a useful testbed for long-running autonomous AI behavior.

The final goal is to build an AI agent that can independently survive, build, mine, repair, navigate, cooperate, and make decisions in a persistent world shared with humans and other AI agents.

This project is not intended to be only a game bot. It is an experimental autonomy stack where agents learn to observe world state, use tools, gather resources, build infrastructure, recover from failures, and operate over long time horizons.

## Current capabilities

The project already includes a set of tools and experiments for controlling autonomous agents inside Space Engineers.

Implemented or partially implemented capabilities:

- Telemetry collection from grids, blocks, inventories, connectors, projectors, assemblers, refineries, batteries, thrusters, gyroscopes, remote controls, ore detectors, and other devices.
- Python control scripts for autonomous ships and bases.
- Navigation experiments for moving ships between points and asteroids.
- Docking and parking workflows using connectors.
- Resource logistics: checking inventories, moving resources, maintaining components, and operating assemblers.
- Refinery and assembler automation.
- Blueprint and projector automation for construction workflows.
- Radar, ore scanning, and shared-map experiments for world awareness.
- Early mission scenarios for mining, returning to base, docking, producing components, and supporting base operations.
- Debugging and verification scripts for agent behavior.
- Documentation for operators, administrators, and developers.

The current agents can already perform parts of autonomous behavior, but full independent life inside the world is still an open research and engineering challenge.

## Architecture

The project is organized as a layered autonomy stack.

### 1. Simulation layer

Space Engineers is used as the simulated world. It provides physics, grids, ships, bases, resources, tools, construction, damage, power systems, and multiplayer interaction.

### 2. Telemetry layer

A dedicated integration layer collects information from the game world: block states, inventories, positions, velocities, connector status, production queues, projector status, resource availability, and ship/base systems.

### 3. Device control layer

Python tools and scripts operate individual devices and systems: remote controls, thrusters, gyroscopes, connectors, assemblers, refineries, projectors, cargo containers, drills, welders, batteries, displays, lamps, and radars.

### 4. Behavior layer

Higher-level scripts combine device commands into useful behaviors: navigation, docking, mining, production, construction, resource management, scanning, and base maintenance.

### 5. Agent layer

The long-term goal is to connect LLM-based agents to these tools, allowing them to plan, execute, observe results, debug failures, and improve their behavior over time.

### 6. Evaluation layer

The project aims to create repeatable scenarios for measuring progress: reaching a target, docking, mining resources, producing components, repairing structures, building from blueprints, and surviving for long periods.

## Roadmap

### Short-term goals

- Improve reliability of navigation and docking.
- Add better obstacle detection and collision avoidance.
- Make production scripts aware of existing inventories and queued assembler jobs.
- Improve resource logistics between base, ship, refinery, assembler, and cargo.
- Add more tests and validation scripts for critical behaviors.
- Document all tools and workflows.

### Mid-term goals

- Build complete mission loops:
  - mine resources;
  - return to base;
  - dock safely;
  - unload cargo;
  - process ore;
  - produce missing components;
  - repair or build required structures.
- Add a higher-level task planner that can select tools based on goals and world state.
- Create reusable scenarios for agent evaluation.
- Improve failure recovery when a ship is stuck, out of fuel, misaligned, damaged, or missing components.

### Long-term goals

- Create agents that can survive and operate continuously in a persistent world.
- Enable cooperation between multiple AI agents.
- Support interaction with human players.
- Allow agents to build, repair, expand bases, explore, mine, and defend themselves.
- Develop an open benchmark for embodied/autonomous AI in a complex sandbox simulation.

The final milestone is not a single scripted mission, but a long-running autonomous agent that can observe the world, form goals, use tools, recover from failures, and continue operating without direct human control.

## Why this matters for AI agents

Most AI coding and agent benchmarks are short-lived and text-based. This project explores a harder problem: an AI agent acting in a persistent, partially observable, physics-based world.

The agent must deal with:

- incomplete and changing information;
- physical movement;
- navigation errors;
- collisions and damage;
- resource scarcity;
- power limitations;
- construction dependencies;
- tool usage;
- multi-step planning;
- long-running missions;
- cooperation with other agents and human players;
- recovery from unexpected failures.

This creates a useful environment for developing and evaluating AI systems that need more than language understanding. They must connect reasoning with tools, memory, perception, planning, and action.

A successful agent in this environment must not only generate code or answer questions. It must keep itself alive, understand its tools, maintain infrastructure, adapt to failures, and act over long time horizons.

## Evaluation scenarios

The project aims to define repeatable scenarios for measuring autonomous agent progress:

- inspect grid state and report missing systems;
- undock from a base and reach a target point;
- fly to the nearest asteroid without collision;
- scan for ore and select a mining target;
- mine resources and return to base;
- dock to a free connector;
- unload cargo and start refining ore;
- produce missing components using assembler queues;
- load a blueprint into a projector and prepare construction;
- recover from common failures such as being stuck, misaligned, low on power, damaged, or missing resources.

Each scenario can produce structured logs: world state, goal, plan, tool calls, telemetry results, failure reason, and corrected plan.

## Limitations and safety

The project is experimental. Agents are developed inside a game simulation and should not be treated as reliable real-world robotics controllers.

Current limitations include:

- incomplete world understanding;
- imperfect navigation and docking;
- possible collision or stuck states;
- incomplete failure recovery;
- dependence on available telemetry and game-side integration.

The project focuses on safe sandboxed experimentation before applying similar ideas to more realistic environments.

## How stronger AI models can help

Codex and API credits, if available, would be used to accelerate development of the open-source autonomy stack.

Planned uses include:

- Code review and refactoring of Python control scripts.
- Generating tests for navigation, docking, production, logistics, and resource management.
- Debugging complex failures in autonomous behavior.
- Improving reliability of long-running scripts.
- Creating safer control logic for ships, connectors, thrusters, gyroscopes, and production systems.
- Building higher-level planning tools for AI agents.
- Producing documentation and examples for other contributors.
- Analyzing telemetry logs and turning failures into reproducible test cases.
- Creating evaluation scenarios for autonomous AI agents.

Access to stronger models would directly improve the speed and quality of development. The project requires frequent debugging across game telemetry, Python automation, state machines, planning logic, and real-time behavior. AI-assisted development can help turn experimental scripts into a reliable open-source platform for autonomous AI research.

## Features

- Connecting to Redis using configuration from `.env` or constructor arguments.
- Monitoring keys and channels with automatic subscription recovery.
- Utilities for obtaining owner, player, and grid identifiers.
- Controllers for radar scanning, shared world memory, and ship navigation.
- Device abstractions for Space Engineers blocks and systems.
- Examples demonstrating command publishing, state monitoring, and automation workflows.

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
print(
    ", ".join((d.name or f"{d.device_type}:{d.device_id}") for d in grid.devices.values())
    or "(no devices)"
)
```

### Environment variables

| Variable         | Purpose                                               |
| ---------------- | ----------------------------------------------------- |
| `REDIS_USERNAME` | Username for authorization.                           |
| `REDIS_PASSWORD` | Password for connection.                              |
| `SE_OWNER_ID`    | Space Engineers owner ID.                             |
| `SE_PLAYER_ID`   | Player ID; falls back to the owner ID when omitted.   |

Variables can be defined in the `.env` file in the project root. `REDIS_USERNAME` and `REDIS_PASSWORD` must be obtained in the personal account on the page <https://www.outenemy.ru/se/>.

## Examples

Ready-made scripts are located in the [`examples/organized`](examples/organized) directory, organized by device type and complexity level:

- `basic/` - introductory examples.
- `lamp/` - lamp device control examples.
- `container/` - cargo container and inventory examples.
- `assembler/` - assembler production and queue examples.
- `rover/` - rover movement, wheel control, and steering examples.
- `display/` - display content and visualization examples.
- `grid/` - grid-level information, resources, and damage examples.
- `ai/` - AI automation experiments.
- `refinery/` - refinery control and priority examples.
- `radar/` - radar, ore detection, and shared-map examples.
- `inventory/` - inventory tracking and transfer examples.
- `parking/` - docking and connector parking workflows.

## Documentation

- [Operator playbook](docs/agent-playbook/PLAYBOOK.md) - ready-to-run commands for navigation, mining, construction, production, inventory, and monitoring.
- [Developer guide](docs/agent-dev/DEVGUIDE.md) - project structure, APIs, controllers, devices, code conventions, and testing.
- [Admin guide](admins/AGENTS.md) - server administration, grid spawning, teleportation, chat, AI factions, and block/voxel operations.
- [API reference](docs/API_REFERENCE.md) - library API documentation.
- [Device reference](docs/DEVICE_REFERENCE.md) - supported Space Engineers device abstractions.
- [Examples catalog](docs/EXAMPLES.md) - additional example descriptions.
- [Architecture](ARCHITECTURE.md) - deeper architecture notes.
- [Wiki](https://github.com/rootfabric/secontrol/wiki/home) - project wiki.

## Repository status

This project is in active development and is intended to remain a public open-source repository. Some capabilities are already implemented, while others are experimental or planned.

## Contributing

Contributions are welcome, especially in navigation, telemetry, testing, documentation, planning, reliability, failure recovery, and agent evaluation scenarios.

## License

The project is distributed under the MIT license. See the [LICENSE](LICENSE) file.
