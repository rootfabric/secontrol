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


def _coerce_bytes(value: Any) -> Optional[bytes]:
    """Return ``value`` as bytes when possible."""

    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    except Exception:
        return str(value).encode("utf-8")


def _read_key_value(
    client: redis.Redis,
    key: str,
    *,
    raise_on_error: bool = False,
) -> Optional[bytes]:
    """Fetch raw key value handling RedisJSON documents."""

    try:
        result = client.get(key)
    except redis.ResponseError as exc:
        message = str(exc)
        if "WRONGTYPE" not in message.upper():
            if raise_on_error:
                raise RuntimeError(f"Failed to read key {key!r}: {exc}") from exc
            return None
        try:
            json_result = client.execute_command("JSON.GET", key)
        except redis.RedisError as json_exc:
            if raise_on_error:
                raise RuntimeError(f"Failed to read JSON key {key!r}: {json_exc}") from json_exc
            return None
        return _coerce_bytes(json_result)
    except redis.RedisError as exc:
        if raise_on_error:
            raise RuntimeError(f"Failed to read key {key!r}: {exc}") from exc
        return None

    return _coerce_bytes(result)


def _is_subgrid(grid_info: dict) -> bool:
    """Best-effort detection whether a grid descriptor represents a sub-grid.

    Different Space Engineers bridges expose slightly different fields. We try several
    common markers and fall back to assuming it's a main grid when unsure.
    """
    if not isinstance(grid_info, dict):
        return False

    # 1) Explicit boolean flags
    for key in ("isSubgrid", "isSubGrid", "is_subgrid", "is_sub_grid"):
        val = grid_info.get(key)
        if isinstance(val, bool):
            return val is True
        if isinstance(val, (int, float)):
            return bool(val)

    # 2) Inverse of "isMainGrid" if present
    val = grid_info.get("isMainGrid")
    if isinstance(val, bool):
        return not val
    if isinstance(val, (int, float)):
        return not bool(val)

    # 3) Relationship by id: if main/root/top grid id differs from own id -> sub-grid
    own_id = grid_info.get("id")
    for rel in ("mainGridId", "rootGridId", "topGridId", "parentGridId", "parentId"):
        rel_id = grid_info.get(rel)
        if rel_id is not None and own_id is not None and str(rel_id) != str(own_id):
            return True

    # If no markers matched, treat as main grid
    return False


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
        # Debug print only when explicitly enabled via env
        try:
            import os as _os
            dbg = (_os.getenv("SECONTROL_DEBUG") or _os.getenv("SE_DEBUG") or _os.getenv("SEC_DEBUG") or "").strip().lower()
            if dbg in {"1", "true", "yes", "on"}:
                print(f"[redis] db_index={self._db_index}")
        except Exception:
            pass
        self._subscriptions: list[_PubSubSubscription] = []

    # ------------------------------------------------------------------
    # Basic Redis helpers
    # ------------------------------------------------------------------
    def get_value(self, key: str) -> Optional[bytes]:
        return _read_key_value(self._client, key, raise_on_error=True)

    def get_json(self, key: str) -> Optional[Any]:
        value = _read_key_value(self._client, key)
        if value is None:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def list_grids(self, owner_id: str | int, *, key: str | None = None, exclude_subgrids: bool = True) -> list[Dict[str, Any]]:
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

        filtered_grids = grids
        if exclude_subgrids:
            filtered_grids = [grid for grid in grids if not _is_subgrid(grid)]

        return [grid for grid in filtered_grids if isinstance(grid, dict)]

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
    def subscribe_to_key(
        self,
        key: str,
        callback: CallbackType,
        *,
        events: Iterable[str] | None = None,
    ) -> "_PubSubSubscription":
        channel = f"__keyspace@{self._db_index}__:{key}"
        if events is None:
            events_tuple: Optional[tuple[str, ...]] = (
                "set",
                "setrange",
                "append",
                "hset",
                "hmset",
                "hdel",
                "del",
                "unlink",
                "expired",
                "evicted",
                "json.set",
                "json.mset",
                "json.merge",
                "json.clear",
                "json.arrappend",
                "json.arrinsert",
                "json.arrpop",
                "json.arrtrim",
                "json.toggle",
                "json.numincrby",
                "json.nummultby",
                "json.strappend",
                "json.del",
                "json.forget",
            )
        else:
            events_tuple = tuple(events)
        subscription = _PubSubSubscription(
            self._client,
            channel,
            key,
            callback,
            events_tuple,
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

    def subscribe_to_key_resilient(self, key: str, callback: CallbackType, *,
                                   events: Iterable[str] | None = None) -> object:
        """Subscribe to a key with multiple fallbacks.

        Combines keyspace notifications, a direct channel subscribe to ``key``
        (for setups that PUBLISH telemetry to the same name), and a lightweight
        polling loop. A small de-duplication window prevents double-calling
        when multiple paths deliver the same payload close in time.
        """

        # Initialize shared last payload
        last_payload = {"ts": 0.0, "payload": None}

        def _dispatch(_key: str, payload: Optional[Any], event_name: str) -> None:
            import time as _t, json as _json
            ts = _t.monotonic()
            try:
                # Normalize payload for comparison
                norm = payload
                if isinstance(payload, (dict, list)):
                    try:
                        norm = _json.dumps(payload, sort_keys=True, ensure_ascii=False)
                    except Exception:
                        pass
                elif isinstance(payload, (bytes, bytearray)):
                    norm = bytes(payload).decode("utf-8", "replace")
                elif payload is None:
                    norm = None

                # Skip duplicates within 100ms having the same normalized payload
                if last_payload["payload"] == norm and (ts - float(last_payload["ts"])) < 0.1:
                    return

                last_payload["payload"] = norm
                last_payload["ts"] = ts
            except Exception:
                # On any issue, still forward the event
                pass

            try:
                callback(_key, payload, event_name)
            except Exception:
                pass

        # Preferred: keyspace subscription
        if events:
            kept_events = tuple(events)
        else:
            kept_events = (
                "set",
                "setrange",
                "append",
                "hset",
                "hmset",
                "hdel",
                "del",
                "unlink",
                "expired",
                "evicted",
                "json.set",
                "json.mset",
                "json.merge",
                "json.clear",
                "json.arrappend",
                "json.arrinsert",
                "json.arrpop",
                "json.arrtrim",
                "json.toggle",
                "json.numincrby",
                "json.nummultby",
                "json.strappend",
                "json.del",
                "json.forget",
            )

        ks_channel = f"__keyspace@{self._db_index}__:{key}"
        ks_sub = _PubSubSubscription(
            self._client,
            ks_channel,
            key,
            _dispatch,
            kept_events,
            is_pattern=False,
            is_keyspace=True,
        )
        ks_sub.start()

        subs = [ks_sub]

        # Also subscribe to the direct channel named as the key itself.
        # Some Space Engineers bridges publish telemetry frames via PUBLISH
        # into the telemetry key channel without touching the key value.
        try:
            ch_sub = _PubSubSubscription(
                self._client,
                key,        # channel name equals the telemetry key
                key,
                _dispatch,
                None,
                is_pattern=False,
                is_keyspace=False,
            )
            ch_sub.start()
            subs.append(ch_sub)
        except Exception:
            # Channel subscribe may be denied by ACL; continue with other paths
            pass

        # Fallback: polling
        # Safety net to catch missed notifications or disabled keyspace events
        poller = _PollingSubscription(self._client, key, _dispatch, interval=0.01)
        poller.start()
        subs.append(poller)

        composite = _CompositeSubscription(subs)
        self._subscriptions.append(composite)
        return composite

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
        delete_events = {
            "del",
            "expired",
            "unlink",
            "evicted",
            "json.del",
            "json.forget",
        }

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

            if self._is_keyspace:
                payload: Optional[Any]
                if raw_event not in delete_events:
                    payload = _read_key_value(self._client, self._key)
                else:
                    payload = None

                if isinstance(payload, bytes):
                    try:
                        decoded_payload: Optional[Any] = json.loads(payload.decode("utf-8"))
                    except json.JSONDecodeError:
                        decoded_payload = payload.decode("utf-8", "replace")
                else:
                    decoded_payload = payload

                event_name = str(raw_event)
            else:
                decoded_payload = raw_event
                if isinstance(decoded_payload, str):
                    stripped = decoded_payload.strip()
                    if stripped:
                        try:
                            decoded_payload = json.loads(stripped)
                        except json.JSONDecodeError:
                            decoded_payload = stripped
                    else:
                        decoded_payload = stripped
                event_name = "message"

            try:
                self._callback(self._key, decoded_payload, event_name)
            except Exception:
                pass


class _PollingSubscription:
    """Periodic GET of a key to detect changes when notifications are delayed/missing.

    Calls the provided callback with event_name "poll" when a change is detected.
    """

    def __init__(self, client: redis.Redis, key: str, callback: CallbackType, *, interval: float = 0.01) -> None:
        self._client = client
        self._key = key
        self._callback = callback
        self._interval = max(0.001, float(interval))
        self._thread = threading.Thread(target=self._run, name=f"redis-poll-{key}", daemon=True)
        self._stop_event = threading.Event()
        self._last_norm: Any = object()

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        import time as _t
        while not self._stop_event.is_set():
            try:
                raw = self._client.get(self._key)
            except Exception:
                raw = None

            if isinstance(raw, (bytes, bytearray)):
                try:
                    decoded: Optional[Any] = json.loads(bytes(raw).decode("utf-8"))
                except Exception:
                    decoded = bytes(raw).decode("utf-8", "replace")
            else:
                decoded = raw

            # Normalize for comparison
            norm = decoded
            if isinstance(decoded, (dict, list)):
                try:
                    norm = json.dumps(decoded, sort_keys=True, ensure_ascii=False)
                except Exception:
                    pass

            if norm != self._last_norm:
                self._last_norm = norm
                try:
                    self._callback(self._key, decoded, "poll")
                except Exception:
                    pass

            self._stop_event.wait(self._interval)


class _CompositeSubscription:
    """A simple wrapper that closes multiple subscriptions at once."""

    def __init__(self, subs: list[object]) -> None:
        self._subs = list(subs)

    def close(self) -> None:
        for s in list(self._subs):
            try:
                # Each sub exposes .close()
                s.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._subs.clear()


    
