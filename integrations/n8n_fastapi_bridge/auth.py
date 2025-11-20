"""Authentication helpers for the FastAPI ⇔ n8n bridge."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import Header, HTTPException, status


@dataclass(slots=True)
class UserAccount:
    """Simple user profile bound to a specific Space Engineers owner."""

    username: str
    hashed_password: str
    owner_id: str
    player_id: Optional[str] = None
    redis_url: Optional[str] = None
    redis_username: Optional[str] = None
    redis_password: Optional[str] = None
    description: Optional[str] = None

    def display_name(self) -> str:
        return self.description or self.username


class UserStore:
    """Loads bridge users from a JSON file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._users: Dict[str, UserAccount] = {}
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """(Re)load user accounts from disk."""

        if not self._path.exists():
            raise FileNotFoundError(
                f"User configuration file {self._path} was not found. "
                "Copy users.example.json and adjust the credentials."
            )

        with self._lock:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            users: Dict[str, UserAccount] = {}
            for entry in raw:
                username = entry.get("username")
                password = entry.get("password") or entry.get("hashed_password")
                owner_id = entry.get("owner_id")
                if not username or not password or not owner_id:
                    raise ValueError(
                        "Each user entry must define 'username', 'password' (hashed) and 'owner_id'."
                    )
                if len(password) != 64 or not all(c in "0123456789abcdef" for c in password.lower()):
                    raise ValueError(
                        "Passwords must be provided as SHA-256 hex digests. Use hash_password() helper."
                    )

                account = UserAccount(
                    username=username,
                    hashed_password=password.lower(),
                    owner_id=str(owner_id),
                    player_id=entry.get("player_id") or str(owner_id),
                    redis_url=entry.get("redis_url"),
                    redis_username=entry.get("redis_username"),
                    redis_password=entry.get("redis_password"),
                    description=entry.get("description"),
                )
                users[username] = account
            self._users = users

    def get(self, username: str) -> Optional[UserAccount]:
        with self._lock:
            return self._users.get(username)

    def authenticate(self, username: str, password: str) -> Optional[UserAccount]:
        candidate = self.get(username)
        if not candidate:
            return None
        hashed = hash_password(password)
        if hashed != candidate.hashed_password:
            return None
        return candidate


class TokenStore:
    """In-memory storage for issued access tokens."""

    def __init__(self, lifetime_minutes: int = 60) -> None:
        self._lifetime = timedelta(minutes=lifetime_minutes)
        self._tokens: Dict[str, tuple[UserAccount, datetime]] = {}
        self._lock = threading.RLock()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def issue(self, user: UserAccount) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = self._now() + self._lifetime
        with self._lock:
            self._tokens[token] = (user, expires_at)
        return token, expires_at

    def resolve(self, token: str) -> UserAccount:
        with self._lock:
            self._purge_locked()
            entry = self._tokens.get(token)
            if not entry:
                raise KeyError("token not found")
            user, expires_at = entry
            if expires_at <= self._now():
                self._tokens.pop(token, None)
                raise KeyError("token expired")
            return user

    def _purge_locked(self) -> None:
        now = self._now()
        expired = [token for token, (_, exp) in self._tokens.items() if exp <= now]
        for token in expired:
            self._tokens.pop(token, None)

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)


def hash_password(password: str) -> str:
    """Return a SHA-256 hex digest for ``password``."""

    if password is None:
        raise ValueError("password must not be None")
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class AuthManager:
    """Utility that plugs token validation into FastAPI dependencies."""

    def __init__(self, store: UserStore, tokens: TokenStore) -> None:
        self._store = store
        self._tokens = tokens

    def login(self, username: str, password: str) -> tuple[str, datetime, UserAccount]:
        user = self._store.authenticate(username, password)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token, expires_at = self._tokens.issue(user)
        return token, expires_at, user

    def dependency(self, authorization: str = Header(...)) -> UserAccount:
        if not authorization:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization scheme")
        try:
            return self._tokens.resolve(token)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is invalid or expired")

    def optional_dependency(self, authorization: str | None = Header(default=None)) -> Optional[UserAccount]:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            return self._tokens.resolve(token)
        except KeyError:
            return None


__all__ = [
    "AuthManager",
    "TokenStore",
    "UserAccount",
    "UserStore",
    "hash_password",
]
