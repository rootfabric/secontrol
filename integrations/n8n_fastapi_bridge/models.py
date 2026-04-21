"""Pydantic models for the FastAPI ⇔ n8n bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserProfile(BaseModel):
    username: str
    owner_id: str = Field(alias="ownerId")
    player_id: Optional[str] = Field(default=None, alias="playerId")
    display_name: Optional[str] = Field(default=None, alias="displayName")

    model_config = ConfigDict(populate_by_name=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer", alias="token_type")
    expires_at: datetime = Field(alias="expiresAt")
    expires_in: int = Field(alias="expiresIn")
    user: UserProfile

    model_config = ConfigDict(populate_by_name=True)


class GridSummary(BaseModel):
    id: str
    owner_id: str = Field(alias="ownerId")
    name: Optional[str] = None
    is_subgrid: bool = Field(default=False, alias="isSubgrid")
    descriptor: Dict[str, Any] = Field(default_factory=dict)
    info: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class DeviceSummary(BaseModel):
    id: str
    grid_id: str = Field(alias="gridId")
    owner_id: str = Field(alias="ownerId")
    type: Optional[str] = Field(default=None, alias="deviceType")
    name: Optional[str] = None
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    command_channel: Optional[str] = Field(default=None, alias="commandChannel")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class CommandRequest(BaseModel):
    """Generic command envelope."""

    model_config = ConfigDict(extra="allow")

    cmd: str
    state: Any | None = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    def command_dict(self) -> Dict[str, Any]:
        base = self.model_dump(exclude_none=True)
        extras = {k: v for k, v in (self.model_extra or {}).items() if v is not None}
        if extras:
            base.update(extras)
        return base

    @property
    def extra_params(self) -> Dict[str, Any]:
        return {k: v for k, v in (self.model_extra or {}).items() if v is not None}


class CommandResponse(BaseModel):
    ok: bool = True
    channel_count: int = Field(alias="channelCount")
    command: Dict[str, Any]

    model_config = ConfigDict(populate_by_name=True)


class TelemetryResponse(BaseModel):
    device: DeviceSummary
    telemetry: Dict[str, Any]
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


__all__ = [
    "CommandRequest",
    "CommandResponse",
    "DeviceSummary",
    "GridSummary",
    "LoginRequest",
    "TelemetryResponse",
    "TokenResponse",
    "UserProfile",
]
