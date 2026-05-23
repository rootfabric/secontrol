from pathlib import Path
from examples.organized.radar.ore_deposit_scanner import load_scan

data = load_scan()
print("=== Saved scan data ===")
print(f"Scan time: {data['scan_time']}")
print(f"Grid: {data['grid']['name']}")
print(f"Ship position: {data['ship_position']}")
print()
print("=== Ore Summary ===")
for ore, info in data["ore_summary"].items():
    print(f"  {ore}: {info['count']} deposits, closest={info['closest_m']}m, max_content={info['max_content']}")

print()
print("=== Clusters ===")
for cl in data["clusters"]:
    print(f"  {cl['ore_type']}: {cl['deposit_count']} deposits, spread={cl['spread_m']}m")
    print(f"    center: {cl['center']}")
    gps = f"GPS:{cl['ore_type']}:{cl['center'][0]}:{cl['center'][1]}:{cl['center'][2]}:#FF8800:"
    print(f"    {gps}")