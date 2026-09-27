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

from backend.config import (HTTP_TIMEOUT, SOURCECRAFT_API, SOURCECRAFT_AUTH_HEADER,
                            SOURCECRAFT_AUTH_TEMPLATE, SOURCECRAFT_ORG_PATHS,
                            SOURCECRAFT_ORG_REPOS_TEMPLATES, SOURCECRAFT_REPOS_PATHS)

log = logging.getLogger(__name__)

LIST_KEYS = ("items", "repositories", "repos", "organizations", "orgs", "data", "results")

# Роли, при которых репозиторий считается своим, а не просто доступным
OWNER_ROLES = {"owner", "admin", "maintainer", "administrator"}


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

    # 1. Ищем владельца и имя с учетом ключа slug
    org = item.get("organization") or {}
    owner = item.get("owner") or org.get("slug") or org.get("name")
    name = item.get("name") or item.get("slug") or item.get("repo")

    if not full_path and owner and name:
        full_path = f"{owner}/{name}"
    if not full_path:
        return None
    if not owner or not name:
        owner, _, name = full_path.partition("/")

    # 2. ИСПРАВЛЕНИЕ: Защита от объекта в поле языка (чтобы React не падал)
    lang_raw = item.get("primary_language") or item.get("language")
    if isinstance(lang_raw, dict):
        primary_language = lang_raw.get("name")
    else:
        primary_language = lang_raw

    return {
        "full_path": full_path,
        "owner": owner,
        "name": name,
        "id": str(item.get("id") or item.get("uuid") or full_path),
        "url": item.get("url") or f"https://sourcecraft.dev/{full_path}",
        "description": item.get("description"),
        "primary_language": primary_language,
        "visibility": item.get("visibility") or ("private" if item.get("is_private") else "public"),
        "role": item.get("role") or item.get("permission") or "member",
    }


def auth_headers(token: str) -> dict[str, str]:
    """Заголовок авторизации платформы. Вид задаётся настройками: точная схема
    подбирается скриптом tools/probe_sourcecraft.py."""
    return {
        SOURCECRAFT_AUTH_HEADER: SOURCECRAFT_AUTH_TEMPLATE.format(t=token),
        "Accept": "application/json",
    }


async def _get_items(client: httpx.AsyncClient, path: str, headers: dict,
                     attempts: list[str]) -> list[dict]:
    try:
        response = await client.get(path, headers=headers)
    except httpx.HTTPError as exc:
        attempts.append(f"{path}: {exc}")
        return []
    if response.status_code != 200:
        attempts.append(f"{path}: {response.status_code} {response.text[:120]}")
        return []
    try:
        return _extract_items(response.json())
    except ValueError:
        attempts.append(f"{path}: 200, но ответ не JSON")
        return []


async def _org_slugs(client: httpx.AsyncClient, headers: dict, attempts: list[str]) -> list[str]:
    slugs: list[str] = []
    for path in SOURCECRAFT_ORG_PATHS:
        path = path.strip()
        if not path.startswith("/me"):
            # Защита от глобальных списков: они вернут чужие организации
            log.warning("Адрес организаций %s не в области пользователя — пропускаем", path)
            continue
        for org in await _get_items(client, path, headers, attempts):
            slug = org.get("slug") or org.get("name") or org.get("login")
            if slug and str(slug) not in slugs:
                slugs.append(str(slug))
    return slugs


async def list_user_repos(token: str, login: str | None = None) -> list[dict]:
    """Репозитории пользователя.

    Платформа отдаёт по /me/repos в том числе просто доступные и недавно открытые
    проекты — среди них бывают чужие. Поэтому сначала собираем репозитории
    организаций пользователя (это и есть «его» проекты), а список доступных
    добавляем следом и помечаем, чтобы в кабинете было видно, что это не своё.
    """
    attempts: list[str] = []
    headers = auth_headers(token)
    collected: dict[str, dict] = {}

    async with httpx.AsyncClient(base_url=SOURCECRAFT_API, timeout=HTTP_TIMEOUT) as client:
        for slug in await _org_slugs(client, headers, attempts):
            for template in SOURCECRAFT_ORG_REPOS_TEMPLATES:
                items = await _get_items(client, template.strip().format(slug=slug),
                                         headers, attempts)
                for raw in items:
                    repo = normalize_repo(raw)
                    if repo:
                        # Организация получена из области пользователя, значит проект его
                        repo["source"] = "organization"
                        collected.setdefault(repo["full_path"], repo)
                if items:
                    log.info("Организация %s: %s репозиториев", slug, len(items))
                    break

        for path in SOURCECRAFT_REPOS_PATHS:
            for raw in await _get_items(client, path.strip(), headers, attempts):
                repo = normalize_repo(raw)
                if not repo:
                    continue
                own = (login and repo["owner"] == login) or \
                    str(repo.get("role", "")).lower() in OWNER_ROLES
                repo["source"] = "organization" if own else "accessible"
                collected.setdefault(repo["full_path"], repo)

    if not collected:
        raise SourceCraftError(
            "Платформа не вернула список репозиториев ни по одному из известных адресов.",
            attempts,
        )

    repos = list(collected.values())
    repos.sort(key=lambda r: (r.get("source") != "organization", r["full_path"]))
    log.info("Итого репозиториев пользователя: %s (своих: %s)",
             len(repos), sum(1 for r in repos if r.get("source") == "organization"))
    return repos
