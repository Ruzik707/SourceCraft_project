"""
Клиент SourceCraft: профиль пользователя, его организации и репозитории.

Форматы проверены на живом API 27.09.2026 (tools/dump_my_repos.py):

    Authorization: Bearer <личный токен доступа>
    GET /user                  → профиль: {id, username, display_name, ...}
    GET /me/orgs               → {"organizations": [{slug, display_name, visibility}]}
    GET /orgs/{slug}/repos     → {"repositories": [...], "next_page_token": "..."}

Важно: /me/repos отдаёт не все репозитории пользователя — в выдаче были только
проекты одной организации, а личные отсутствовали. Поэтому список собирается по
организациям, а /me/repos добавляется как дополнительный источник.
"""
from __future__ import annotations

import logging

import httpx

from backend.config import (HTTP_TIMEOUT, SOURCECRAFT_API, SOURCECRAFT_AUTH_HEADER,
                            SOURCECRAFT_AUTH_TEMPLATE, SOURCECRAFT_ORG_PATHS,
                            SOURCECRAFT_ORG_REPOS_TEMPLATES, SOURCECRAFT_PROFILE_PATH,
                            SOURCECRAFT_REPOS_PATHS)

log = logging.getLogger(__name__)

PAGE_SIZE = 100
MAX_PAGES = 20


class SourceCraftError(RuntimeError):
    def __init__(self, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def auth_headers(token: str) -> dict[str, str]:
    """Заголовок авторизации платформы; вид задаётся настройками."""
    return {
        SOURCECRAFT_AUTH_HEADER: SOURCECRAFT_AUTH_TEMPLATE.format(t=token),
        "Accept": "application/json",
    }


def _items(payload, *keys: str) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def normalize_repo(item: dict, org_slug: str | None = None) -> dict | None:
    """Ответ платформы → структура, которую ждёт интерфейс.

    Платформа не отдаёт full_path: путь собирается из slug организации и slug
    репозитория. Языка в ответе тоже нет — он берётся из витрины, если
    репозиторий уже анализировался.
    """
    org = item.get("organization") or {}
    owner = org.get("slug") or org.get("name") or org_slug or item.get("owner")
    name = item.get("slug") or item.get("name")
    full_path = item.get("full_path") or (f"{owner}/{name}" if owner and name else None)
    if not full_path:
        return None
    if not owner or not name:
        owner, _, name = full_path.partition("/")

    language = item.get("primary_language") or item.get("language")
    if isinstance(language, dict):
        language = language.get("name")

    rating = item.get("rating") or {}
    return {
        "full_path": full_path,
        "owner": owner,
        "name": name,
        "id": str(item.get("id") or full_path),
        "url": item.get("web_url") or item.get("url") or f"https://sourcecraft.dev/{full_path}",
        "description": item.get("description") or None,
        "primary_language": language,
        "visibility": item.get("visibility") or ("private" if item.get("is_private") else "public"),
        "likes": float(rating.get("value") or 0),
        "is_empty": bool(item.get("is_empty")),
        "default_branch": item.get("default_branch") or None,
        "organization": owner,
    }


async def _get(client: httpx.AsyncClient, path: str, headers: dict,
               attempts: list[str], params: dict | None = None):
    try:
        response = await client.get(path, headers=headers, params=params)
    except httpx.HTTPError as exc:
        attempts.append(f"{path}: {type(exc).__name__}")
        return None
    if response.status_code != 200:
        attempts.append(f"{path}: {response.status_code}")
        return None
    try:
        return response.json()
    except ValueError:
        attempts.append(f"{path}: ответ не JSON")
        return None


async def _paged(client: httpx.AsyncClient, path: str, headers: dict,
                 attempts: list[str]) -> list[dict]:
    """Постраничный обход: платформа отдаёт next_page_token."""
    collected: list[dict] = []
    token = ""
    for _ in range(MAX_PAGES):
        params = {"page_size": PAGE_SIZE}
        if token:
            params["page_token"] = token
        payload = await _get(client, path, headers, attempts, params)
        if payload is None:
            break
        collected.extend(_items(payload, "repositories", "repos", "items"))
        token = (payload or {}).get("next_page_token") or ""
        if not token:
            break
    return collected


async def fetch_profile(client: httpx.AsyncClient, headers: dict,
                        attempts: list[str]) -> dict | None:
    payload = await _get(client, SOURCECRAFT_PROFILE_PATH, headers, attempts)
    return payload if isinstance(payload, dict) else None


async def fetch_organizations(client: httpx.AsyncClient, headers: dict,
                              attempts: list[str]) -> list[dict]:
    orgs: list[dict] = []
    seen: set[str] = set()
    for path in SOURCECRAFT_ORG_PATHS:
        path = path.strip()
        if not path.startswith("/me"):
            # Глобальные списки вернут чужие организации — не берём
            log.warning("Адрес организаций %s вне области пользователя, пропускаем", path)
            continue
        payload = await _get(client, path, headers, attempts)
        for org in _items(payload, "organizations", "orgs", "items"):
            slug = org.get("slug") or org.get("name")
            if slug and slug not in seen:
                seen.add(str(slug))
                orgs.append({"slug": str(slug),
                             "display_name": org.get("display_name") or str(slug),
                             "visibility": org.get("visibility") or "public"})
    return orgs


async def list_user_repos(token: str, login: str | None = None) -> list[dict]:
    """Все репозитории, доступные пользователю в SourceCraft.

    Собираются по его организациям; личная организация идёт первой.
    """
    attempts: list[str] = []
    headers = auth_headers(token)
    collected: dict[str, dict] = {}

    async with httpx.AsyncClient(base_url=SOURCECRAFT_API,
                                 timeout=httpx.Timeout(HTTP_TIMEOUT, connect=25.0)) as client:
        profile = await fetch_profile(client, headers, attempts)
        username = (profile or {}).get("username") or login

        organizations = await fetch_organizations(client, headers, attempts)
        log.info("Организации пользователя: %s",
                 ", ".join(o["slug"] for o in organizations) or "не найдены")

        for org in organizations:
            for template in SOURCECRAFT_ORG_REPOS_TEMPLATES:
                items = await _paged(client, template.strip().format(slug=org["slug"]),
                                     headers, attempts)
                if not items:
                    continue
                for raw in items:
                    repo = normalize_repo(raw, org_slug=org["slug"])
                    if repo:
                        repo["source"] = "organization"
                        repo["organization_name"] = org["display_name"]
                        repo["role"] = "личная организация" if org["slug"] == username else "участник"
                        collected.setdefault(repo["full_path"], repo)
                log.info("Организация %s: %s репозиториев", org["slug"], len(items))
                break

        # Дополнительный источник: платформа может вернуть здесь то, чего нет в организациях
        for path in SOURCECRAFT_REPOS_PATHS:
            for raw in await _paged(client, path.strip(), headers, attempts):
                repo = normalize_repo(raw)
                if repo:
                    repo.setdefault("source", "organization")
                    repo.setdefault("role", "участник")
                    collected.setdefault(repo["full_path"], repo)

    if not collected:
        raise SourceCraftError(
            "Платформа не вернула ни одного репозитория.", attempts)

    repos = list(collected.values())
    # Личные проекты первыми, дальше по алфавиту
    repos.sort(key=lambda r: (r["owner"] != username, r["full_path"]))
    log.info("Итого репозиториев пользователя: %s", len(repos))
    return repos
