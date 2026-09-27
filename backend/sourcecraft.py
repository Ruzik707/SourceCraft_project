"""
Клиент SourceCraft: список репозиториев, доступных авторизованному пользователю.

Точный путь ручки в документации платформы может отличаться, поэтому адреса
перечислены в SOURCECRAFT_REPOS_PATHS и пробуются по очереди — первый успешный
ответ и используется. Ошибка возвращается текстом, чтобы было видно, что именно
ответила платформа.
"""
from __future__ import annotations

import logging

import httpx

from backend.config import HTTP_TIMEOUT, SOURCECRAFT_API, SOURCECRAFT_REPOS_PATHS

log = logging.getLogger(__name__)

LIST_KEYS = ("items", "repositories", "repos", "data", "results")


class SourceCraftError(RuntimeError):
    def __init__(self, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def _extract_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def normalize_repo(item: dict) -> dict | None:
    """Приводит ответ платформы к тому, что ждёт интерфейс."""
    full_path = item.get("full_path") or item.get("fullPath") or item.get("path")
    owner = item.get("owner") or (item.get("organization") or {}).get("name")
    name = item.get("name") or item.get("repo")
    if not full_path and owner and name:
        full_path = f"{owner}/{name}"
    if not full_path:
        return None
    if not owner or not name:
        owner, _, name = full_path.partition("/")
    return {
        "full_path": full_path,
        "owner": owner,
        "name": name,
        "id": str(item.get("id") or item.get("uuid") or full_path),
        "url": item.get("url") or f"https://sourcecraft.dev/{full_path}",
        "description": item.get("description"),
        "primary_language": item.get("primary_language") or item.get("language"),
        "visibility": item.get("visibility") or ("private" if item.get("is_private") else "public"),
        "role": item.get("role") or item.get("permission") or "member",
    }


async def list_user_repos(token: str) -> list[dict]:
    attempts: list[str] = []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async with httpx.AsyncClient(base_url=SOURCECRAFT_API, timeout=HTTP_TIMEOUT) as client:
        for path in SOURCECRAFT_REPOS_PATHS:
            path = path.strip()
            if not path:
                continue
            try:
                response = await client.get(path, headers=headers)
            except httpx.HTTPError as exc:
                attempts.append(f"{path}: {exc}")
                continue

            if response.status_code == 200:
                items = [normalize_repo(x) for x in _extract_items(response.json())]
                items = [x for x in items if x]
                if items:
                    log.info("Репозитории пользователя получены с %s: %s шт.", path, len(items))
                    return items
                attempts.append(f"{path}: 200, но список пуст")
            else:
                attempts.append(f"{path}: {response.status_code} {response.text[:120]}")

    raise SourceCraftError(
        "Платформа не вернула список репозиториев ни по одному из известных адресов.",
        attempts,
    )
