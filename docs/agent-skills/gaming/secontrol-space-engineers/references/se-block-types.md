# Space Engineers Block Types Reference

## Registered in DEVICE_TYPE_MAP (31 types)

| Key | Class | Category |
|---|---|---|
| ai_behavior | AiBehaviorDevice | AI |
| ai_defensive | AiDefensiveDevice | AI |
| ai_move_ground | AiMoveGroundDevice | AI |
| ai_offensive | AiOffensiveDevice | AI |
| ai_recorder | AiRecorderDevice | AI |
| assembler | AssemblerDevice | Production |
| battery | BatteryDevice | Power |
| cockpit | CockpitDevice | Control |
| connector | ConnectorDevice | Docking |
| container | ContainerDevice | Storage |
| conveyor_sorter | ConveyorSorterDevice | Logistics |
| flightmovementblock | AiFlightAutopilotDevice | AI |
| gas_generator | GasGeneratorDevice | Power |
| gyro | GyroDevice | Navigation |
| interior_turret | InteriorTurretDevice | Defense |
| lamp | LampDevice | Utility |
| large_turret | LargeTurretDevice | Defense |
| nanobot_build_and_repair | BuildAndRepairDevice | Automation |
| nanobot_drill_system | NanobotDrillSystemDevice | Mining |
| ore_detector | OreDetectorDevice | Mining |
| projector | ProjectorDevice | Construction |
| reactor | ReactorDevice | Power |
| refinery | RefineryDevice | Production |
| remote_control | RemoteControlDevice | Control |
| ship_drill | ShipDrillDevice | Mining |
| ship_grinder | ShipGrinderDevice | Deconstruction |
| ship_welder | ShipWelderDevice | Construction |
| textpanel | DisplayDevice | Display |
| thruster | ThrusterDevice | Propulsion |
| weapon | WeaponDevice | Defense |
| wheel | WheelDevice | Propulsion |

## Common GenericDevice types (not in DEVICE_TYPE_MAP)

These appear as `GenericDevice` with `dev.device_type` set to the SE type string:

| SE Type | Purpose | Priority |
|---|---|---|
| survivalkit | Respawn + basic refining/assembly | HIGH — on most bases |
| solarpanel | Free power generation | HIGH — on stations |
| beacon | Navigation marker | MEDIUM |
| oxygentank | O2 storage | MEDIUM |
| airvent | Pressurization | MEDIUM |

## Missing critical blocks (not registered, not on grids as Generic)

| Block | Purpose |
|---|---|
| Oxygen Generator | Ice → O2 + H2 (fuel for drones) |
| Hydrogen Tank | H2 fuel storage |
| Hydrogen Engine | Alternative power from H2 |
| Antenna | Long-range comms, coordination |
| Laser Antenna | Point-to-point comms |
| Wind Turbine | Free station power |
| Timer Block | Scheduled automation |
| Programmable Block | In-game scripting |
| Event Controller | Conditional automation |
| Sensor | Proximity detection |
| Camera | Raycast / vision |
| Gatling Turret | Medium defense |
| Missile Turret | Heavy defense |
| Piston / Rotor / Hinge | Mechanical movement |
| Merge Block | Grid merging |
| Landing Gear | Passive docking |
| Medical Room | Respawn point |
