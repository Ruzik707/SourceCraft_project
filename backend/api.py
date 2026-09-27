"""REST-эндпоинты сервиса. Контракт: docs/api-contract.md."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse

from backend import analyses, auth, presenter
from backend.config import (ALLOW_DEMO_AUTH, API_PREFIX, FRONTEND_URL, SCHEDULE_CRON,
                            SOURCECRAFT_FALLBACK_TOKEN)
from backend.db import history_for, session_scope, UserSession
from backend.scheduler import next_run_at
from backend.sourcecraft import SourceCraftError, list_user_repos
from backend.store import showcase

log = logging.getLogger(__name__)
router = APIRouter(prefix=API_PREFIX)


# ══════════════════════════════ публичная часть ══════════════════════════════
@router.get("/repos")
def list_repos(
    query: str | None = None,
    language: str | None = None,
    sort: str = Query("score", pattern="^(score|likes|activity|name)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    has_ci: bool | None = None,
    security_status: str | None = Query(None, pattern="^(ok|partial|no_data|not_applicable)$"),
    min_coverage: float | None = Query(None, ge=0, le=1),
):
    rows, total = showcase.query(
        query=query, language=language, sort=sort, order=order, page=page,
        page_size=page_size, has_ci=has_ci, security_status=security_status,
        min_coverage=min_coverage,
    )
    return {
        "items": [presenter.to_summary(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/repos/{owner}/{name}")
def get_repo(owner: str, name: str, current=Depends(auth.optional_user)):
    full_path = f"{owner}/{name}"
    row = showcase.summary_row(full_path)
    raw_row = showcase.raw_row(full_path)
    if row is None or raw_row is None:
        raise HTTPException(404, {
            "code": "repo_not_found",
            "message": f"Репозиторий {full_path} ещё не анализировался сервисом.",
        })

    # Закрытый репозиторий отдаём только его владельцу: постороннему он выглядит
    # как несуществующий, чтобы сам факт наличия не раскрывался.
    if str(row.get("visibility")) == "private":
        user = current[0] if current else None
        if user is None or user.login != owner:
            raise HTTPException(404, {
                "code": "repo_not_found",
                "message": f"Репозиторий {full_path} ещё не анализировался сервисом.",
            })
    report = presenter.to_report(row, raw_row, showcase.prepared_row(full_path))
    stored = history_for(full_path)
    if stored:
        report["history"] = stored
    return report


@router.get("/languages")
def list_languages():
    return showcase.languages()


@router.get("/stats")
def get_stats():
    stats = showcase.stats()
    scheduled = next_run_at()
    if scheduled:
        stats["next_run_at"] = scheduled
    else:
        last = stats.get("last_run_at")
        base = datetime.fromisoformat(last) if last else datetime.now(timezone.utc)
        stats["next_run_at"] = (base + timedelta(days=1)).replace(
            hour=3, minute=0, second=0, microsecond=0).isoformat()
    stats["schedule"] = SCHEDULE_CRON
    return stats


@router.post("/admin/rebuild")
def rebuild():
    """Пересборка витрины из выгрузки — вручную; по расписанию делает планировщик."""
    showcase.build()
    return {"status": "ok", **showcase.stats()}


# ══════════════════════════════ авторизация ══════════════════════════════════
@router.get("/auth/yandex/login")
def yandex_login(redirect_uri: str | None = None, next: str = "/dashboard",
                 demo: bool = False):
    """Начало входа. Уводит на страницу согласия Яндекс ID.

    Есть секрет приложения — идём надёжным code-потоком через ручку сервиса.
    Секрета нет — implicit: Яндекс вернёт токен прямо на фронт, сервис проверит
    его при первом же запросе. Нет и client_id — выдаём демо-сессию для стенда.
    """
    target = redirect_uri or f"{FRONTEND_URL}/auth/callback"

    # ?demo=1 — вход без Яндекса для стенда и автотестов. Работает только пока
    # разрешён ALLOW_DEMO_AUTH; на публичном стенде его выключают.
    if demo and ALLOW_DEMO_AUTH:
        _, token = auth.demo_login()
        return RedirectResponse(_with_token(target, token, next), status_code=302)

    if auth.code_flow_available():
        return RedirectResponse(auth.authorize_url(target, next), status_code=302)

    if auth.yandex_configured():
        # redirect_uri должен совпадать с зарегистрированным — без параметров запроса
        callback = target.split("?")[0]
        next_path = next if next.startswith("/") else "/dashboard"
        return RedirectResponse(auth.implicit_url(callback, next_path), status_code=302)

    _, token = auth.demo_login()
    return RedirectResponse(_with_token(target, token, next), status_code=302)


@router.get("/auth/yandex/callback")
async def yandex_callback(code: str | None = None, state: str | None = None,
                          error: str | None = None, error_description: str | None = None):
    """Возврат от Яндекса: меняем код на токен и заводим сессию."""
    front = f"{FRONTEND_URL}/auth/callback"
    if error:
        return RedirectResponse(f"{front}?error={error}&error_description={error_description or ''}",
                                status_code=302)
    if not code or not state:
        raise HTTPException(400, {"code": "bad_request", "message": "Яндекс ID не передал код."})

    data = auth.read_state(state)
    redirect_uri = data["redirect_uri"]
    tokens = await auth.exchange_code(code, auth.callback_uri())
    profile = await auth.fetch_profile(tokens["access_token"])
    user = auth.upsert_user(profile)
    session_token = auth.create_session(user, yandex_token=tokens.get("access_token"))
    return RedirectResponse(
        _with_token(redirect_uri, session_token, data.get("next", "/dashboard")),
        status_code=302,
    )


@router.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(default=None)):
    auth.logout(auth.bearer_token(authorization))


@router.get("/me")
def me(current=Depends(auth.require_user)):
    user, _session = current
    return user.to_dict()


@router.post("/me/sourcecraft-token", status_code=204)
def set_sourcecraft_token(token: str = Body(embed=True), current=Depends(auth.require_user)):
    """Личный токен доступа SourceCraft: с ним сервис видит закрытые репозитории.

    Нужен, пока токен Я ID не даёт доступа к API платформы. Хранится в сессии и
    удаляется вместе с ней.
    """
    _user, session_row = current
    with session_scope() as session:
        row = session.get(UserSession, session_row.token)
        if row is not None:
            row.sourcecraft_token = token.strip() or None


@router.get("/me/repos")
async def my_repos(current=Depends(auth.require_user)):
    user, session_row = current

    # Платформа принимает разные ключи: личный токен доступа и токен Я ID.
    # Пробуем оба — какой сработает, тем и пользуемся.
    candidates = [
        ("личный токен SourceCraft", session_row.sourcecraft_token),
        ("токен Я ID", session_row.yandex_token),
    ]
    if ALLOW_DEMO_AUTH and SOURCECRAFT_FALLBACK_TOKEN:
        # Стендовый запасной ключ: в проде так нельзя — каждый вошедший увидит
        # репозитории его владельца, поэтому только вместе с ALLOW_DEMO_AUTH.
        candidates.append(("запасной токен из настроек", SOURCECRAFT_FALLBACK_TOKEN))

    repos: list[dict] = []
    demo = False
    failures: list[str] = []
    for label, token in candidates:
        if not token:
            continue
        try:
            repos = await list_user_repos(token, login=user.login)
            log.info("Репозитории получены: %s", label)
            break
        except SourceCraftError as exc:
            log.warning("%s не подошёл: %s | %s", label, exc, exc.attempts)
            failures.append(f"{label}: {exc}")

    if not repos and failures and not ALLOW_DEMO_AUTH:
        raise HTTPException(502, {
            "code": "sourcecraft_unavailable",
            "message": "Платформа не вернула список репозиториев. "
                       "Добавьте действующий личный токен доступа SourceCraft.",
        })

    if not repos:
        repos = _demo_repos(user.login)
        demo = True

    return [_own_repo(repo, demo) for repo in repos]


@router.get("/me/analyses")
def my_analyses(current=Depends(auth.require_user)):
    user, _ = current
    return analyses.recent_for_user(user.id)


# ══════════════════════════════ анализ по запросу ════════════════════════════
@router.post("/analyses", status_code=202)
def create_analysis(repo_full_path: str = Body(embed=True), current=Depends(auth.require_user)):
    user, _ = current
    if "/" not in repo_full_path:
        raise HTTPException(400, {"code": "bad_request",
                                  "message": "Ожидается путь вида owner/name."})
    return analyses.start(repo_full_path.strip(), user.id)


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, current=Depends(auth.require_user)):
    user, _ = current
    run = analyses.get(analysis_id, user.id)
    if run is None:
        raise HTTPException(404, {"code": "not_found", "message": "Запуск анализа не найден."})
    return run


# ══════════════════════════════ вспомогательное ══════════════════════════════
def _with_token(redirect_uri: str, token: str, next_path: str = "/dashboard") -> str:
    from urllib.parse import urlencode
    separator = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{separator}{urlencode({'token': token, 'next': next_path})}"


def _demo_repos(login: str) -> list[dict]:
    """Подборка для стенда, пока платформа не отдаёт список: свои репозитории
    пользователя, если они есть в выгрузке, иначе несколько показательных."""
    showcase.ensure_ready()
    table = showcase.table
    own = table[table["owner"].fillna("") == login]
    if len(own):
        rows = own.head(12).to_dict("records")
    else:
        # Показательная подборка: сильный, средний, слабый и один без данных —
        # чтобы на стенде было видно, как интерфейс ведёт себя в разных случаях
        scored = table[table["total_score"].notna()]
        picks = [scored.iloc[0], scored.iloc[len(scored) // 4], scored.iloc[len(scored) // 2],
                 scored.iloc[-1]]
        empty = table[table["total_score"].isna()]
        if len(empty):
            picks.append(empty.iloc[0])
        rows, seen = [], set()
        for pick in picks:
            row = pick.to_dict()
            if row["full_path"] not in seen:
                seen.add(row["full_path"])
                rows.append(row)
    return [{"full_path": r["full_path"], "owner": r.get("owner"), "name": r.get("name"),
             "id": r.get("id"), "url": r.get("url"), "description": r.get("description"),
             "primary_language": r.get("primary_language"), "visibility": "public",
             "role": "maintainer"} for r in rows]


def _own_repo(repo: dict, demo: bool) -> dict:
    """Репозиторий пользователя + его оценка из витрины, если он уже анализировался."""
    row = showcase.summary_row(repo["full_path"])
    if row is not None:
        summary = presenter.to_summary(row)
    else:
        summary = {
            "id": repo.get("id") or repo["full_path"],
            "full_path": repo["full_path"], "owner": repo.get("owner"), "name": repo.get("name"),
            "url": repo.get("url"), "description": repo.get("description"),
            "primary_language": repo.get("primary_language"), "likes": 0,
            "last_activity_at": None, "analyzed_at": None, "total_score": None,
            "grade": "—", "coverage": 0.0, "categories": {}, "no_data_categories": [],
            "not_applicable_categories": [], "has_ci": False, "security_status": "no_data",
            "rank": None,
        }
    return {
        **summary,
        "role": repo.get("role", "member"),
        "visibility": repo.get("visibility", "public"),
        "last_analysis_at": summary.get("analyzed_at"),
        "demo": demo,
        # organization — репозиторий пользователя, accessible — просто доступный ему
        "source": repo.get("source", "organization"),
    }
