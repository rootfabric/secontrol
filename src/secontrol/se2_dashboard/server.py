"""SE2-only dashboard: grids of Space Engineers 2, voxels around a grid, asteroids, ore deposits."""
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..fleet_dashboard.redis_reader import SE2VoxelService

app = FastAPI(title="SE2 Dashboard")
service = SE2VoxelService(None)  # own Redis connection (SE2_REDIS_URL / localhost)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (static_dir / "index.html").read_text(encoding="utf-8")


@app.get("/api/grids")
async def api_grids():
    try:
        return {"grids": service.grids()}
    except Exception as e:
        return {"error": str(e), "grids": []}


@app.get("/api/state")
async def api_state():
    try:
        return service._state()
    except Exception as e:
        return {"error": str(e)}


class ScanRequest(BaseModel):
    grid_id: str
    radius: float = 32.0


@app.post("/api/voxel_scan")
async def api_voxel_scan(body: ScanRequest):
    try:
        return service.start_scan(body.grid_id, body.radius, True)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/voxel_status/{request_id}")
async def api_voxel_status(request_id: str):
    try:
        return service.status(request_id)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/voxels/{request_id}")
async def api_voxels(request_id: str):
    try:
        result = service.voxels(request_id)
        if result is None:
            return {"error": "No scan data available"}
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/voxel_tiles/{request_id}")
async def api_voxel_tiles(request_id: str):
    """Raw tiles with per-tile axes — client orients chunks correctly."""
    try:
        result = service.tiles(request_id)
        if result is None:
            return {"error": "No scan data available"}
        return result
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/asteroid_index")
async def api_asteroid_index(body: ScanRequest):
    try:
        return service.start_asteroid_index(body.grid_id, body.radius)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/asteroids/{request_id}")
async def api_asteroids(request_id: str):
    try:
        result = service.asteroids(request_id)
        if result is None:
            return {"error": "No index data available"}
        return result
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/deposits")
async def api_deposits(body: ScanRequest):
    try:
        return service.start_deposits(body.grid_id)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/deposits_result/{request_id}")
async def api_deposits_result(request_id: str):
    try:
        result = service.deposits(request_id)
        if result is None:
            return {"error": "No deposit data available"}
        return result
    except Exception as e:
        return {"error": str(e)}


def main():
    import uvicorn
    port = int(os.getenv("SE2_DASHBOARD_PORT", "8082"))
    host = os.getenv("SE2_DASHBOARD_HOST", "127.0.0.1")
    print(f"Starting SE2 Dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
