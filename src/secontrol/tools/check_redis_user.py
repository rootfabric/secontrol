#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
check_redis_user.py

Проверяет существование Redis-пользователя и выводит его права.

Переменные окружения:
  - REDIS_URL             — адрес Redis (напр., redis://host:port/db)
  - REDIS_PORT            — порт Redis (переопределяет порт из URL, если задан)
  - REDIS_DB              — номер БД (переопределяет номер из URL, если задан)
  - REDIS_USERNAME        — UID/логин проверяемого пользователя

Админские креденшелы:
  - REDIS_ADMIN_PASSWORD  — пароль админ-пользователя Redis (обычно «default»)
  - REDIS_ADMIN_USERNAME  — имя админ-пользователя (по умолчанию «default»)
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, urlunparse

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

    # Если DB не задана явно — возьмём из URL
    if effective_db is None:
        try:
            path = pu.path.strip("/ ")
            effective_db = int(path) if path else 0
        except (TypeError, ValueError):
            effective_db = 0

    return url, effective_db


def main() -> None:
    # Достаём имя проверяемого пользователя
    uid = os.getenv("REDIS_USERNAME")
    if not uid:
        print("ERROR: Требуется REDIS_USERNAME для проверяемого пользователя.", file=sys.stderr)
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

    # Проверяем существование пользователя
    try:
        user_info = r_admin.execute_command("ACL", "GETUSER", uid)
        print(f"✅ Пользователь {uid} существует.")
        print(f"   URL: {resolved_url}  (db={effective_db})")
        print("\nACL GETUSER:")
        for item in user_info:
            print(f"  {item[0]}: {item[1]}")
    except redis.ResponseError as e:
        if "User doesn't exist" in str(e):
            print(f"❌ Пользователь {uid} не существует.")
            print(f"   URL: {resolved_url}  (db={effective_db})")
        else:
            print(f"❌ Ошибка ACL GETUSER: {e}", file=sys.stderr)
            sys.exit(4)
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
