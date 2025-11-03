#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
create_restricted_redis_user.py

Создаёт/обновляет Redis-пользователя с доступом только к своим ключам и каналам,
и сохраняет ACL в aclfile (ACL SAVE), чтобы права переживали рестарт.

Переменные окружения:
  - REDIS_URL             — адрес Redis (напр., redis://host:port/db), default: redis://127.0.0.1:6379/0
  - REDIS_PORT            — переопределение порта (необязательно)
  - REDIS_DB              — переопределение DB (необязательно)
  - REDIS_USERNAME        — UID/логин создаваемого пользователя (также ownerId)
  - REDIS_PASSWORD        — пароль создаваемого пользователя
  - REDIS_ADMIN_USERNAME  — админ-пользователь (default: "default")
  - REDIS_ADMIN_PASSWORD  — пароль админа (или SE_REDIS_PASSWORD как запасной)

Важные условия:
  - В redis.conf используйте ИЛИ aclfile, ИЛИ user ... (нельзя одновременно).
  - Если задан aclfile, файл должен существовать и быть доступен на чтение/запись.
"""

from __future__ import annotations

import os
import sys
import json
from urllib.parse import urlparse, urlunparse

import redis
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)


def _resolve_url_with_overrides() -> tuple[str, int]:
    """Возвращает (resolved_url, effective_db), учитывая REDIS_PORT / REDIS_DB."""
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    port_env = os.getenv("REDIS_PORT")
    db_env = os.getenv("REDIS_DB")

    pu = urlparse(url)

    # Порт
    try:
        if port_env is not None:
            port_val = int(port_env)
            if port_val > 0:
                netloc = pu.hostname or "127.0.0.1"
                if pu.username and pu.password:
                    auth = f"{pu.username}:{pu.password}@"
                elif pu.username:
                    auth = f"{pu.username}@"
                else:
                    auth = ""
                url = urlunparse((pu.scheme, f"{auth}{netloc}:{port_val}", pu.path, pu.params, pu.query, pu.fragment))
                pu = urlparse(url)
    except (TypeError, ValueError):
        pass

    # База
    effective_db = None
    try:
        if db_env is not None:
            db_val = int(db_env)
            if db_val >= 0:
                effective_db = db_val
                url = urlunparse((pu.scheme, pu.netloc, f"/{db_val}", pu.params, pu.query, pu.fragment))
                pu = urlparse(url)
    except (TypeError, ValueError):
        pass

    if effective_db is None:
        try:
            path = pu.path.strip("/ ")
            effective_db = int(path) if path else 0
        except (TypeError, ValueError):
            effective_db = 0

    return url, effective_db


def _supports(feature: str, r: redis.Redis) -> bool:
    """Проверяет поддержку конкретной ACL-фичи сервером (Redis 7+): sanitize-payload, channel ACL (&...)."""
    tmp = "__tmp_acl_probe__"
    try:
        r.execute_command("ACL", "DELUSER", tmp)
    except redis.ResponseError:
        pass
    try:
        if feature == "sanitize":
            r.execute_command("ACL", "SETUSER", tmp, "reset", "on", "sanitize-payload", ">x")
        elif feature == "channels":
            r.execute_command(
                "ACL",
                "SETUSER",
                tmp,
                "reset",
                "on",
                ">x",
                "&foo:*",
                "&__keyspace@0__:foo:*",
                "&__keyevent@0__:*",
            )
        return True
    except redis.ResponseError:
        return False
    finally:
        try:
            r.execute_command("ACL", "DELUSER", tmp)
        except redis.ResponseError:
            pass


def _get_aclfile_path(r: redis.Redis) -> str | None:
    """Возвращает путь aclfile через CONFIG GET, либо None если недоступно/не задано."""
    try:
        res = r.execute_command("CONFIG", "GET", "aclfile")
        if isinstance(res, (list, tuple)) and len(res) == 2 and res[0] == "aclfile":
            path = res[1]
            return path or None
    except redis.ResponseError:
        return None
    except Exception:
        return None
    return None


def _acl_save(r: redis.Redis) -> bool:
    """Выполняет ACL SAVE, возвращает True при успехе."""
    try:
        r.execute_command("ACL", "SAVE")
        return True
    except Exception as e:
        print(f"⚠️ ACL SAVE failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    uid = os.getenv("REDIS_USERNAME")
    u_pass = os.getenv("REDIS_PASSWORD")

    if not uid or not u_pass:
        print("ERROR: Требуются REDIS_USERNAME и REDIS_PASSWORD.", file=sys.stderr)
        sys.exit(2)

    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD") or os.getenv("SE_REDIS_PASSWORD")
    if not admin_pass:
        print("ERROR: Укажите REDIS_ADMIN_PASSWORD (пароль админа).", file=sys.stderr)
        sys.exit(2)

    resolved_url, effective_db = _resolve_url_with_overrides()

    # Подключение админом
    try:
        r_admin = redis.Redis.from_url(
            resolved_url, username=admin_user, password=admin_pass, decode_responses=True
        )
        r_admin.ping()
    except Exception as e:
        print(f"❌ Не удалось подключиться к Redis админом: {e}", file=sys.stderr)
        print(f"   URL: {resolved_url}; user={admin_user}")
        sys.exit(3)

    has_sanitize = _supports("sanitize", r_admin)
    has_channels = _supports("channels", r_admin)
    aclfile_path = _get_aclfile_path(r_admin)

    if not aclfile_path:
        print("⚠️ Внимание: aclfile не настроен или CONFIG запрещён.", file=sys.stderr)
        print("   Если в redis.conf указан aclfile, убедитесь что файл существует и доступен пользователю 'redis'.")
    else:
        print(f"aclfile: {aclfile_path}")

    key_pattern = f"se:{uid}:*"
    ks_db = f"__keyspace@{effective_db}__:{key_pattern}"
    ks_any = f"__keyspace@*__:{key_pattern}"
    ke_db_all = f"__keyevent@{effective_db}__:*"
    ke_any_all = f"__keyevent@*__:*"

    # Снесём прежнего одноимённого пользователя (не критично, если нет)
    try:
        r_admin.execute_command("ACL", "DELUSER", uid)
    except redis.ResponseError:
        pass

    tokens: list[str] = [
        "ACL", "SETUSER", uid,
        "reset",
        "on",
        f">{u_pass}",
    ]

    if has_sanitize:
        tokens.append("sanitize-payload")

    # Ключи
    tokens.append(f"~{key_pattern}")
    # Каналы
    if has_channels:
        tokens.extend(
            [
                f"&se:{uid}:*",
                f"&se.{uid}.*",
                f"&se.{uid}.commands.*",
                f"&se.{uid}.commands.device.*",
                f"&se.{uid}.commands.entity.*",
                f"&{ks_db}",
                f"&{ks_any}",
                f"&{ke_db_all}",
                f"&{ke_any_all}",
            ]
        )

    # Разрешённые команды (минимально достаточные)
    tokens.extend(
        [
            "+@read",
            "+@write",
            "+@pubsub",
            "+publish",
            "+ping",
            "+hello",
            "+select",
            "+info",
            "+echo",
            "+time",
            "+role",
            "+client|setname",
            "+client|getname",
            "+client|id",
            "+client|info",
            "+subscribe",
            "+psubscribe",
        ]
    )

    # Жёсткие запреты
    tokens.extend(
        [
            "-keys",
            "-scan",
            "-randomkey",
            "-dbsize",
            "-monitor",
            "-config",
            "-command",
            "-acl",
            "-@dangerous",
            "-@admin",
            "-eval",
            "-evalsha",
            "-script",
            "-migrate",
            "-move",
            "-flushall",
            "-flushdb",
            "-rename",
            "-renamenx",
            "-unlink",
            "-expire",
            "-pexpire",
            "-expireat",
            "-pexpireat",
            "-persist",
        ]
    )

    # Применяем правила
    try:
        r_admin.execute_command(*tokens)
        print(f"✅ Пользователь {uid} создан/обновлён.")
        print(f"   sanitize-payload: {'ON' if has_sanitize else 'OFF'}")
        print(f"   channel ACLs (&…): {'ON' if has_channels else 'OFF'}")
        print(f"   URL: {resolved_url}  (db={effective_db})")
    except redis.ResponseError as e:
        print(f"❌ Ошибка ACL SETUSER: {e}", file=sys.stderr)
        sys.exit(4)

    # Информационный ключ (не обязателен)
    try:
        meta_key = f"se:system:players:{uid}:redis"
        meta_payload = {
            "username": uid,
            "password": u_pass,
            "key_pattern": key_pattern,
            "commands": ["@read", "@write", "@pubsub"],
        }
        r_admin.set(meta_key, json.dumps(meta_payload, ensure_ascii=False))
        print(f"✅ Метаданные прав сохранены в ключ: {meta_key}")
    except Exception as e:
        print(f"⚠️ Не удалось записать метаданные: {e}")

    # Печать ACL GETUSER
    try:
        info = r_admin.execute_command("ACL", "GETUSER", uid)
        print("\nACL GETUSER:")
        for i in info:
            print(" ", i)
    except Exception as e:
        print(f"⚠️ Не удалось прочитать ACL GETUSER: {e}")

    # Сохранить ACL на диск
    if aclfile_path:
        if _acl_save(r_admin):
            print(f"💾 ACL сохранены в файл: {aclfile_path}")
        else:
            print("⚠️ Не удалось сохранить ACL. Проверьте права/путь aclfile.", file=sys.stderr)
    else:
        # Возможно CONFIG запрещён, но aclfile настроен — попробуем всё равно
        if _acl_save(r_admin):
            print("💾 ACL сохранены (aclfile возможно настроен, но CONFIG GET недоступен).")
        else:
            print("⚠️ Похоже, aclfile не настроен — после рестарта пользователь может исчезнуть.", file=sys.stderr)

    # Проверка логина новым пользователем
    try:
        r_user = redis.Redis.from_url(resolved_url, username=uid, password=u_pass, decode_responses=True)
        r_user.ping()
        print("✅ Логин/пароль рабочего пользователя (PING ok).")
    except Exception as e:
        print(f"❌ Логин/пароль НЕ работают: {e}")


if __name__ == "__main__":
    main()
