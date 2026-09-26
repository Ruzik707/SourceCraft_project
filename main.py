import os
import httpx
import uuid
import pandas as pd
import urllib.parse
from typing import Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from scoring.normalizer import calculate_health_score
from scoring.data_loader import preprocess_data
from scoring.recommender import SourceCraftRecommendationEngine

app = FastAPI(title="SourceCraft Backend API")
engine = SourceCraftRecommendationEngine()

YANDEX_CLIENT_ID = "0e306eb0e70e42fca074ede029dc9e1f"
REDIRECT_URI = "http://localhost:5173/auth/callback"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "repo_health_report.csv")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def safe_str(val, default=""):
    if pd.isna(val): return default
    return str(val)

def safe_float(val, default=0.0):
    if pd.isna(val): return default
    try: return float(val)
    except: return default

def safe_int(val, default=0):
    if pd.isna(val): return default
    try: return int(float(val))
    except: return default

def get_grade(score: float) -> str:
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "E"


# ==========================================
# 1. АВТОРИЗАЦИЯ ЧЕРЕЗ ЯНДЕКС ID
# ==========================================

@app.get("/api/v1/auth/yandex/login")
def yandex_login(redirect_uri: str = "http://localhost:5173/auth/callback"):
    encoded_uri = urllib.parse.quote(redirect_uri)
    url = f"https://oauth.yandex.ru/authorize?response_type=token&client_id={YANDEX_CLIENT_ID}&redirect_uri={encoded_uri}"
    return RedirectResponse(url)

@app.get("/api/v1/me")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Отсутствует токен авторизации")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://login.yandex.ru/info?format=json",
            headers={"Authorization": f"OAuth {token}"}
        )

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Токен недействителен или истек")

    user_data = response.json()
    return {
        "id": str(user_data.get("id")),
        "login": user_data.get("login"),
        "display_name": user_data.get("real_name", user_data.get("login")),
        "avatar_url": None,
        "provider": "yandex_id"
    }

