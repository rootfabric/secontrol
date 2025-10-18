"""Redis client implementation for Space Engineers grid control.

This module provides a lightweight Redis client for publish/subscribe patterns
and keyspace notifications, specifically designed for Space Engineers
telemetry and command systems.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional

import redis

CallbackType = Callable[[str, Optional[Any], str], None]


class RedisEventClient:
    """Lightweight helper around :mod:`redis` for publish/subscribe patterns.

    The class focuses on keyspace notifications. To receive change events the
    Redis instance must have ``notify-keyspace-events`` configured with at
    least ``K$`` (keyspace events) and ``E$`` (generic events) flags. Most
    Space Engineers Redis bridge configurations already enable this, but the
    code also works in polling mode when the events are not available – the
    initial value can always be retrieved with :meth:`get_json` or
    :meth:`get_value`.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Create a Redis client using configuration from arguments or ``.env``."""

        resolved_url = url or os.getenv("REDIS_URL", "redis://api.outenemy.ru:6379/0")
        resolved_username = username if username is not None else os.getenv("REDIS_USERNAME")
        resolved_password = password if password is not None else os.getenv("REDIS_PASSWORD")

        connection_kwargs: Dict[str, Any] = {
            "decode_responses": False,
            "socket_keepalive": True,
            "health_check_interval": 30,
            "retry_on_timeout": True,
            "socket_timeout": 5,
        }
        if resolved_username:
            connection_kwargs["username"] = resolved_username
        if resolved_password:
            connection_kwargs["password"] = resolved_password
        connection_kwargs.update(kwargs)

        self._client = redis.Redis.from_url(resolved_url, **connection_kwargs)

        self._db_index = int(self._client.connection_pool.connection_kwargs.get("db", 0))
        self._subscriptions: list[_PubSubSubscription] = []

    # ------------------------------------------------------------------
    # Basic Redis helpers
    # ------------------------------------------------------------------
    def get_value(self, key: str) -> Optional[bytes]:
        try:
            return self._client.get(key)
        except redis.RedisError as exc:  # pragma: no cover - defensive logging
            raise RuntimeError(f"Failed to read key {key!r}: {exc}") from exc

    def get_json(self, key: str) -> Optional[Any]:
        value = self.get_value(key)
        if value is None:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def list_grids(self, owner_id: str | int, *, key: str | None = None) -> list[Dict[str, Any]]:
        """Return all grid descriptors available for ``owner_id``.

        The Space Engineers Redis bridge stores the list of grids for an owner
        under the ``se:{owner_id}:grids`` key.  The value is expected to be a
        JSON document with a top-level ``grids`` array, but the method is
        tolerant to plain lists as well.  Missing keys result in an empty list.
        """

        owner = str(owner_id)
        redis_key = key or f"se:{owner}:grids"
        payload = self.get_json(redis_key)
        if payload is None:
            return []

        if isinstance(payload, dict):
            grids = payload.get("grids", [])
        else:
            grids = payload

        if not isinstance(grids, list):
            raise ValueError(
                f"Unexpected grids payload type for {redis_key!r}: {type(payload).__name__}"
            )

        return [grid for grid in grids if isinstance(grid, dict)]

    def publish(self, channel: str, payload: Any) -> int:
        if not isinstance(payload, (str, bytes)):
            payload = json.dumps(payload, ensure_ascii=False)
        try:
            return self._client.publish(channel, payload)  # type: ignore[return-value]
        except redis.RedisError as exc:  # pragma: no cover - defensive logging
            raise RuntimeError(f"Failed to publish to {channel!r}: {exc}") from exc

    def set_json(self, key: str, value: Any, expire: Optional[int] = None) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        try:
            if expire is None:
                self._client.set(key, payload)
            else:
                self._client.setex(key, expire, payload)
        except redis.RedisError as exc:  # pragma: no cover - defensive logging
            raise RuntimeError(f"Failed to write key {key!r}: {exc}") from exc

    # ------------------------------------------------------------------
    # Subscription handling
    # ------------------------------------------------------------------
    def subscribe_to_key(self, key: str, callback: CallbackType, *,
                         events: Iterable[str] | None = None) -> "_PubSubSubscription":
        channel = f"__keyspace@{self._db_index}__:{key}"
        subscription = _PubSubSubscription(
            self._client,
            channel,
            key,
            callback,
            tuple(events) if events else ("set", "del"),
            is_pattern=False,   # <<--- ВАЖНО: точный канал, не паттерн
            is_keyspace=True,
        )
        subscription.start()
        self._subscriptions.append(subscription)
        return subscription


    def subscribe_to_channel(self, channel: str, callback: CallbackType) -> "_PubSubSubscription":
        subscription = _PubSubSubscription(self._client, channel, channel, callback, None, is_pattern=False,
                                           is_keyspace=False)
        subscription.start()
        self._subscriptions.append(subscription)
        return subscription

    def close(self) -> None:
        # закрываем все активные подписки
        for sub in list(self._subscriptions):
            try:
                sub.close()
            except Exception:
                pass
        self._subscriptions.clear()

        # закрываем сам Redis-клиент
        try:
            self._client.close()
        except Exception:
            pass

    @property
    def client(self) -> redis.Redis:
        return self._client


class _PubSubSubscription:
    """Internal helper that runs a background thread to process events."""

    def __init__(
            self,
            client: redis.Redis,
            channel: str,
            key: str,
            callback: CallbackType,
            events: Optional[tuple[str, ...]],
            *,
            is_pattern: bool = True,
            is_keyspace: bool = True,
    ) -> None:
        self._client = client
        self._channel = channel
        self._key = key
        self._callback = callback
        self._events = events
        self._is_pattern = is_pattern
        self._is_keyspace = is_keyspace
        self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        if self._is_pattern:
            self._pubsub.psubscribe(channel)
        else:
            self._pubsub.subscribe(channel)
        self._thread = threading.Thread(target=self._run, name=f"redis-sub-{channel}", daemon=True)
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        try:
            try:
                if self._is_pattern:
                    self._pubsub.punsubscribe()
                else:
                    self._pubsub.unsubscribe()
            except Exception:
                pass
            self._pubsub.close()
        except Exception:
            pass
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop_event.is_set():
            try:
                msg = self._pubsub.get_message(timeout=1.0)
            except (redis.ConnectionError, redis.TimeoutError, OSError, ValueError) as _:
                if self._stop_event.is_set():
                    break
                try:
                    self._pubsub.close()
                except Exception:
                    pass
                try:
                    self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
                    if self._is_pattern:
                        self._pubsub.psubscribe(self._channel)
                    else:
                        self._pubsub.subscribe(self._channel)
                    backoff = 0.5
                except Exception:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 5.0)
                continue
            except redis.ResponseError as e:
                # Явно подсказуемая ситуация: нет прав на канал
                err = str(e)
                if "No permissions to access a channel" in err or "NOPERM" in err:
                    # Либо логируем, либо поднимаем явное исключение
                    raise RuntimeError(
                        f"Redis ACL denies channel {self._channel}. "
                        f"Grant channels ACL: &{self._channel} or &__keyspace@*__:se:<UID>:*"
                    ) from e
                # Иные ошибки RESP
                raise

            if not msg:
                continue

            raw_event = msg.get("data")
            if isinstance(raw_event, bytes):
                raw_event = raw_event.decode("utf-8", "replace")
            if self._events and raw_event not in self._events:
                continue

            payload: Optional[Any]
            if self._is_keyspace and raw_event != "del":
                try:
                    payload = self._client.get(self._key)
                except redis.RedisError:
                    payload = None
            else:
                payload = None

            if isinstance(payload, bytes):
                try:
                    decoded_payload: Optional[Any] = json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError:
                    decoded_payload = payload.decode("utf-8", "replace")
            else:
                decoded_payload = payload

            try:
                self._callback(self._key, decoded_payload, str(raw_event))
            except Exception:
                pass
