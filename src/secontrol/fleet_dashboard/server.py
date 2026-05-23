import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .redis_reader import FleetRedisReader

app = FastAPI(title="SE Fleet Dashboard")
reader = FleetRedisReader()

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (static_dir / "index.html").read_text(encoding="utf-8")


@app.get("/api/fleet/status")
async def api_fleet_status():
    try:
        return reader.get_fleet_status()
    except Exception as e:
        return {"error": str(e), "grids": []}


@app.get("/api/grids")
async def api_grids():
    try:
        return {"grids": reader.get_grids_list()}
    except Exception as e:
        return {"error": str(e), "grids": []}


@app.get("/api/grid/{grid_id}")
async def api_grid_detail(grid_id: str):
    try:
        detail = reader.get_grid_detail(grid_id)
        nearby = reader.get_nearby_grids(grid_id)
        detail["nearby"] = nearby
        return detail
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/grid/{grid_id}/devices")
async def api_grid_devices(grid_id: str):
    try:
        return {"devices": reader.get_devices_summary(grid_id)}
    except Exception as e:
        return {"error": str(e), "devices": []}


@app.get("/api/grid/{grid_id}/containers")
async def api_grid_containers(grid_id: str):
    try:
        return {"containers": reader.get_grid_containers(grid_id)}
    except Exception as e:
        return {"error": str(e), "containers": []}


@app.get("/api/device/{device_id}/telemetry")
async def api_device_telemetry(device_id: str, grid_id: str, device_type: str):
    try:
        telemetry = reader.get_device_telemetry(device_id, grid_id, device_type)
        return {"telemetry": telemetry}
    except Exception as e:
        return {"error": str(e)}


class GridCommand(BaseModel):
    command: Dict[str, Any]


@app.post("/api/grid/{grid_id}/command")
async def api_grid_command(grid_id: str, body: GridCommand):
    try:
        ok = reader.send_grid_command(grid_id, body.command)
        if not ok:
            return {"error": "SE_PLAYER_ID not set, cannot send commands"}
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


class DeviceCommand(BaseModel):
    command: Dict[str, Any]


@app.post("/api/device/{device_id}/command")
async def api_device_command(device_id: str, body: DeviceCommand):
    try:
        ok = reader.send_device_command(device_id, body.command)
        if not ok:
            return {"error": "SE_PLAYER_ID not set, cannot send commands"}
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    current_grid_id = None
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "select_grid":
                current_grid_id = msg.get("grid_id")
            if current_grid_id:
                try:
                    detail = reader.get_grid_detail(current_grid_id)
                    nearby = reader.get_nearby_grids(current_grid_id)
                    detail["nearby"] = nearby
                    devices = reader.get_devices_summary(current_grid_id)
                    detail["device_details"] = devices
                    await ws.send_text(json.dumps({"type": "update", "data": detail}))
                except Exception as e:
                    await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


def main():
    import uvicorn
    port = int(os.getenv("FLEET_DASHBOARD_PORT", "8081"))
    host = os.getenv("FLEET_DASHBOARD_HOST", "0.0.0.0")
    print(f"Starting SE Fleet Dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
