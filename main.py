"""
SourceCraft Repo Health — HTTP API.

Эндпоинты чтения витрины (/repos, /languages, /stats) собраны в backend/api.py:
они отдают данные по контракту docs/api-contract.md, который уже реализует фронтенд.
Расчёт оценок выполняет пакет scoring/.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict

from backend import scheduler
from backend.api import router
from backend.db import init_db
from backend.store import showcase
from scoring.data_loader import preprocess_data
from scoring.normalizer import calculate_health_score
from scoring.recommender import SourceCraftRecommendationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("repo-health")

app = FastAPI(title="SourceCraft Repo Health API", version="1.0.0")
engine = SourceCraftRecommendationEngine()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def warm_up() -> None:
    """Витрина строится при старте, дальше пересчитывается по расписанию."""
    init_db()
    try:
        showcase.build()
    except Exception:  # noqa: BLE001 — сервис должен подняться даже без выгрузки
        log.exception("Не удалось построить витрину при старте")
    scheduler.start()


@app.on_event("shutdown")
def stop_scheduler() -> None:
    scheduler.shutdown()


@app.get("/health")
def health() -> dict:
    from backend.auth import yandex_configured
    ready = showcase.table is not None
    return {
        "status": "ok" if ready else "loading",
        "repos": int(len(showcase.table)) if ready else 0,
        "built_at": showcase.built_at.isoformat() if showcase.built_at else None,
        "next_run_at": scheduler.next_run_at(),
        "auth": "yandex_id" if yandex_configured() else "demo",
    }


class RepoPayload(BaseModel):
    repository_id: str
    metrics: Dict[str, Any]


@app.post("/api/v1/score")
def generate_score(payload: RepoPayload) -> dict:
    """Расчёт по произвольному набору метрик — используется для отладки методики.

    Внимание: нормализация в методике считается по выборке, поэтому оценка одной
    записи отличается от оценки того же репозитория в общей витрине.
    """
    df_clean = preprocess_data(payload.metrics)
    health_scores = calculate_health_score(df_clean)
    recommendations = engine.generate_recommendations(df_clean.iloc[0].to_dict())
    return {
        "repository_id": payload.repository_id,
        "scores": health_scores,
        "recommendations": recommendations,
    }
