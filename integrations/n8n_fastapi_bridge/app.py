"""FastAPI application exposing Space Engineers grids to n8n."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from base64 import b64decode

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .auth import AuthManager, TokenStore, UserAccount, UserStore
from .models import (
    CommandRequest,
    CommandResponse,
    DeviceSummary,
    GridSummary,
    LoginRequest,
    TelemetryResponse,
    TokenResponse,
    UserProfile,
)
from .services import BridgeService, RedisManager


app = FastAPI(title="Space Engineers Grid Bridge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


USERS_FILE = Path(__file__).with_name("users.json")
if not USERS_FILE.exists():
    example = Path(__file__).with_name("users.example.json")
    if example.exists():
        USERS_FILE = example
_user_store = UserStore(USERS_FILE)
_token_store = TokenStore(lifetime_minutes=120)
_auth_manager = AuthManager(_user_store, _token_store)
_redis_manager = RedisManager()
_bridge_service = BridgeService(_redis_manager)


@app.on_event("startup")
def _startup() -> None:
    _user_store.load()


@app.on_event("shutdown")
def _shutdown() -> None:
    _redis_manager.close()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest | None = None, request: Request | None = None) -> TokenResponse:
    username = payload.username if payload else None
    password = payload.password if payload else None
    if (not username or not password) and request is not None:
        auth_header = request.headers.get("Authorization")
        if auth_header:
            scheme, _, token = auth_header.partition(" ")
            if scheme.lower() == "basic" and token:
                try:
                    decoded = b64decode(token).decode("utf-8")
                except Exception:
                    decoded = ""
                if decoded:
                    username, _, pwd = decoded.partition(":")
                    password = pwd
    if not username or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username and password must be provided")

    token, expires_at, user = _auth_manager.login(username, password)
    now = datetime.now(timezone.utc)
    expires_in = max(int((expires_at - now).total_seconds()), 0)
    profile = UserProfile(
        username=user.username,
        ownerId=user.owner_id,
        playerId=user.player_id,
        displayName=user.display_name(),
    )
    return TokenResponse(
        access_token=token,
        expiresAt=expires_at,
        expiresIn=expires_in,
        user=profile,
    )


@app.get("/me", response_model=UserProfile)
def me(user: UserAccount = Depends(_auth_manager.dependency)) -> UserProfile:
    return UserProfile(
        username=user.username,
        ownerId=user.owner_id,
        playerId=user.player_id,
        displayName=user.display_name(),
    )


@app.get("/grids", response_model=List[GridSummary])
def list_grids(user: UserAccount = Depends(_auth_manager.dependency)) -> List[GridSummary]:
    return _bridge_service.list_grids(user, include_subgrids=True)


@app.get("/grids/{grid_id}/devices", response_model=List[DeviceSummary])
def list_grid_devices(grid_id: str, user: UserAccount = Depends(_auth_manager.dependency)) -> List[DeviceSummary]:
    return _bridge_service.list_devices(user, grid_id)


@app.get("/devices", response_model=List[DeviceSummary])
def list_devices(
    grid_id: Optional[str] = None,
    user: UserAccount = Depends(_auth_manager.dependency),
) -> List[DeviceSummary]:
    if grid_id:
        return _bridge_service.list_devices(user, grid_id)
    return _bridge_service.list_all_devices(user)


@app.get("/grids/{grid_id}/devices/{device_id}", response_model=DeviceSummary)
def get_device(
    grid_id: str,
    device_id: str,
    user: UserAccount = Depends(_auth_manager.dependency),
) -> DeviceSummary:
    return _bridge_service.get_device(user, grid_id, device_id)


@app.get(
    "/grids/{grid_id}/devices/{device_id}/telemetry",
    response_model=TelemetryResponse,
)
def get_device_telemetry(
    grid_id: str,
    device_id: str,
    user: UserAccount = Depends(_auth_manager.dependency),
) -> TelemetryResponse:
    return _bridge_service.get_device_telemetry(user, grid_id, device_id)


@app.post("/grids/{grid_id}/command", response_model=CommandResponse)
def send_grid_command(
    grid_id: str,
    command: CommandRequest,
    user: UserAccount = Depends(_auth_manager.dependency),
) -> CommandResponse:
    sent = _bridge_service.send_grid_command(user, grid_id, command)
    return CommandResponse(channelCount=sent, command=command.command_dict())


@app.post(
    "/grids/{grid_id}/devices/{device_id}/command",
    response_model=CommandResponse,
)
def send_device_command(
    grid_id: str,
    device_id: str,
    command: CommandRequest,
    user: UserAccount = Depends(_auth_manager.dependency),
) -> CommandResponse:
    sent = _bridge_service.send_device_command(user, grid_id, device_id, command)
    return CommandResponse(channelCount=sent, command=command.command_dict())


__all__ = ["app"]