@app.get("/api/v1/me/repos")
def get_my_repos(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Отсутствует токен авторизации")

    mock_repo = get_repos()["items"][0]
    mock_repo["role"] = "maintainer"
    mock_repo["visibility"] = "public"
    return [mock_repo]


# ==========================================
# 2. ФОНОВЫЕ ЗАДАЧИ ДЛЯ АНАЛИЗА
# ==========================================

analysis_queue = {}

class AnalysisRequest(BaseModel):
    repo_full_path: str

def run_analysis_task(task_id: str, repo_full_path: str):
    analysis_queue[task_id]["status"] = "running"
    analysis_queue[task_id]["progress"] = 50

    try:
        analysis_queue[task_id]["progress"] = 100
        analysis_queue[task_id]["status"] = "succeeded"
        analysis_queue[task_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

        owner, name = repo_full_path.split("/")
        report_data = get_repo_details(owner, name)
        analysis_queue[task_id]["report"] = report_data
    except Exception as e:
        analysis_queue[task_id]["status"] = "failed"
        analysis_queue[task_id]["error"] = str(e)

@app.post("/api/v1/analyses")
def start_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    task_id = f"an_{uuid.uuid4().hex[:8]}"
    analysis_queue[task_id] = {
        "id": task_id,
        "repo_full_path": req.repo_full_path,
        "status": "queued",
        "progress": 0,
        "stages": [
            {"key": "clone", "title": "Сбор метрик из SourceCraft", "status": "pending"}
        ],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
        "report": None
    }
    background_tasks.add_task(run_analysis_task, task_id, req.repo_full_path)
    return analysis_queue[task_id]

@app.get("/api/v1/analyses/{task_id}")
def get_analysis_status(task_id: str):
    if task_id not in analysis_queue:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    return analysis_queue[task_id]


# ==========================================
# 3. КЭШ ДАННЫХ И ДИНАМИЧЕСКИЙ СКОРИНГ
# ==========================================

CACHED_DF = None

def get_or_load_dataset() -> pd.DataFrame:
    global CACHED_DF
    if CACHED_DF is not None:
        return CACHED_DF

    if not os.path.exists(DATA_FILE):
        return pd.DataFrame()

    try:
        df = pd.read_csv(DATA_FILE, low_memory=False)

        # 1. Безопасная очистка строковых колонок (никаких нулей вместо строк!)
        string_cols = ['repo.full_path', 'repo.name', 'repo.owner', 'repo.primary_language',
                       'repo.description', 'repo.url', 'activity.last_commit_at']
        for col in string_cols:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str)

        # 2. Числовые колонки заполняем нулями
        numeric_cols = [
            'activity.likes.value', 'cicd.has_ci_config', 'cicd.success_rate_30d',
            'documentation.has_readme', 'documentation.has_license', 'documentation.readme_length_chars',
            'documentation.readme_has_sections', 'documentation.has_contributing', 'documentation.has_docs_dir',
            'activity.commits_30d', 'activity.commits_90d', 'activity.contributors_365d',
            'code_health.lines_of_code_estimate', 'code_health.todo_density_per_kloc',
            'issues.stale_open_count', 'issues.unanswered_open_count',
            'security.appsec_available', 'security.open_defect_groups_total', 'security.has_security_policy'
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # 3. Векторный расчет категорий
        ci_has_cfg = df['cicd.has_ci_config'].astype(bool).astype(int) * 50
        ci_success = (df['cicd.success_rate_30d'] * 50).clip(0, 50)
        ci_score = (ci_has_cfg + ci_success).clip(0, 100)

        readme_len = (df['documentation.readme_length_chars'] / 1000.0).clip(0, 1) * 30
        readme_sections = df['documentation.readme_has_sections'].astype(bool).astype(int) * 20
        has_license = df['documentation.has_license'].astype(bool).astype(int) * 25
        has_contrib = df['documentation.has_contributing'].astype(bool).astype(int) * 15
        has_docs = df['documentation.has_docs_dir'].astype(bool).astype(int) * 10
        doc_score = (readme_len + readme_sections + has_license + has_contrib + has_docs).clip(0, 100)

        c_30 = (df['activity.commits_30d'] / 20.0).clip(0, 1) * 40
        c_90 = (df['activity.commits_90d'] / 60.0).clip(0, 1) * 30
        contribs = (df['activity.contributors_365d'] / 5.0).clip(0, 1) * 30
        activity_score = (c_30 + c_90 + contribs).clip(0, 100)

        has_code = (df['code_health.lines_of_code_estimate'] > 50).astype(int)
        todo_density = df['code_health.todo_density_per_kloc'].clip(0, 50)
        code_health_score = ((100 - todo_density * 2) * has_code).clip(0, 100)

        stale_penalty = (df['issues.stale_open_count'] * 15).clip(0, 60)
        unanswered_penalty = (df['issues.unanswered_open_count'] * 10).clip(0, 40)
        issues_score = (100 - stale_penalty - unanswered_penalty).clip(0, 100)

        appsec_on = df['security.appsec_available'].astype(bool).astype(int) * 40
        open_defects = (df['security.open_defect_groups_total'] * 20).clip(0, 60)
        has_policy = df['security.has_security_policy'].astype(bool).astype(int) * 20
        security_score = (appsec_on + 40 - open_defects + has_policy).clip(0, 100)

        # 4. Итоговый Score
        total_score = (
            security_score * 0.198 +
            code_health_score * 0.298 +
            activity_score * 0.108 +
            doc_score * 0.100 +
            ci_score * 0.102 +
            issues_score * 0.191
        ).round(1)

        df['computed_total_score'] = total_score
        df['score_security'] = security_score.round(1)
        df['score_code_health'] = code_health_score.round(1)
        df['score_activity'] = activity_score.round(1)
        df['score_documentation'] = doc_score.round(1)
        df['score_cicd'] = ci_score.round(1)
        df['score_issues'] = issues_score.round(1)

        CACHED_DF = df
        return CACHED_DF
    except Exception as e:
        print(f"Ошибка загрузки датасета: {e}")
        return pd.DataFrame()


def get_metrics_for_repo(owner: str, repo_name: str) -> pd.DataFrame:
    df_full = get_or_load_dataset()
    if df_full.empty:
        return pd.DataFrame()

    full_path = f"{owner}/{repo_name}"
    repo_df = df_full[df_full['repo.full_path'] == full_path]

    if repo_df.empty:
        # Поиск только по имени репозитория
        repo_df = df_full[df_full['repo.name'] == repo_name]

    if repo_df.empty:
        return pd.DataFrame()

    return repo_df.copy()


@app.get("/api/v1/stats")
def get_stats():
    df_full = get_or_load_dataset()
    total_repos = len(df_full)
    median_val = float(df_full['computed_total_score'].median()) if not df_full.empty else 0.0

    try:
        mtime = os.path.getmtime(DATA_FILE)
        last_run = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except Exception:
        last_run = datetime.now(timezone.utc).isoformat()

    return {
        "repos_total": total_repos,
        "repos_scored": total_repos,
        "median_score": round(median_val, 1),
        "no_data_security": int((df_full['security.appsec_available'] == 0).sum()) if not df_full.empty else 0,
        "with_ci": int((df_full['cicd.has_ci_config'] == 1).sum()) if not df_full.empty else 0,
        "last_run_at": last_run
    }


@app.get("/api/v1/languages")
def get_languages():
    df_full = get_or_load_dataset()
    if df_full.empty:
        return []

    lang_counts = df_full['repo.primary_language'].value_counts().reset_index()
    lang_counts.columns = ['language', 'count']

    result = []
    for _, row in lang_counts.dropna().iterrows():
        lang = str(row['language']).strip()
        if lang and lang.lower() not in ["nan", "unknown", "0", "0.0"]:
            result.append({"language": lang, "count": int(row['count'])})

    return sorted(result, key=lambda x: x["count"], reverse=True)


@app.get("/api/v1/repos")
def get_repos(
        page: int = 1,
        page_size: int = 25,
        sort: str = "score",
        order: str = "desc",
        language: str = None,
        min_coverage: float = 0.0
):
    df_full = get_or_load_dataset().copy()
    if df_full.empty:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    if language and language not in ["Все языки", "null", "undefined"]:
        df_full = df_full[df_full['repo.primary_language'] == language]

    total_records = len(df_full)
    ascending = (order == "asc")

    # Безопасная сортировка без конфликта типов str и int
    if sort == "score":
        df_full = df_full.sort_values(by="computed_total_score", ascending=ascending)
    elif sort == "likes":
        df_full = df_full.sort_values(by="activity.likes.value", ascending=ascending)
    elif sort == "activity":
        # Приводим к строкам для надежной сортировки дат ISO
        df_full['sort_date'] = df_full['activity.last_commit_at'].astype(str)
        df_full = df_full.sort_values(by="sort_date", ascending=ascending)
    elif sort == "name":
        df_full['sort_name'] = df_full['repo.name'].astype(str).str.lower()
        df_full = df_full.sort_values(by="sort_name", ascending=ascending)

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    df_page = df_full.iloc[start_idx:end_idx]

    items = []
    current_rank = start_idx + 1

    for _, row in df_page.iterrows():
        full_path = safe_str(row.get("repo.full_path"), f"unknown/repo-{current_rank}")
        parts = full_path.split("/")
        owner = parts[0] if len(parts) > 0 else "unknown"
        name = parts[1] if len(parts) > 1 else f"repo-{current_rank}"

        score_val = safe_float(row.get("computed_total_score"), 0.0)

        categories_dict = {
            "security": safe_float(row.get("score_security"), 0.0),
            "code_health": safe_float(row.get("score_code_health"), 0.0),
            "activity": safe_float(row.get("score_activity"), 0.0),
            "documentation": safe_float(row.get("score_documentation"), 0.0),
            "cicd": safe_float(row.get("score_cicd"), 0.0),
            "issues": safe_float(row.get("score_issues"), 0.0)
        }

        items.append({
            "id": full_path,
            "full_path": full_path,
            "owner": owner,
            "name": name,
            "url": safe_str(row.get("repo.url"), f"https://sourcecraft.dev/{full_path}"),
            "description": safe_str(row.get("repo.description"), "Описание отсутствует"),
            "primary_language": safe_str(row.get("repo.primary_language"), "Unknown"),
            "likes": safe_int(row.get("activity.likes.value"), 0),
            "last_activity_at": safe_str(row.get("activity.last_commit_at"), "2026-09-20T12:00:00Z"),
            "analyzed_at": safe_str(row.get("collection.collected_at"), datetime.now(timezone.utc).isoformat()),
            "total_score": score_val,
            "grade": get_grade(score_val),
            "coverage": 1.0,
            "categories": categories_dict,
            "no_data_categories": [],
            "not_applicable_categories": [],
            "has_ci": bool(row.get("cicd.has_ci_config", False)),
            "security_status": "ok" if row.get("security.appsec_available") else "no_data",
            "rank": current_rank
        })
        current_rank += 1

    return {
        "items": items,
        "total": total_records,
        "page": page,
        "page_size": page_size,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def get_metrics_for_repo(owner: str, repo_name: str) -> pd.DataFrame:
    """Ищет репозиторий без учета регистра и по разным вариациям путей."""
    df_full = get_or_load_dataset()
    if df_full.empty:
        return pd.DataFrame()

    full_path = f"{owner}/{repo_name}".lower()
    paths = df_full['repo.full_path'].astype(str).str.lower()

    # Поиск по точному совпадению full_path
    match = df_full[paths == full_path]

    # Если не найдено, ищем по repo.name
    if match.empty:
        names = df_full['repo.name'].astype(str).str.lower()
        match = df_full[names == repo_name.lower()]

    return match.copy()


@app.get("/api/v1/repos/{owner}/{repo_name}")
def get_repo_details(owner: str, repo_name: str):
    df_clean = get_metrics_for_repo(owner, repo_name)
    if df_clean.empty:
        raise HTTPException(status_code=404, detail="Репозиторий не найден в базе данных")

    row_data = df_clean.iloc[0]

    # Безопасный расчет рекомендаций
    try:
        row_dict = row_data.to_dict()
        raw_recommendations = engine.generate_recommendations(row_dict)
    except Exception:
        raw_recommendations = []

    safe_recommendations = []
    for i, rec in enumerate(raw_recommendations):
        safe_recommendations.append({
            "id": f"rec-{i}",
            "category": rec.get("category", "activity").lower(),
            "priority": "high",
            "title": rec.get("action", "Рекомендация"),
            "problem": rec.get("problem", "Обнаружена проблема"),
            "why": rec.get("importance", "Влияет на Health Score"),
            "action": rec.get("action", "Исправьте проблему"),
            "evidence": [{"label": "Деталь", "value": "Требует внимания", "url": None}],
            "expected_gain": 5.0
        })

    def make_safe_category(key, title, score_val):
        val = safe_float(score_val, 0.0)
        return {
            "key": key,
            "title": title,
            "weight": 0.16,
            "effective_weight": 0.16,
            "score": val,
            "status": "ok",
            "no_data_reason": None,
            "signal_coverage": 1.0,
            "metrics": [{
                "key": f"{key}_metric",
                "label": "Текущая оценка",
                "value": val,
                "display": f"{round(val, 1)}/100",
                "status": "ok",
                "hint": None,
                "source": "pandas_engine"
            }],
            "strengths": [],
            "weaknesses": [],
            "summary": f"{round(val, 1)}/100: метрика рассчитана"
        }

    total_score = safe_float(row_data.get('computed_total_score'), 0.0)

    full_path_val = safe_str(row_data.get("repo.full_path"), f"{owner}/{repo_name}")
    desc_val = safe_str(row_data.get("repo.description"), "Описание отсутствует")
    lang_val = safe_str(row_data.get("repo.primary_language"), "Unknown")
    url_val = safe_str(row_data.get("repo.url"), f"https://sourcecraft.dev/{owner}/{repo_name}")

    return {
        "id": full_path_val,
        "full_path": full_path_val,
        "owner": owner,
        "name": repo_name,
        "url": url_val,
        "description": desc_val,
        "visibility": "public",
        "default_branch": safe_str(row_data.get("repo.default_branch"), "main"),
        "primary_language": lang_val,
        "likes": safe_int(row_data.get("activity.likes.value"), 0),
        "likes_percentile": safe_float(row_data.get("activity.likes.percentile"), 0.0),
        "last_activity_at": safe_str(row_data.get("activity.last_commit_at"), "2026-09-20T12:00:00Z"),
        "analyzed_at": safe_str(row_data.get("collection.collected_at"), datetime.now(timezone.utc).isoformat()),
        "score": {
            "total": total_score,
            "grade": get_grade(total_score),
            "coverage": 1.0,
            "formula_version": "pandas-1.0",
            "weights": {
                "security": 0.198, "code_health": 0.298, "activity": 0.108,
                "documentation": 0.100, "cicd": 0.102, "issues": 0.191
            }
        },
        "categories": [
            make_safe_category("security", "Security", row_data.get("score_security", 0)),
            make_safe_category("code_health", "Состояние кода", row_data.get("score_code_health", 0)),
            make_safe_category("activity", "Активность", row_data.get("score_activity", 0)),
            make_safe_category("documentation", "Документация", row_data.get("score_documentation", 0)),
            make_safe_category("cicd", "CI/CD", row_data.get("score_cicd", 0)),
            make_safe_category("issues", "Issues", row_data.get("score_issues", 0))
        ],
        "recommendations": safe_recommendations,
        "strengths": [{"category": "general", "text": "Метрики успешно выгружены из SourceCraft"}],
        "risks": [],
        "no_data_categories": [],
        "not_applicable_categories": [],
        "summary": f"Health Score проекта составляет {total_score} из 100 на основе комплексного анализа репозитория.",
        "collection": {
            "collected_at": safe_str(row_data.get("collection.collected_at"), datetime.now(timezone.utc).isoformat()),
            "duration_ms": safe_float(row_data.get("collection.duration_ms"), 150.0),
            "collector_version": safe_str(row_data.get("collection.collector_version"), "1.0"),
            "sources_used": {
                "git_clone": bool(row_data.get("collection.sources_used.git_clone", True)),
                "platform_api": bool(row_data.get("collection.sources_used.platform_api", True)),
                "platform_cli": bool(row_data.get("collection.sources_used.platform_cli", False)),
                "appsec_api": bool(row_data.get("collection.sources_used.appsec_api", True))
            },
            "errors": []
        },
        "history": [
            {"analyzed_at": safe_str(row_data.get("collection.collected_at"), datetime.now(timezone.utc).isoformat()),
             "total": total_score}
        ]
    }