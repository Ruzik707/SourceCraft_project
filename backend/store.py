"""
Витрина Repo Health: загружает выгрузку сборщика, прогоняет её через scoring
и держит результат в памяти для выдачи по API.

Нормализация метрик в scoring считается по min/max всей выборки, поэтому расчёт
выполняется разом по всему датасету, а не по одному репозиторию.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

import pandas as pd

from backend.config import CSV_PATH
from scoring.data_loader import preprocess_frame
from scoring.normalizer import BEST_WEIGHTS, WEIGHT_KEY_BY_CATEGORY, compute_scores_frame

log = logging.getLogger(__name__)

CATEGORIES = ["security", "code_health", "activity", "documentation", "cicd", "issues"]

# Колонки, которые нужны рейтингу: остальное подтягивается только на странице анализа
IDENTITY_COLUMNS = [
    "repo.platform_id", "repo.full_path", "repo.owner", "repo.name", "repo.url",
    "repo.description", "repo.primary_language", "repo.visibility", "repo.default_branch",
    "activity.likes.value", "activity.likes.percentile", "activity.last_commit_at",
    "collection.collected_at", "collection.collector_version",
]


def _as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"])


def _status_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Статус каждой категории. Правила совпадают с backend/facts.py — это
    единственное место, где решается, участвует ли категория в расчёте."""
    def col(name, default=""):
        return raw[name] if name in raw.columns else pd.Series(default, index=raw.index)

    def num(name):
        return pd.to_numeric(col(name, None), errors="coerce")

    st = pd.DataFrame(index=raw.index)

    st["security"] = pd.Series("ok", index=raw.index).where(
        _as_bool(col("security.appsec_available", "False")), "no_data")

    cicd_unavailable = col("collection.category_status.cicd").fillna("") == "unavailable"
    has_history = _as_bool(col("cicd.pipeline_history_available", "False"))
    st["cicd"] = pd.Series("partial", index=raw.index).where(~has_history, "ok")
    st.loc[cicd_unavailable, "cicd"] = "no_data"

    for category, column in (("documentation", "collection.category_status.documentation"),
                             ("activity", "collection.category_status.activity")):
        st[category] = pd.Series("ok", index=raw.index)
        st.loc[col(column).fillna("") == "unavailable", category] = "no_data"

    open_count, opened, closed = num("issues.open_count"), num("issues.opened_90d"), num("issues.closed_90d")
    first_response = num("issues.avg_time_to_first_response_hours")
    st["issues"] = pd.Series("ok", index=raw.index)
    st.loc[first_response.isna(), "issues"] = "partial"
    empty_tracker = (open_count.fillna(0) == 0) & (opened.fillna(0) == 0) & (closed.fillna(0) == 0)
    st.loc[empty_tracker, "issues"] = "not_applicable"
    st.loc[col("collection.category_status.issues").fillna("") == "unavailable", "issues"] = "no_data"

    loc_estimate = num("code_health.lines_of_code_estimate")
    st["code_health"] = pd.Series("ok", index=raw.index)
    st.loc[loc_estimate.fillna(0) < 200, "code_health"] = "not_applicable"
    st.loc[col("collection.category_status.code_health").fillna("") == "unavailable", "code_health"] = "no_data"

    return st


def _grade(total: float | None) -> str:
    if total is None or pd.isna(total):
        return "—"
    if total >= 85:
        return "A"
    if total >= 70:
        return "B"
    if total >= 55:
        return "C"
    if total >= 40:
        return "D"
    return "E"


