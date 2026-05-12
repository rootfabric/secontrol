import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .redis_reader import RedisReader

app = FastAPI(title="SE Grid Dashboard")
reader = RedisReader()

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (static_dir / "index.html").read_text(encoding="utf-8")


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
                    await ws.send_text(json.dumps({"type": "update", "data": detail}))
                except Exception as e:
                    await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


def main():
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    print(f"Starting SE Grid Dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
