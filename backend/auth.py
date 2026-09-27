"""
Авторизация через Я ID.

Поток: фронт уводит пользователя на /auth/yandex/login → сервис редиректит на
страницу согласия Яндекса → Яндекс возвращает код на /auth/yandex/callback →
сервис меняет код на токен, читает профиль, заводит сессию и возвращает
пользователя на фронт с токеном сессии.

Пока приложение в Яндекс OAuth не заведено (нет client_id), работает демо-вход:
сессия выдаётся сразу, профиль помечается provider=demo. На публичном стенде
выключается переменной ALLOW_DEMO_AUTH=false.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Header, HTTPException
from sqlalchemy import select

from backend.config import (ALLOW_DEMO_AUTH, HTTP_TIMEOUT, SECRET_KEY, SESSION_TTL_HOURS,
                            YANDEX_AUTHORIZE_URL, YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET,
                            YANDEX_INFO_URL, YANDEX_TOKEN_URL)
from backend.db import User, UserSession, session_scope, utcnow

log = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600


def yandex_configured() -> bool:
    """Есть ли хоть какой-то рабочий вход через Яндекс."""
    return bool(YANDEX_CLIENT_ID)


def code_flow_available() -> bool:
    """Code-поток требует секрета приложения; без него используется implicit."""
    return bool(YANDEX_CLIENT_ID and YANDEX_CLIENT_SECRET)


# ─────────────────────────────── state ───────────────────────────────────────
def _sign(payload: bytes) -> str:
    digest = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_state(redirect_uri: str, next_path: str = "/dashboard") -> str:
    payload = json.dumps({
        "redirect_uri": redirect_uri,
        "next": next_path,
        "nonce": secrets.token_urlsafe(8),
        "exp": int((utcnow() + timedelta(seconds=STATE_TTL_SECONDS)).timestamp()),
    }, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_sign(payload)}"


def read_state(state: str) -> dict:
    try:
        body, signature = state.split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(400, {"code": "bad_state", "message": "Некорректный параметр state."}) from exc

    if not hmac.compare_digest(signature, _sign(payload)):
        raise HTTPException(400, {"code": "bad_state", "message": "Подпись state не совпала."})

    data = json.loads(payload)
    if data.get("exp", 0) < int(utcnow().timestamp()):
        raise HTTPException(400, {"code": "state_expired", "message": "Ссылка входа устарела, попробуйте ещё раз."})
    return data


# ─────────────────────────────── поток входа ─────────────────────────────────
def callback_uri() -> str:
    """Адрес, который вызывает Яндекс после согласия. Регистрируется в приложении."""
    from backend.config import API_PREFIX, PUBLIC_API_URL
    return f"{PUBLIC_API_URL.rstrip('/')}{API_PREFIX}/auth/yandex/callback"


def implicit_url(frontend_callback: str, next_path: str) -> str:
    """Ссылка на согласие для implicit-потока.

    Яндекс вернёт токен прямо на фронт во фрагменте адреса. Секрет приложения не
    нужен, поэтому этот путь работает сразу; redirect_uri обязан совпадать с тем,
    что зарегистрирован в приложении, — отсюда адрес без параметров запроса.
    """
    from urllib.parse import urlencode
    params = {
        "response_type": "token",
        "client_id": YANDEX_CLIENT_ID,
        "redirect_uri": frontend_callback,
        "state": next_path,
    }
    return f"{YANDEX_AUTHORIZE_URL}?{urlencode(params)}"


def authorize_url(frontend_redirect: str, next_path: str = "/dashboard") -> str:
    """Ссылка на страницу согласия. Куда вернуть пользователя — помним в state."""
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": YANDEX_CLIENT_ID,
        "redirect_uri": callback_uri(),
        "state": make_state(frontend_redirect, next_path),
        # login:info — профиль, login:email — почта для отображения в кабинете
        "scope": "login:info login:email",
        "force_confirm": "yes",
    }
    return f"{YANDEX_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(YANDEX_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": YANDEX_CLIENT_ID,
            "client_secret": YANDEX_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        })
    if response.status_code != 200:
        log.warning("Яндекс OAuth отказал: %s %s", response.status_code, response.text[:300])
        raise HTTPException(502, {
            "code": "oauth_failed",
            "message": "Яндекс ID не выдал токен доступа. Попробуйте войти ещё раз.",
        })
    return response.json()


async def fetch_profile(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(YANDEX_INFO_URL, params={"format": "json"},
                                    headers={"Authorization": f"OAuth {access_token}"})
    if response.status_code != 200:
        raise HTTPException(502, {
            "code": "profile_failed",
            "message": "Не удалось получить профиль Яндекс ID.",
        })
    return response.json()


# ─────────────────────────────── сессии ──────────────────────────────────────
def upsert_user(profile: dict, provider: str = "yandex_id") -> User:
    provider_user_id = str(profile.get("id") or profile.get("login") or uuid.uuid4())
    with session_scope() as session:
        user = session.scalars(
            select(User).where(User.provider == provider,
                               User.provider_user_id == provider_user_id)
        ).first()
        if user is None:
            user = User(id=str(uuid.uuid4()), provider=provider, provider_user_id=provider_user_id)
            session.add(user)
        user.login = str(profile.get("login") or provider_user_id)
        user.display_name = str(profile.get("real_name") or profile.get("display_name")
                                or profile.get("login") or "Пользователь")
        user.email = profile.get("default_email") or (profile.get("emails") or [None])[0]
        avatar = profile.get("default_avatar_id")
        user.avatar_url = f"https://avatars.yandex.net/get-yapic/{avatar}/islands-200" if avatar else None
        session.flush()
        return user


def create_session(user: User, yandex_token: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    with session_scope() as session:
        session.add(UserSession(
            token=token,
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=SESSION_TTL_HOURS),
            yandex_token=yandex_token,
        ))
    return token


def demo_login() -> tuple[User, str]:
    """Вход без приложения Яндекс OAuth — только для стенда."""
    if not ALLOW_DEMO_AUTH:
        raise HTTPException(503, {
            "code": "auth_not_configured",
            "message": "Вход через Я ID не настроен: не заданы YANDEX_CLIENT_ID и YANDEX_CLIENT_SECRET.",
        })
    log.warning("Выдана демо-сессия: приложение Яндекс OAuth не настроено")
    user = upsert_user({"id": "demo", "login": "demo-user", "real_name": "Demo User",
                        "default_email": "demo-user@example.com"}, provider="demo")
    return user, create_session(user)


def resolve_session(token: str | None) -> tuple[User, UserSession] | None:
    if not token:
        return None
    with session_scope() as session:
        row = session.get(UserSession, token)
        if row is None:
            return None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            session.delete(row)
            return None
        user = session.get(User, row.user_id)
        return (user, row) if user else None


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else authorization


async def adopt_yandex_token(token: str) -> tuple[User, UserSession] | None:
    """Принять токен, выданный Яндексом напрямую (implicit-поток).

    Проверяем его в Яндекс ID, заводим пользователя и сохраняем сам токен как
    сессию: повторные запросы уже не ходят наружу.
    """
    try:
        profile = await fetch_profile(token)
    except HTTPException:
        return None

    user = upsert_user(profile)
    with session_scope() as session:
        if session.get(UserSession, token) is None:
            session.add(UserSession(
                token=token,
                user_id=user.id,
                expires_at=utcnow() + timedelta(hours=SESSION_TTL_HOURS),
                yandex_token=token,
            ))
    return resolve_session(token)


async def require_user(authorization: str | None = Header(default=None)) -> tuple[User, UserSession]:
    """Зависимость FastAPI: сессия сервиса либо токен Яндекс ID."""
    token = bearer_token(authorization)
    resolved = resolve_session(token)
    if resolved is None and token:
        resolved = await adopt_yandex_token(token)
    if resolved is None:
        raise HTTPException(401, {
            "code": "unauthorized",
            "message": "Сессия истекла. Войдите через Я ID ещё раз.",
        })
    return resolved


async def optional_user(authorization: str | None = Header(default=None)):
    """Как require_user, но без ошибки: нужна там, где страница доступна и гостю."""
    token = bearer_token(authorization)
    resolved = resolve_session(token)
    if resolved is None and token:
        resolved = await adopt_yandex_token(token)
    return resolved


def logout(token: str | None) -> None:
    if not token:
        return
    with session_scope() as session:
        row = session.get(UserSession, token)
        if row is not None:
            session.delete(row)