class Showcase:
    """Загруженная и посчитанная витрина. Пересобирается по требованию."""

    def __init__(self) -> None:
        self.raw: pd.DataFrame | None = None
        self.table: pd.DataFrame | None = None
        self.statuses: pd.DataFrame | None = None
        self.built_at: datetime | None = None
        self.duration_seconds: float | None = None
        self._lock = threading.Lock()

    # ─────────────────────────────── сборка ──────────────────────────────────
    def build(self) -> None:
        started = datetime.now(timezone.utc)
        log.info("Загружаем выгрузку сборщика: %s", CSV_PATH)
        raw = pd.read_csv(CSV_PATH, encoding="utf-8-sig", low_memory=False)
        raw = raw[raw["repo.full_path"].notna()].reset_index(drop=True)
        log.info("Строк: %s, колонок: %s", len(raw), len(raw.columns))

        statuses = _status_frame(raw)

        prepared = preprocess_frame(raw)
        # Маску активных категорий задаёт сама методика — бэкенд её не подменяет
        scores = compute_scores_frame(prepared)

        table = pd.DataFrame(index=raw.index)
        table["id"] = raw.get("repo.platform_id")
        table["full_path"] = raw["repo.full_path"]
        table["owner"] = raw.get("repo.owner")
        table["name"] = raw.get("repo.name")
        table["url"] = raw.get("repo.url")
        table["description"] = raw.get("repo.description")
        table["primary_language"] = raw.get("repo.primary_language")
        table["likes"] = pd.to_numeric(raw.get("activity.likes.value"), errors="coerce").fillna(0.0)
        table["last_activity_at"] = raw.get("activity.last_commit_at")
        table["analyzed_at"] = raw.get("collection.collected_at")
        table["has_ci"] = _as_bool(raw.get("cicd.has_ci_config", pd.Series(False, index=raw.index)))
        # Пустое значение трактуем как public: сборщик ходил по открытому каталогу,
        # а пропуск означает недобранные метаданные, а не закрытый репозиторий.
        table["visibility"] = raw.get("repo.visibility", pd.Series("public", index=raw.index)) \
            .fillna("public").astype(str)
        table["total_score"] = scores["total_health_score"]
        table["coverage"] = scores["coverage"]
        table["grade"] = table["total_score"].map(_grade)

        for category in CATEGORIES:
            column = {"security": "score_security", "code_health": "score_health",
                      "issues": "score_issues", "activity": "score_activity",
                      "documentation": "score_docs", "cicd": "score_cicd"}[category]
            counted = scores[f"active_{category}"] == 1
            # Балл показываем там, где его учла методика; иначе категория исключена
            table[f"score_{category}"] = scores[column].where(counted)
            table[f"weight_{category}"] = scores[f"weight_{category}"]
            table[f"counted_{category}"] = counted
            table[f"status_{category}"] = statuses[category]

        table = table.sort_values(["total_score", "likes"], ascending=[False, False],
                                  na_position="last").reset_index(drop=True)
        table["rank"] = [i + 1 if pd.notna(v) else None
                         for i, v in enumerate(table["total_score"])]

        with self._lock:
            self.raw = raw.set_index("repo.full_path", drop=False)
            self.table = table
            self.statuses = statuses
            self.built_at = datetime.now(timezone.utc)
            self.duration_seconds = (self.built_at - started).total_seconds()

        log.info("Витрина готова за %.1f с, оценено %s репозиториев",
                 self.duration_seconds, int(table["total_score"].notna().sum()))

    def ensure_ready(self) -> None:
        if self.table is None:
            self.build()

    # ─────────────────────────────── выборки ─────────────────────────────────
    def query(self, *, query: str | None = None, language: str | None = None,
              sort: str = "score", order: str = "desc", page: int = 1, page_size: int = 25,
              has_ci: bool | None = None, security_status: str | None = None,
              min_coverage: float | None = None,
              include_private: bool = False) -> tuple[list[dict], int]:
        self.ensure_ready()
        df = self.table
        if not include_private:
            # Публичный рейтинг — только открытые репозитории
            df = df[df["visibility"] != "private"]

        if query:
            needle = query.strip().lower()
            haystack = (df["full_path"].fillna("") + " " + df["description"].fillna("")).str.lower()
            df = df[haystack.str.contains(needle, regex=False)]
        if language:
            df = df[df["primary_language"].fillna("—") == language]
        if has_ci is not None:
            df = df[df["has_ci"] == has_ci]
        if security_status:
            df = df[df["status_security"] == security_status]
        if min_coverage:
            df = df[df["coverage"].fillna(0) >= min_coverage]

        ascending = order == "asc"
        if sort == "likes":
            df = df.sort_values("likes", ascending=ascending, na_position="last")
        elif sort == "activity":
            df = df.sort_values("last_activity_at", ascending=ascending, na_position="last")
        elif sort == "name":
            df = df.sort_values("full_path", ascending=ascending)
        else:
            df = df.sort_values("total_score", ascending=ascending, na_position="last")

        total = len(df)
        start = max(0, (page - 1) * page_size)
        return df.iloc[start:start + page_size].to_dict("records"), total

    def summary_row(self, full_path: str) -> dict | None:
        self.ensure_ready()
        rows = self.table[self.table["full_path"] == full_path]
        return None if rows.empty else rows.iloc[0].to_dict()

    def raw_row(self, full_path: str) -> dict | None:
        self.ensure_ready()
        if full_path not in self.raw.index:
            return None
        row = self.raw.loc[full_path]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return row.to_dict()

    def prepared_row(self, full_path: str) -> dict:
        """Строка, подготовленная так же, как для расчёта — нужна рекомендателю."""
        raw_row = self.raw_row(full_path)
        if raw_row is None:
            return {}
        return preprocess_frame(pd.DataFrame([raw_row])).iloc[0].to_dict()

    def languages(self) -> list[dict]:
        self.ensure_ready()
        public = self.table[self.table["visibility"] != "private"]
        counts = public["primary_language"].fillna("—").value_counts()
        return [{"language": str(lang), "count": int(n)} for lang, n in counts.items()]

    def stats(self) -> dict:
        self.ensure_ready()
        df = self.table[self.table["visibility"] != "private"]
        scored = df["total_score"].dropna()
        return {
            "repos_total": int(len(df)),
            "repos_scored": int(len(scored)),
            "median_score": round(float(scored.median()), 1) if len(scored) else None,
            "no_data_security": int((df["status_security"] == "no_data").sum()),
            "with_ci": int(df["has_ci"].sum()),
            "last_run_at": self.built_at.isoformat() if self.built_at else None,
            "next_run_at": None,
            "schedule": None,
            "weights": {cat: BEST_WEIGHTS[key] for cat, key in WEIGHT_KEY_BY_CATEGORY.items()},
            "build_duration_seconds": round(self.duration_seconds or 0, 1),
        }


showcase = Showcase()
