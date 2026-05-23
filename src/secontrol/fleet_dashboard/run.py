"""Launch SE Fleet Dashboard standalone.

Usage:
    python src/secontrol/fleet_dashboard/run.py
"""
import os
import sys
from pathlib import Path

# Ensure src is on the path so fleet_dashboard can be imported as a package
_here = Path(__file__).resolve().parent
_src = _here.parent.parent  # src/
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# Now import and run
from secontrol.fleet_dashboard.server import main

if __name__ == "__main__":
    main()
