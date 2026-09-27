"""
Периодический пересчёт: по расписанию заново собирает витрину и пишет точки
истории Repo Health Score, из которых интерфейс рисует динамику.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import HISTORY_ON_REBUILD, SCHEDULE_CRON, SCHEDULER_ENABLED
from backend.db import save_history
from backend.store import CATEGORIES, showcase

log = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None


def write_history() -> int:
    """Снимок текущих оценок в историю."""
    if not HISTORY_ON_REBUILD or showcase.table is None:
        return 0
    analyzed_at = showcase.built_at
    points = []
    for row in showcase.table.to_dict("records"):
        total = row.get("total_score")
        if total is None or total != total:  # NaN
            continue
        points.append({
            "full_path": row["full_path"],
            "analyzed_at": analyzed_at,
            "total": round(float(total), 1),
            "categories": {c: (None if row.get(f"score_{c}") != row.get(f"score_{c}")
                               else row.get(f"score_{c}")) for c in CATEGORIES},
            "formula_version": None,
        })
    saved = save_history(points)
    log.info("История: записано %s точек", saved)
    return saved


def recalculate() -> None:
    """Задача расписания: пересобрать витрину и зафиксировать оценки."""
    log.info("Плановый пересчёт Repo Health Score")
    showcase.build()
    write_history()


def start() -> None:
    global scheduler
    if not SCHEDULER_ENABLED:
        log.info("Планировщик выключен (SCHEDULER_ENABLED=false)")
        return
    if scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(recalculate, CronTrigger.from_crontab(SCHEDULE_CRON),
                      id="recalculate", replace_existing=True, max_instances=1)
    scheduler.start()
    log.info("Планировщик запущен, расписание: %s", SCHEDULE_CRON)


def shutdown() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None


def next_run_at() -> str | None:
    if scheduler is None:
        return None
    job = scheduler.get_job("recalculate")
    return job.next_run_time.isoformat() if job and job.next_run_time else None
