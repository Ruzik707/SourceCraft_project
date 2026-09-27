"""
Анализ репозитория по запросу из личного кабинета.

Задача ставится в очередь и выполняется в фоне: интерфейс опрашивает статус и
показывает стадии сбора. Сбор данных выполняет сборщик — команда задаётся
переменной COLLECTOR_COMMAND. Пока она не задана, стадии сбора помечаются
пропущенными, а оценка пересчитывается по последнему снимку: интерфейс пишет
об этом прямо, чтобы результат нельзя было принять за свежий сбор.
"""
from __future__ import annotations

import logging
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

from sqlalchemy import select

from backend import presenter
from backend.config import COLLECTOR_COMMAND, COLLECTOR_TIMEOUT, ANALYSIS_WORKERS
from backend.db import AnalysisRun, ScoreHistory, session_scope, utcnow
from backend.store import showcase

log = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=ANALYSIS_WORKERS, thread_name_prefix="analysis")

STAGES = [
    ("queue", "Постановка в очередь"),
    ("clone", "Получение рабочей копии и Git-истории"),
    ("platform", "Метаданные платформы: issues, MR, релизы, лайки"),
    ("appsec", "Результаты AppSec SourceCraft"),
    ("score", "Расчёт Repo Health Score"),
    ("recommendations", "Формирование рекомендаций"),
]


def _initial_stages() -> list[dict]:
    return [{"key": key, "title": title, "status": "pending", "detail": None}
            for key, title in STAGES]


def _update(analysis_id: str, **fields) -> None:
    with session_scope() as session:
        run = session.get(AnalysisRun, analysis_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)


def _set_stage(stages: list[dict], key: str, status: str, detail: str | None = None) -> list[dict]:
    for stage in stages:
        if stage["key"] == key:
            stage["status"] = status
            if detail is not None:
                stage["detail"] = detail
    return stages


def start(full_path: str, user_id: str | None) -> dict:
    analysis_id = f"an_{uuid.uuid4().hex[:16]}"
    stages = _set_stage(_initial_stages(), "queue", "running")
    with session_scope() as session:
        session.add(AnalysisRun(id=analysis_id, user_id=user_id, repo_full_path=full_path,
                                status="queued", progress=0, stages=stages))
    executor.submit(_run, analysis_id, full_path)
    return get(analysis_id, user_id)


def get(analysis_id: str, user_id: str | None) -> dict | None:
    with session_scope() as session:
        run = session.get(AnalysisRun, analysis_id)
        if run is None:
            return None
        # Чужой запуск не отдаём: в нём могут быть данные закрытого репозитория
        if run.user_id and user_id and run.user_id != user_id:
            return None
        return run.to_dict()


def recent_for_user(user_id: str, limit: int = 20) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(
            select(AnalysisRun).where(AnalysisRun.user_id == user_id)
            .order_by(AnalysisRun.started_at.desc()).limit(limit)
        ).all()
    return [{**r.to_dict(), "report": None} for r in rows]


# ─────────────────────────────── выполнение ──────────────────────────────────
def _run(analysis_id: str, full_path: str) -> None:
    stages = _initial_stages()
    try:
        stages = _set_stage(stages, "queue", "done")
        _update(analysis_id, status="running", progress=10, stages=stages)

        collected = _collect(analysis_id, full_path, stages)
        if collected:
            showcase.build()

        stages = _set_stage(stages, "score", "running")
        _update(analysis_id, progress=70, stages=stages)

        row = showcase.summary_row(full_path)
        raw_row = showcase.raw_row(full_path)
        if row is None or raw_row is None:
            raise LookupError(
                f"Репозитория {full_path} нет в выгрузке сборщика. "
                "Запустите сбор данных или проверьте название."
            )

        stages = _set_stage(stages, "score", "done")
        stages = _set_stage(stages, "recommendations", "running")
        _update(analysis_id, progress=85, stages=stages)

        report = presenter.to_report(row, raw_row, showcase.prepared_row(full_path))
        report["history"] = _history_with_current(full_path, report)

        stages = _set_stage(stages, "recommendations", "done")
        finished = utcnow()
        _update(analysis_id, status="succeeded", progress=100, stages=stages,
                finished_at=finished, report=report)
        _save_history_point(full_path, report)
        log.info("Анализ %s завершён: %s", analysis_id, full_path)

    except Exception as exc:  # noqa: BLE001 — любая ошибка должна дойти до интерфейса
        log.exception("Анализ %s упал", analysis_id)
        for stage in stages:
            if stage["status"] == "running":
                stage["status"] = "failed"
        _update(analysis_id, status="failed", stages=stages, finished_at=utcnow(),
                error=str(exc))


def _collect(analysis_id: str, full_path: str, stages: list[dict]) -> bool:
    """Сбор свежих данных. Возвращает True, если выгрузка обновилась."""
    if not COLLECTOR_COMMAND:
        note = "Сборщик не подключён: оценка пересчитана по последнему снимку данных."
        for key in ("clone", "platform", "appsec"):
            _set_stage(stages, key, "skipped", note)
        _update(analysis_id, progress=55, stages=stages)
        return False

    _set_stage(stages, "clone", "running")
    _update(analysis_id, progress=25, stages=stages)
    command = COLLECTOR_COMMAND.format(full_path=full_path)
    started = time.monotonic()
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True,
                                timeout=COLLECTOR_TIMEOUT)
    except subprocess.TimeoutExpired:
        _set_stage(stages, "clone", "failed", f"Сборщик не уложился в {COLLECTOR_TIMEOUT} с")
        _update(analysis_id, stages=stages)
        raise

    duration = time.monotonic() - started
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "")[-300:]
        _set_stage(stages, "clone", "failed", detail)
        _update(analysis_id, stages=stages)
        raise RuntimeError(f"Сборщик завершился с кодом {result.returncode}: {detail}")

    for key in ("clone", "platform"):
        _set_stage(stages, key, "done", f"Сбор занял {duration:.0f} с")
    _set_stage(stages, "appsec", "skipped",
               "AppSec отвечает только при наличии прав на репозиторий")
    _update(analysis_id, progress=60, stages=stages)
    return True


def _history_with_current(full_path: str, report: dict) -> list[dict]:
    from backend.db import history_for
    points = history_for(full_path)
    current = {"analyzed_at": report.get("analyzed_at"), "total": report["score"]["total"]}
    if not points or points[-1]["total"] != current["total"]:
        points.append(current)
    return points


def _save_history_point(full_path: str, report: dict) -> None:
    with session_scope() as session:
        session.add(ScoreHistory(
            full_path=full_path,
            analyzed_at=utcnow().astimezone(timezone.utc),
            total=report["score"]["total"],
            categories={c["key"]: c["score"] for c in report["categories"]},
            formula_version=report["score"]["formula_version"],
        ))
