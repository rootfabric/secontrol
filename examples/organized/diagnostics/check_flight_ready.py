"""Ship Flight Readiness Diagnostic.

Checks battery charge level and hydrogen fuel level (if hydrogen engines present).
Run standalone or import check_ship_readiness() function.

Usage:
    python check_flight_ready.py [grid_name]
"""
from __future__ import annotations

import sys
from secontrol import Grid
from secontrol.redis_client import RedisEventClient
from secontrol.fleet_dashboard.redis_reader import FleetRedisReader


def check_ship_readiness(grid: Grid) -> dict[str, bool | list[str]]:
    results = {
        "ready": True,
        "warnings": [],
        "batteries": [],
        "hydrogen_warning": None,
        "engines": [],
        "has_ion_thrusters": False,
        "has_hydrogen_thrusters": False,
    }

    reader = FleetRedisReader()
    grid_id = grid.grid_id
    telemetry_map = reader._discover_telemetry(grid_id)

    batteries = grid.find_devices_by_type("battery")
    for bat in batteries:
        device_id = bat.device_id
        tel = telemetry_map.get(device_id, {})
        stored = tel.get("currentStoredPower", 0.0)
        capacity = tel.get("maxStoredPower", 1.0)
        charge_pct = (stored / capacity * 100) if capacity else 0
        results["batteries"].append({
            "name": tel.get("name", tel.get("CustomName", tel.get("displayName", "Battery"))),
            "stored": stored,
            "capacity": capacity,
            "charge_pct": charge_pct,
        })
        if charge_pct < 20:
            results["ready"] = False
            results["warnings"].append(f"Low battery charge: {charge_pct:.1f}%")

    for device_id, tel in telemetry_map.items():
        dev_type = str(tel.get("type", ""))
        subtype = str(tel.get("subtype", "")).lower()
        name = str(tel.get("name", ""))
        if "Thrust" in dev_type:
            if "hydrogen" in subtype or "hydrogenthrust" in subtype:
                results["has_hydrogen_thrusters"] = True
            else:
                results["has_ion_thrusters"] = True
            results["engines"].append({
                "name": name,
                "type": dev_type,
                "subtype": subtype,
            })
        elif "HydrogenEngine" in dev_type:
            results["has_hydrogen_thrusters"] = True

    if results["has_hydrogen_thrusters"]:
        hydrogen_level = None
        for device_id, tel in telemetry_map.items():
            dev_type = str(tel.get("type", ""))
            if "OxygenTank" in dev_type and "hydrogen" in str(tel.get("subtype", "")).lower():
                fr = tel.get("filledRatio")
                fp = tel.get("filledPercent")
                if fr is not None:
                    hydrogen_level = float(fr) * 100
                elif fp is not None:
                    hydrogen_level = float(fp)
                break

        if hydrogen_level is not None:
            if hydrogen_level < 20:
                if not results["has_ion_thrusters"]:
                    results["ready"] = False
                    results["hydrogen_warning"] = f"CRITICAL: No hydrogen fuel ({hydrogen_level:.0f}%) and no ion backup!"
                else:
                    results["hydrogen_warning"] = f"WARNING: Low hydrogen ({hydrogen_level:.0f}%), ion thrusters available"
            elif hydrogen_level < 50:
                results["hydrogen_warning"] = f"Hydrogen low: {hydrogen_level:.0f}%"
            else:
                results["hydrogen_warning"] = f"Hydrogen OK: {hydrogen_level:.0f}%"

    return results


def print_report(grid_name: str, results: dict) -> None:
    print(f"\n{'=' * 50}")
    print(f"  Ship: {grid_name}")
    print(f"{'=' * 50}")

    print("\nBatteries:")
    if not results["batteries"]:
        print("  None found")
    for bat in results["batteries"]:
        icon = "[OK]" if bat["charge_pct"] >= 50 else ("[WARN]" if bat["charge_pct"] >= 20 else "[FAIL]")
        print(f"  {icon} {bat['name']}: {bat['charge_pct']:.1f}% ({bat['stored']:.2f} / {bat['capacity']:.2f} MWh)")

    eng_lines = []
    for eng in results["engines"]:
        subtype = eng["subtype"]
        if "hydrogen" in subtype:
            eng_lines.append(f"  - {eng['name']} (hydrogen)")
        else:
            eng_lines.append(f"  - {eng['name']} (ion)")
    if eng_lines:
        print("\nThrusters:")
        for line in eng_lines:
            print(line)

    if results["hydrogen_warning"] is not None:
        icon = "[OK]" if "OK" in results["hydrogen_warning"] else ("[WARN]" if "WARNING" in results["hydrogen_warning"] else "[FAIL]")
        print(f"\nHydrogen: {icon} {results['hydrogen_warning']}")

    print("\n[OK] READY FOR FLIGHT" if results["ready"] else "[FAIL] NOT READY FOR FLIGHT")

    if results["warnings"]:
        print("\nWarnings:")
        for w in results["warnings"]:
            print(f"  - {w}")


def main() -> None:
    grid_name = sys.argv[1] if len(sys.argv) > 1 else None

    client = RedisEventClient()
    try:
        if grid_name:
            grid = Grid.from_name(grid_name, redis_client=client)
        else:
            grids = Grid.list_available(redis_client=client)
            if not grids:
                print("No grids available")
                return
            grid = Grid.from_name(grids[0][1], redis_client=client)

        results = check_ship_readiness(grid)
        print_report(grid.name, results)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    main()