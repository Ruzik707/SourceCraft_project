#!/usr/bin/env python3
"""
Показывает, что платформа отдаёт по разным адресам: профиль, организации,
репозитории. Нужен, чтобы понять, какой список действительно «мои репозитории»,
а какой — недавние или доступные.

    export SOURCECRAFT_TOKEN=pv1_...
    uv run python tools/dump_my_repos.py

Токен в вывод не попадает.
"""
from __future__ import annotations

import json
import os
import sys

import httpx


def _token_from_env_file() -> str:
    """Берёт токен из .env, если переменная окружения не задана."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_path):
        return ""
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            key, _, value = line.strip().partition("=")
            if key.strip() == "SOURCECRAFT_TOKEN":
                return value.strip().strip('"').strip("'")
    return ""


BASE = os.getenv("SOURCECRAFT_API", "https://api.sourcecraft.tech")
TOKEN = os.getenv("SOURCECRAFT_TOKEN") or (
    sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("pv1_") else "")
HEADERS = {"Accept": "application/json"}

# Схемы заголовка: личный токен платформы и токен Я ID принимаются по-разному
AUTH_VARIANTS = [
    ("Authorization", "Bearer {t}"),
    ("Authorization", "OAuth {t}"),
    ("Authorization", "Token {t}"),
    ("Authorization", "{t}"),
    ("X-Api-Key", "{t}"),
    ("Private-Token", "{t}"),
    ("X-Auth-Token", "{t}"),
]

PROFILE_PATHS = ["/me", "/user", "/profile"]
ORG_PATHS = ["/me/organizations", "/me/orgs", "/organizations", "/orgs", "/me/groups"]
REPO_PATHS = ["/me/repos", "/me/repositories", "/me/projects"]


def show(client: httpx.Client, path: str, limit: int = 900) -> object | None:
    try:
        r = client.get(path, headers=HEADERS)
    except httpx.HTTPError as exc:
        print(f"   ✗ {path}: {type(exc).__name__}")
        return None
    if r.status_code != 200:
        print(f"   · {path}: {r.status_code}")
        return None
    try:
        data = r.json()
    except ValueError:
        print(f"   · {path}: 200, но не JSON")
        return None
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(f"   ✓ {path}: 200")
    print("     " + text[:limit].replace("\n", "\n     "))
    if len(text) > limit:
        print(f"     … ещё {len(text) - limit} символов")
    return data


def items_of(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "repositories", "repos", "organizations", "orgs", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def pick_auth(client: httpx.Client) -> tuple[str, str] | None:
    """Ищет схему заголовка, которую платформа принимает для этого токена.

    Проверяем на двух адресах: профиль и заведомо существующий публичный
    репозиторий. Личный токен может не давать доступа к профилю, но работать
    с репозиториями — тогда 401 на /me ещё ничего не значит.
    Медленное первое рукопожатие не должно выглядеть как отказ, поэтому
    неудавшиеся по сети варианты проверяются повторно.
    """
    print("0. Подбираем схему авторизации\n")
    probes = ["/me", "/repos/userver/userver"]
    retry: list[tuple[str, str]] = []

    def attempt(header: str, template: str, quiet: bool = False) -> bool:
        results = []
        for path in probes:
            try:
                r = client.get(path, headers={header: template.format(t=TOKEN),
                                              "Accept": "application/json"})
                results.append((path, r.status_code))
            except httpx.HTTPError as exc:
                results.append((path, type(exc).__name__))
        shown = ", ".join(f"{p} → {code}" for p, code in results)
        ok = any(code == 200 for _, code in results)
        if not quiet:
            print(f"   {'✓' if ok else '·'} {header}: {template.replace('{t}', '<токен>')} — {shown}")
        if not ok and any(isinstance(code, str) for _, code in results):
            retry.append((header, template))
        return ok

    for header, template in AUTH_VARIANTS:
        if attempt(header, template):
            return header, template

    if retry:
        print("\n   Повтор для вариантов, не дошедших до сервера с первого раза:\n")
        for header, template in retry:
            if attempt(header, template):
                return header, template
    return None


def main() -> int:
    global TOKEN, HEADERS
    if not TOKEN:
        TOKEN = _token_from_env_file()
    if not TOKEN:
        print("Не задан SOURCECRAFT_TOKEN")
        return 1

    print(f"Токен: {TOKEN[:8]}…{TOKEN[-4:]} (длина {len(TOKEN)})\n")

    # Первое рукопожатие к платформе бывает долгим: даём запас на соединение
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, connect=25.0),
                      follow_redirects=True) as client:
        auth = pick_auth(client)
        if auth is None:
            print("\n   Ни одна схема не принята. Возможные причины:")
            print("   • токен истёк или отозван — выпустите новый в профиле SourceCraft;")
            print("   • токен скопирован не полностью;")
            print("   • личные токены не дают доступа к этому API, и нужен токен Я ID.")
            return 1
        header, template = auth
        HEADERS = {header: template.format(t=TOKEN), "Accept": "application/json"}
        print(f"\n   Рабочая схема: {header}: {template.replace('{t}', '<токен>')}")
        print(f"   Для .env:  SOURCECRAFT_AUTH_HEADER={header}")
        print(f"              SOURCECRAFT_AUTH_TEMPLATE={template}\n")

        print("1. Кто владелец токена\n")
        profile = None
        for path in PROFILE_PATHS:
            profile = show(client, path, 500) or profile

        print("\n2. Организации\n")
        orgs = []
        for path in ORG_PATHS:
            data = show(client, path, 700)
            orgs.extend(items_of(data))

        print("\n3. Списки репозиториев\n")
        for path in REPO_PATHS:
            data = show(client, path, 1200)
            found = items_of(data)
            if found:
                print(f"     → записей: {len(found)}")
                print("     → пути:", ", ".join(
                    str(x.get("full_path") or x.get("path")
                        or f"{(x.get('organization') or {}).get('slug', '?')}/{x.get('slug') or x.get('name')}")
                    for x in found[:20] if isinstance(x, dict)))

        print("\n4. Репозитории каждой организации\n")
        slugs = []
        for org in orgs:
            if isinstance(org, dict):
                slug = org.get("slug") or org.get("name") or org.get("login")
                if slug:
                    slugs.append(str(slug))
        if not slugs:
            print("   организации не найдены — впишите свои вручную:")
            print("   uv run python tools/dump_my_repos.py <токен> organization-sofia-malakaeva ...")
            slugs = sys.argv[2:]

        for slug in slugs:
            for template in ("/orgs/{s}/repos", "/organizations/{s}/repos",
                             "/repos/{s}", "/{s}/repos"):
                data = show(client, template.format(s=slug), 700)
                found = items_of(data)
                if found:
                    print(f"     → у «{slug}» записей: {len(found)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
