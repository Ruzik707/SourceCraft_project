#!/usr/bin/env python3
"""
Подбор рабочей ручки SourceCraft для списка репозиториев пользователя.

Зачем: сервису нужно знать, по какому адресу и с каким заголовком авторизации
платформа отдаёт репозитории, доступные пользователю. Скрипт перебирает
разумные варианты и печатает, что ответила платформа.

Запуск (нужен личный токен доступа из профиля SourceCraft):

    export SOURCECRAFT_TOKEN=pv1_...
    uv run python tools/probe_sourcecraft.py

Токен в вывод не попадает — можно отправлять результат как есть.
"""
from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.getenv("SOURCECRAFT_API", "https://api.sourcecraft.tech")
TOKEN = os.getenv("SOURCECRAFT_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else "")

# Схемы авторизации: точный вид заголовка платформа нигде явно не описывает
AUTH_VARIANTS = [
    ("Authorization", "Bearer {t}"),
    ("Authorization", "OAuth {t}"),
    ("Authorization", "Token {t}"),
    ("Authorization", "{t}"),
    ("X-Api-Key", "{t}"),
    ("Private-Token", "{t}"),
]

# Пути: соглашения GitHub/GitLab плюс то, что видно в логах сборщика
PATHS = [
    "/me", "/user", "/users/me", "/profile",
    "/repos", "/repositories", "/me/repos", "/user/repos", "/users/me/repos",
    "/v1/repos", "/api/v1/repos", "/projects", "/me/projects",
    "/search/repositories?query=test",
]

# Заведомо существующий адрес из логов сборщика — проверяем, что токен вообще принят
KNOWN = "/repos/userver/userver"


def probe(client: httpx.Client, path: str, header: str, template: str) -> tuple[int, str]:
    try:
        response = client.get(path, headers={header: template.format(t=TOKEN),
                                             "Accept": "application/json"})
    except httpx.HTTPError as exc:
        return 0, f"{type(exc).__name__}: {exc}"
    body = response.text[:200].replace("\n", " ")
    return response.status_code, body


def main() -> int:
    if not TOKEN:
        print("Не задан SOURCECRAFT_TOKEN (переменная окружения или первый аргумент)")
        return 1

    print(f"База: {BASE}\n")
    with httpx.Client(base_url=BASE, timeout=20, follow_redirects=True) as client:
        print("1. Какая схема авторизации принимается")
        print(f"   Проверяем на известном адресе {KNOWN}\n")
        working = []
        for header, template in AUTH_VARIANTS:
            code, body = probe(client, KNOWN, header, template)
            mark = "OK " if code == 200 else "   "
            print(f"   {mark}{code}  {header}: {template.replace('{t}', '<токен>')}")
            if code == 200:
                working.append((header, template))
                print(f"        ответ: {body[:160]}")

        if not working:
            print("\n   Ни одна схема не подошла. Пришлите, пожалуйста, ответ целиком —")
            print("   возможно, у API другой базовый адрес или нужен другой заголовок.")
            working = [AUTH_VARIANTS[0]]

        header, template = working[0]
        print(f"\n2. Ищем список репозиториев пользователя (заголовок {header})\n")
        found = []
        for path in PATHS:
            code, body = probe(client, path, header, template)
            mark = "OK " if code == 200 else "   "
            print(f"   {mark}{code}  {path}")
            if code == 200:
                found.append(path)
                print(f"        ответ: {body[:200]}")

        print("\n3. Итог")
        if found:
            print(f"   Рабочие адреса: {', '.join(found)}")
            print(f"   Заголовок: {header}: {template.replace('{t}', '<токен>')}")
            print("\n   В .env сервиса:")
            print(f"   SOURCECRAFT_REPOS_PATHS={','.join(p for p in found if 'repo' in p or 'project' in p) or found[0]}")
            print(f"   SOURCECRAFT_AUTH_HEADER={header}")
            print(f"   SOURCECRAFT_AUTH_TEMPLATE={template}")
        else:
            print("   Ни один адрес не ответил. Пришлите вывод целиком — подберу дальше.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
