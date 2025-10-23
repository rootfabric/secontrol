#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
create_restricted_redis_user.py

Создаёт/обновляет Redis-пользователя с доступом только к своим ключам и каналам.

Берёт значения из существующих переменных окружения проекта:
  - REDIS_URL          — адрес Redis (например, redis://host:port/db)
  - REDIS_PORT         — порт Redis (переопределяет порт из URL, если задан)
  - REDIS_DB           — номер БД (переопределяет номер из URL, если задан)
  - REDIS_USERNAME     — UID/логин создаваемого пользователя (также ownerId)
  - REDIS_PASSWORD     — пароль создаваемого пользователя

Отдельно читает админские креденшелы:
  - REDIS_ADMIN_PASSWORD — пароль админского пользователя (обычно для «default»)
  - REDIS_ADMIN_USERNAME — (необязательно) имя админского пользователя, по умолчанию «default»

Политика доступа:
  keys:     se:<UID>:*
  channels: se:<UID>:*, se.<UID>.* и связанные служебные keyspace/keyevent каналы в заданной БД и во всех БД.

Ограничивает опасные команды и разрешает необходимый минимум для клиента.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, urlunparse
import json

import redis
from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv(usecwd=True), override=False)


def _resolve_url_with_overrides() -> tuple[str, int]:
    """
    Возвращает (resolved_url, effective_db).
    Учитывает REDIS_URL и переопределения REDIS_PORT / REDIS_DB.
    """

    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    port_env = os.getenv("REDIS_PORT")
    db_env = os.getenv("REDIS_DB")

    pu = urlparse(url)

    # Порт: переопределяем, если указан и валиден
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

    # DB: если задана — переписываем path в URL
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

    # Если DB не задана явным образом — возьмём из URL
    if effective_db is None:
        try:
            path = pu.path.lstrip("/")
            effective_db = int(path) if path else 0
        except (TypeError, ValueError):
            effective_db = 0

    return url, effective_db


def _supports(feature: str, r: redis.Redis) -> bool:
    """Проверка возможности ACL-фишек (sanitize-payload, каналов)."""
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
                "&__keyevent@0__:foo:*",
            )
        return True
    except redis.ResponseError:
        return False
    finally:
        try:
            r.execute_command("ACL", "DELUSER", tmp)
        except redis.ResponseError:
            pass


def main() -> None:
    # Достаём учётные данные будущего пользователя
    uid = os.getenv("REDIS_USERNAME")
    u_pass = os.getenv("REDIS_PASSWORD")
    if not uid or not u_pass:
        print("ERROR: Требуются REDIS_USERNAME и REDIS_PASSWORD для создаваемого пользователя.", file=sys.stderr)
        sys.exit(2)

    # Админские креды отдельно
    admin_user = os.getenv("REDIS_ADMIN_USERNAME", "default") or "default"
    admin_pass = os.getenv("REDIS_ADMIN_PASSWORD") or os.getenv("SE_REDIS_PASSWORD")
    if not admin_pass:
        print("ERROR: Укажите REDIS_ADMIN_PASSWORD (пароль админ-пользователя Redis).", file=sys.stderr)
        sys.exit(2)

    # Разбираем URL с переопределениями
    resolved_url, effective_db = _resolve_url_with_overrides()

    # Подключаемся админом
    try:
        r_admin = redis.Redis.from_url(
            resolved_url,
            username=admin_user,
            password=admin_pass,
            decode_responses=True,
        )
        r_admin.ping()
    except Exception as e:
        print(f"❌ Не удалось подключиться к Redis админом: {e}", file=sys.stderr)
        print(f"   URL: {resolved_url}; user={admin_user}")
        sys.exit(3)

    has_sanitize = _supports("sanitize", r_admin)
    has_channels = _supports("channels", r_admin)

    key_pattern = f"se:{uid}:*"

    # Шаблоны keyspace/keyevent для конкретной БД и для всех БД
    ks_db = f"__keyspace@{effective_db}__:{key_pattern}"
    ke_db = f"__keyevent@{effective_db}__:{key_pattern}"
    ks_any = f"__keyspace@*__:{key_pattern}"
    ke_any = f"__keyevent@*__:{key_pattern}"

    # Удаляем прежнего пользователя (если есть)
    try:
        r_admin.execute_command("ACL", "DELUSER", uid)
    except redis.ResponseError:
        pass

    tokens = [
        "ACL",
        "SETUSER",
        uid,
        "reset",
        "on",
        f">{u_pass}",  # пароль для нового пользователя
    ]

    if has_sanitize:
        tokens.append("sanitize-payload")

    # Разрешённые ключи
    tokens.append(f"~{key_pattern}")

    # Разрешённые каналы (если ACL каналов поддерживаются)
    if has_channels:
        tokens.extend(
            [
                # «Двоеточечная» схема
                f"&se:{uid}:*",
                # «Точечная» схема
                f"&se.{uid}.*",
                # Частые команды
                f"&se.{uid}.commands.*",
                f"&se.{uid}.commands.device.*",
                f"&se.{uid}.commands.entity.*",
                # keyspace/keyevent в текущей БД
                f"&{ks_db}",
                f"&{ke_db}",
                # и во всех БД (если на сервере включены уведомления в нескольких БД)
                f"&{ks_any}",
                f"&{ke_any}",
            ]
        )

    # Разрешённые команды (минимум для клиента)
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

    # Запрещённые команды/группы
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

    try:
        r_admin.execute_command(*tokens)
        print(f"✅ Пользователь {uid} создан/обновлён.")
        print(f"   sanitize-payload: {'ON' if has_sanitize else 'OFF'}")
        print(f"   channel ACLs (&…): {'ON' if has_channels else 'OFF'}")
        print(f"   URL: {resolved_url}  (db={effective_db})")
    except redis.ResponseError as e:
        print(f"❌ Ошибка ACL SETUSER: {e}", file=sys.stderr)
        sys.exit(4)

    # Зафиксируем права в системном ключе
    try:
        meta_key = f"se:system:players:{uid}:redis"
        meta_payload = {
            "username": uid,
            "password": u_pass,
            "key_pattern": key_pattern,
            # Отражаем основные разрешённые категории команд
            "commands": ["@read", "@write", "@pubsub"],
        }
        r_admin.set(meta_key, json.dumps(meta_payload, ensure_ascii=False))
        print(f"✅ Метаданные прав сохранены в ключ: {meta_key}")
    except Exception as e:
        print(f"⚠️ Не удалось записать ключ с правами: {e}")

    # Проверим ACL
    try:
        info = r_admin.execute_command("ACL", "GETUSER", uid)
        print("\nACL GETUSER:")
        for i in info:
            print(" ", i)
    except Exception as e:
        print(f"⚠️ Не удалось прочитать ACL GETUSER: {e}")

    # Проверим вход под созданным пользователем
    try:
        r_user = redis.Redis.from_url(
            resolved_url, username=uid, password=u_pass, decode_responses=True
        )
        r_user.ping()
        print("✅ Логин/пароль рабочего пользователя (PING ok).")
    except Exception as e:
        print(f"❌ Логин/пароль НЕ работают: {e}")


if __name__ == "__main__":
    main()
