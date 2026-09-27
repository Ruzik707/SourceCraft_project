"""Сборка ответов API по контракту docs/api-contract.md."""
from __future__ import annotations

import math
from typing import Any

from backend import facts
from scoring.normalizer import BEST_WEIGHTS, FORMULA_VERSION, WEIGHT_KEY_BY_CATEGORY
from scoring.recommender import SourceCraftRecommendationEngine

CATEGORIES = ["security", "code_health", "activity", "documentation", "cicd", "issues"]

WEIGHTS = {category: BEST_WEIGHTS[key] for category, key in WEIGHT_KEY_BY_CATEGORY.items()}

RECOMMENDER_CATEGORY = {
    "Security": "security", "CI/CD": "cicd", "Documentation": "documentation",
    "Issues": "issues", "Activity": "activity", "Code Health": "code_health",
}
RECOMMENDER_PRIORITY = {
    "Критический": "critical", "Высокий": "high", "Средний": "medium", "Низкий": "low",
}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

engine = SourceCraftRecommendationEngine()


def clean_value(value: Any) -> Any:
    """NaN в JSON не сериализуется: превращаем в None.

    Осторожно: NaN в Python истинный, поэтому выражения вида «a or b» его не
    отфильтровывают — значение нужно чистить явно.
    """
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


_clean = clean_value


def _opt_float(value: Any) -> float | None:
    value = _clean(value)
    return None if value is None else round(float(value), 1)


def to_summary(row: dict) -> dict:
    """Строка рейтинга."""
    categories = {c: _opt_float(row.get(f"score_{c}")) for c in CATEGORIES}
    statuses = {c: _display_status(row.get(f"status_{c}"), bool(row.get(f"counted_{c}", True)))
                for c in CATEGORIES}
    rank = _clean(row.get("rank"))
    return {
        "id": _clean(row.get("id")) or row["full_path"],
        "full_path": row["full_path"],
        "owner": _clean(row.get("owner")),
        "name": _clean(row.get("name")),
        "url": _clean(row.get("url")),
        "description": _clean(row.get("description")),
        "primary_language": _clean(row.get("primary_language")),
        # Округление до целого — правка соседа. clean_value обязателен:
        # NaN в Python истинный, а int(nan) падает с ValueError.
        "likes": int(float(clean_value(row.get("likes")) or 0)),
        "last_activity_at": _clean(row.get("last_activity_at")),
        "analyzed_at": _clean(row.get("analyzed_at")),
        "total_score": _opt_float(row.get("total_score")),
        "grade": row.get("grade") or "—",
        "coverage": round(float(_clean(row.get("coverage")) or 0), 4),
        "categories": categories,
        "no_data_categories": [c for c, s in statuses.items() if s == "no_data"],
        "not_applicable_categories": [c for c, s in statuses.items() if s == "not_applicable"],
        "has_ci": bool(row.get("has_ci")),
        "security_status": statuses["security"],
        "rank": int(rank) if rank is not None else None,
    }


def _display_status(fact_status: str | None, counted: bool) -> str:
    """Статус категории на экране.

    Если методика категорию учла, оценка есть — даже когда часть сигналов собрать не
    удалось: тогда это «собрано частично». Если методика категорию исключила, оценки
    нет вовсе — «нет данных» или «не применимо».
    """
    fact_status = fact_status or "ok"
    if counted:
        return "ok" if fact_status == "ok" else "partial"
    return fact_status if fact_status in ("no_data", "not_applicable") else "no_data"


def _short_title(action: str) -> str:
    """Короткий заголовок из формулировки действия: обрезаем по границе фразы,
    но не внутри скобок — иначе получается «(например» в конце заголовка."""
    text = action.strip().rstrip(".")
    if len(text) > 60:
        for sep in (": ", " — ", ", "):
            head = text.split(sep)[0]
            if sep in text and head.count("(") == head.count(")"):
                text = head
                break
    return text if len(text) <= 80 else text[:77].rsplit(" ", 1)[0] + "…"


def _recommendations(prepared_row: dict, repo_url: str | None) -> list[dict]:
    items = []
    for i, rec in enumerate(engine.generate_recommendations(prepared_row)):
        category = RECOMMENDER_CATEGORY.get(rec.get("category", ""), "activity")
        priority = RECOMMENDER_PRIORITY.get(rec.get("priority", ""), "medium")
        action = rec.get("action", "")
        items.append({
            "id": f"{category}.{i + 1}",
            "category": category,
            "priority": priority,
            "title": _short_title(action),
            "problem": rec.get("problem", ""),
            "why": rec.get("importance", ""),
            "action": action,
            "evidence": [{"label": "Категория", "value": rec.get("category", ""), "url": repo_url}],
            # Числовой прирост методика пока не отдаёт: показываем её же формулировку эффекта
            "expected_gain": 0.0,
            "impact": rec.get("impact"),
        })
    items.sort(key=lambda r: PRIORITY_ORDER[r["priority"]])
    return items


