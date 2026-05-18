# secontrol Grid Data — Session May 14 2026

## Redis Connection

- **Host:** `192.168.0.15:6379` (local network — reachable)
- **Owner ID:** `144115188075855919`
- **Auth:** `REDIS_PASSWORD=IkLg6ZF3k2BeRl2PkT8hKgLE`
- **Source:** `.env` in `/workspace`

## Verified Available Grids

| ID | Name | Notes |
|---|---|---|
| `134540402238780591` | DroneBase 2 | Likely drone carrier / secondary base |
| `138748817302648345` | DroneBase | Primary drone base |
| `74055729860857332` | taburet3 | Station or ship (taburet = Russian "stool", likely small structure) |
| `82069157247683112` | Respawn Rover | Rover that respawns (player vehicle) |
| `98945391841930411` | taburet2 | Small structure #2 |

## Query Code Used

The `execute_code` sandbox lacks `redis`. Used subprocess with system Python:

```python
result = subprocess.run(
    [sys.executable, '-c', '''
import sys
sys.path.insert(0, '/workspace/src')
import os
os.environ['REDIS_USERNAME'] = '144115188075855919'
os.environ['REDIS_PASSWORD'] = 'IkLg6ZF3k2BeRl2PkT8hKgLE'
os.environ['REDIS_URL'] = 'redis://192.168.0.15:6379/0'

from secontrol.common import get_all_grids
grids = get_all_grids()
for gid, gname in grids:
    print(f"{gid}  {gname}")
'''],
    capture_output=True, text=True, timeout=20
)
```

Full output:
```
Owner ID: 144115188075855919

Доступные гриды (5):
ID                        Имя
─────────────────────────────────────────────────────────────────
134540402238780591        DroneBase 2
138748817302648345        DroneBase
74055729860857332         taburet3
82069157247683112         Respawn Rover
98945391841930411         taburet2
```

## Key Patterns

- `get_all_grids()` returns `list[tuple[str, str]]` of `(grid_id, grid_name)`
- Subgrids are automatically excluded
- `resolve_owner_id()` reads `REDIS_USERNAME` env var
- All env vars can also live in `.env` file (auto-loaded by `load_dotenv`)