def _summary_text(total: float | None, grade: str, coverage: float, categories: list[dict],
                  recommendations: list[dict]) -> str:
    scored = [c for c in categories if c["score"] is not None]
    parts = []
    if total is not None:
        parts.append(
            f"Repo Health Score {total:.0f} из 100 (оценка {grade}), посчитан по {len(scored)} "
            f"из {len(categories)} категорий ({coverage * 100:.0f}% веса методики)."
        )
    else:
        parts.append("Оценка не рассчитана: ни по одной категории не удалось собрать данные.")
    if scored:
        best = max(scored, key=lambda c: c["score"])
        worst = min(scored, key=lambda c: c["score"])
        parts.append(f"Сильнее всего категория «{best['title']}» — {best['score']:.0f}/100.")
        if worst is not best:
            parts.append(f"Слабее всего «{worst['title']}» — {worst['score']:.0f}/100.")
    missing = [c["title"] for c in categories if c["status"] == "no_data"]
    if missing:
        parts.append("Нет данных: " + ", ".join(missing)
                     + " — категории исключены из расчёта и не ухудшают Score.")
    not_applicable = [c["title"] for c in categories if c["status"] == "not_applicable"]
    if not_applicable:
        parts.append("Не применимо: " + ", ".join(not_applicable) + ".")
    first = next((r for r in recommendations if r["priority"] in ("critical", "high")), None)
    if first:
        parts.append(f"Первоочередное действие: {first['title']}.")
    return " ".join(parts)


def _category_summary(score: float | None, fact: dict, reason: str | None = None) -> str:
    """Одна фраза под названием категории: почему такая оценка."""
    if score is None:
        return reason or fact["no_data_reason"] or "Нет данных."
    if fact["status"] in ("no_data", "not_applicable"):
        return reason or "Данные собрать не удалось."
    if fact["weaknesses"]:
        return fact["weaknesses"][0]
    if fact["strengths"]:
        return fact["strengths"][0]
    return "Данные собраны, замечаний нет."


def to_report(row: dict, raw_row: dict, prepared_row: dict) -> dict:
    """Полный отчёт для страницы анализа."""
    summary = to_summary(row)
    category_facts = facts.category_facts(raw_row)

    categories = []
    for key in CATEGORIES:
        fact = category_facts[key]
        counted = bool(row.get(f"counted_{key}", True))
        status = _display_status(row.get(f"status_{key}") or fact["status"], counted)
        score = _opt_float(row.get(f"score_{key}"))
        weight = round(float(_clean(row.get(f"weight_{key}")) or 0), 4)
        reason = fact["no_data_reason"]
        if counted and fact["status"] in ("no_data", "not_applicable"):
            # Методика такие категории не исключает: считает по нейтральным значениям.
            # Пишем это прямо, чтобы оценка не выглядела взятой из воздуха.
            reason = ((reason or "Часть данных собрать не удалось.")
                      + " Методика учитывает категорию по нейтральным значениям.")
        elif not counted:
            reason = reason or "Категория исключена методикой из расчёта."
        categories.append({
            "key": key,
            "title": facts.CATEGORY_TITLES[key],
            "score": score,
            "status": status,
            "weight": WEIGHTS[key],
            "effective_weight": weight,
            "signal_coverage": fact["signal_coverage"],
            "summary": _category_summary(score, fact, reason),
            "strengths": fact["strengths"],
            "weaknesses": fact["weaknesses"],
            "no_data_reason": reason,
            "metrics": fact["metrics"],
        })

    recommendations = _recommendations(prepared_row, summary["url"])

    strengths, risks = [], []
    for category in categories:
        for text in category["strengths"][:2]:
            strengths.append({"category": category["key"], "text": text})
        for text in category["weaknesses"][:2]:
            risks.append({"category": category["key"], "text": text})

    return {
        **summary,
        "visibility": facts.text(raw_row, "repo.visibility") or "public",
        "default_branch": facts.text(raw_row, "repo.default_branch"),
        "likes_percentile": facts.num(raw_row, "activity.likes.percentile"),
        "score": {
            "total": summary["total_score"],
            "grade": summary["grade"],
            "coverage": summary["coverage"],
            "formula_version": FORMULA_VERSION,
            "weights": WEIGHTS,
        },
        "categories": categories,
        "recommendations": recommendations,
        "strengths": strengths,
        "risks": risks,
        "summary": _summary_text(summary["total_score"], summary["grade"],
                                 summary["coverage"], categories, recommendations),
        "collection": facts.collection_info(raw_row),
        "history": [{"analyzed_at": summary["analyzed_at"], "total": summary["total_score"]}],
    }
