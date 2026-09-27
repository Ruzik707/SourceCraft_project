"""
Факты для страницы анализа: метрики, статусы категорий, сильные и слабые стороны.

Баллы сюда не попадают — их считает scoring/normalizer.py. Здесь только то, на чём
оценка основана: значения из выгрузки сборщика, приведённые к виду, который ждёт
веб-интерфейс (docs/api-contract.md, раздел CategoryScore).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

CATEGORY_TITLES = {
    "security": "Security",
    "code_health": "Состояние кода",
    "activity": "Активность",
    "documentation": "Документация",
    "cicd": "CI/CD",
    "issues": "Issues",
}


# ─────────────────────────────── доступ к значениям ──────────────────────────
def _isna(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip() == ""


def num(row: dict, key: str) -> float | None:
    v = row.get(key)
    if _isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def flag(row: dict, key: str) -> bool | None:
    v = row.get(key)
    if _isna(v):
        return None
    if isinstance(v, bool):
        return v
    text = str(v).strip().lower()
    if text in ("true", "1", "1.0"):
        return True
    if text in ("false", "0", "0.0"):
        return False
    return None


def text(row: dict, key: str) -> str | None:
    v = row.get(key)
    return None if _isna(v) else str(v).strip()


def jlist(row: dict, key: str) -> list:
    raw = text(row, key)
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except json.JSONDecodeError:
        return []


def days_since(iso: str | None, now: datetime | None = None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - dt).total_seconds() / 86400


def human_days(d: float | None) -> str:
    if d is None:
        return "—"
    d = int(round(d))
    if d <= 0:
        return "сегодня"
    if d == 1:
        return "1 день назад"
    if d < 5:
        return f"{d} дня назад"
    if d < 31:
        return f"{d} дней назад"
    months = d // 30
    if months < 12:
        return f"{months} мес. назад"
    return f"{months // 12} г. назад"


def metric(key: str, label: str, value: Any, display: str, status: str = "ok",
           hint: str | None = None, source: str | None = None) -> dict:
    return {"key": key, "label": label, "value": value, "display": display,
            "status": status, "hint": hint, "source": source}


def yesno(v: bool | None) -> str:
    return "есть" if v else "нет"


# ─────────────────────────────── категории ───────────────────────────────────
def _documentation(row: dict) -> dict:
    if text(row, "collection.category_status.documentation") == "unavailable":
        return _no_data("Репозиторий не удалось склонировать, файлы документации не проверены.")

    has_readme = flag(row, "documentation.has_readme")
    length = num(row, "documentation.readme_length_chars") or 0
    sections = jlist(row, "documentation.readme_has_sections")
    license_type = text(row, "documentation.license_type")
    has_license = flag(row, "documentation.has_license")
    contributing = flag(row, "documentation.has_contributing")
    coc = flag(row, "documentation.has_code_of_conduct")
    changelog = flag(row, "documentation.has_changelog")
    docs_files = num(row, "documentation.docs_file_count") or 0
    issue_tpl = flag(row, "documentation.has_issue_templates")
    pr_tpl = flag(row, "documentation.has_pr_template")

    metrics = [
        metric("readme", "README", has_readme,
               f"есть, {int(length)} символов" if has_readme else "отсутствует",
               hint="Первое, что видит новый разработчик.", source="git_clone"),
        metric("readme_sections", "Разделы README", sections,
               ", ".join(sections) if sections else "разделы не распознаны",
               hint="Инструкция локального запуска, сборка, тесты.", source="git_clone"),
        metric("license", "Лицензия", has_license, license_type or yesno(has_license),
               hint="Без лицензии проект нельзя легально использовать.", source="git_clone"),
        metric("contributing", "CONTRIBUTING", contributing, yesno(contributing), source="git_clone"),
        metric("code_of_conduct", "CODE_OF_CONDUCT", coc, yesno(coc), source="git_clone"),
        metric("changelog", "CHANGELOG", changelog, yesno(changelog), source="git_clone"),
        metric("docs_dir", "Каталог docs/", docs_files,
               f"{int(docs_files)} файлов" if docs_files else "нет", source="git_clone"),
        metric("templates", "Шаблоны issue/PR", bool(issue_tpl or pr_tpl),
               ", ".join(x for x in ("issue" if issue_tpl else "", "PR" if pr_tpl else "") if x) or "нет",
               source="git_clone"),
    ]
    strengths, weaknesses = [], []
    if has_readme and length >= 2000:
        strengths.append(f"Подробный README ({int(length)} символов)")
    if has_license:
        strengths.append(f"Лицензия {license_type or 'указана'}")
    if contributing:
        strengths.append("Есть инструкция для контрибьюторов")
    if not has_readme:
        weaknesses.append("README отсутствует")
    elif length < 500:
        weaknesses.append("README короче 500 символов")
    if not has_license:
        weaknesses.append("Нет файла лицензии")
    if not sections:
        weaknesses.append("В README не найдено инструкции локального запуска")

    return _facts("ok", metrics, strengths, weaknesses)


def _cicd(row: dict) -> dict:
    status_raw = text(row, "collection.category_status.cicd")
    if status_raw == "unavailable":
        return _no_data("Конфигурация и история пайплайнов недоступны.")

    has_ci = flag(row, "cicd.has_ci_config")
    path = text(row, "cicd.ci_config_path")
    test_stage = flag(row, "cicd.has_test_stage")
    lint_stage = flag(row, "cicd.has_lint_or_security_stage")
    deploy_stage = flag(row, "cicd.has_deploy_stage")
    stages = num(row, "cicd.declared_stage_count")
    history = flag(row, "cicd.pipeline_history_available")
    runs = num(row, "cicd.runs_30d")
    success = num(row, "cicd.success_rate_30d")
    duration = num(row, "cicd.median_duration_seconds")
    last_status = text(row, "cicd.last_run_status")

    metrics = [
        metric("ci_config", "Конфигурация CI", has_ci, path or ("есть" if has_ci else "не найдена"),
               hint="Без CI изменения не проверяются автоматически.", source="git_clone"),
        metric("test_stage", "Стадия тестов", test_stage, yesno(test_stage), source="git_clone"),
        metric("lint_stage", "Линт/секьюрити-стадия", lint_stage, yesno(lint_stage), source="git_clone"),
        metric("deploy_stage", "Стадия деплоя", deploy_stage, yesno(deploy_stage), source="git_clone"),
        metric("stages", "Объявлено стадий", stages,
               f"{int(stages)}" if stages is not None else "—", source="git_clone"),
    ]
    if history:
        metrics += [
            metric("runs_30d", "Прогонов за 30 дней", runs, f"{int(runs or 0)}", source="platform_api"),
            metric("success_rate", "Доля успешных прогонов", success, f"{(success or 0) * 100:.0f}%",
                   hint="Нестабильный CI блокирует поставку.", source="platform_api"),
            metric("median_duration", "Медианная длительность", duration,
                   f"{int(duration or 0)} с" if duration else "—", source="platform_api"),
            metric("last_run", "Последний прогон", last_status, last_status or "—", source="platform_api"),
        ]
        status, reason, coverage = "ok", None, 1.0
    else:
        metrics += [
            metric("runs_30d", "Прогонов за 30 дней", None, "нет данных", "no_data",
                   "Платформа вернула 403 на историю пайплайнов.", "platform_api"),
            metric("success_rate", "Доля успешных прогонов", None, "нет данных", "no_data",
                   source="platform_api"),
        ]
        status, coverage = "partial", 0.5
        reason = "История прогонов пайплайнов недоступна через API платформы."

    strengths, weaknesses = [], []
    if has_ci:
        strengths.append(f"CI настроен ({path or 'конфигурация найдена'})")
    else:
        weaknesses.append("Конфигурация CI не найдена")
    if test_stage:
        strengths.append("В пайплайне есть стадия тестов")
    else:
        weaknesses.append("В пайплайне нет стадии тестов")
    if not lint_stage:
        weaknesses.append("Нет стадии линта или проверки безопасности")

    return _facts(status, metrics, strengths, weaknesses, reason, coverage)


def _security(row: dict) -> dict:
    available = flag(row, "security.appsec_available")
    policy = flag(row, "security.has_security_policy")
    policy_metric = metric(
        "security_policy", "SECURITY-политика", policy, yesno(policy),
        hint="Справочный признак: категория считается по данным AppSec.", source="git_clone")

    if not available:
        return _no_data(
            "AppSec SourceCraft вернул 403: результаты SAST/SCA/secret scanning не выдаются "
            "без прав на репозиторий.",
            metrics=[
                metric("appsec", "Данные AppSec", False, "недоступны", "no_data",
                       "Security считается только по фактическим результатам AppSec.", "appsec_api"),
                policy_metric,
            ])

    severity = text(row, "security.defect_groups_by_severity") or "—"
    open_total = num(row, "security.open_defect_groups_total")
    oldest = num(row, "security.oldest_open_defect_group_age_days")
    scan_type = text(row, "security.latest_scan.scan_type")
    scan_status = text(row, "security.latest_scan.status")
    scan_at = text(row, "security.latest_scan.finished_at")

    metrics = [
        metric("scan", "Последнее сканирование", scan_at,
               f"{scan_type or 'scan'}, {scan_status or 'ok'}, {human_days(days_since(scan_at))}",
               source="appsec_api"),
        metric("severity", "Группы дефектов по критичности", severity, severity, source="appsec_api"),
        metric("open_total", "Открытых групп дефектов", open_total,
               f"{int(open_total or 0)}", source="appsec_api"),
        metric("oldest_open", "Возраст старейшей проблемы", oldest, human_days(oldest), source="appsec_api"),
        policy_metric,
    ]
    strengths, weaknesses = [], []
    up = severity.upper()
    if "CRITICAL" in up or "HIGH" in up:
        weaknesses.append("Есть дефекты уровня CRITICAL или HIGH")
    elif open_total == 0:
        strengths.append("Открытых групп дефектов нет")
    if oldest and oldest > 90:
        weaknesses.append(f"Старейшая открытая проблема не исправлена {human_days(oldest)}")

    return _facts("ok", metrics, strengths, weaknesses)


def _activity(row: dict) -> dict:
    if text(row, "collection.category_status.activity") == "unavailable":
        return _no_data("Git-история недоступна: рабочая копия не получена.")

    last = text(row, "activity.last_commit_at")
    age = days_since(last)
    c30 = num(row, "activity.commits_30d") or 0
    c90 = num(row, "activity.commits_90d") or 0
    c365 = num(row, "activity.commits_365d") or 0
    contributors = num(row, "activity.contributors_365d") or 0
    bus = num(row, "activity.bus_factor_top1_share_365d")
    tags = num(row, "activity.tag_count") or 0
    releases = num(row, "activity.releases.count") or 0
    prs_open = num(row, "activity.pull_requests.open") or 0
    prs_merged = num(row, "activity.pull_requests.merged_90d") or 0
    prs_stale = num(row, "activity.pull_requests.stale_open_count") or 0

    metrics = [
        metric("last_commit", "Последний коммит", last, human_days(age), source="git_clone"),
        metric("commits_30d", "Коммитов за 30 дней", c30, f"{int(c30)}", source="git_clone"),
        metric("commits_90d", "Коммитов за 90 дней", c90, f"{int(c90)}", source="git_clone"),
        metric("commits_365d", "Коммитов за год", c365, f"{int(c365)}", source="git_clone"),
        metric("contributors", "Контрибьюторов за год", contributors, f"{int(contributors)}", source="git_clone"),
        metric("bus_factor", "Доля топ-1 автора", bus,
               f"{bus * 100:.0f}%" if bus is not None else "нет данных",
               "ok" if bus is not None else "no_data",
               "Чем выше доля одного автора, тем ниже bus factor.", "git_clone"),
        metric("tags", "Тегов", tags, f"{int(tags)}", source="git_clone"),
        metric("releases", "Релизов", releases, f"{int(releases)}", source="platform_api"),
        metric("prs_open", "Открытых merge request", prs_open, f"{int(prs_open)}", source="platform_api"),
        metric("prs_merged_90d", "Влито MR за 90 дней", prs_merged, f"{int(prs_merged)}", source="platform_api"),
        metric("prs_stale", "Зависших MR", prs_stale, f"{int(prs_stale)}", source="platform_api"),
    ]
    strengths, weaknesses = [], []
    if age is not None and age <= 30:
        strengths.append("Проект активно развивается: коммиты за последние 30 дней")
    if contributors >= 10:
        strengths.append(f"{int(contributors)} контрибьюторов за год")
    if bus is not None and bus <= 0.4 and contributors >= 3:
        strengths.append("Работа распределена между несколькими авторами")
    if age is not None and age > 180:
        weaknesses.append(f"Последний коммит {human_days(age)}")
    if contributors <= 1:
        weaknesses.append("Весь код за год написан одним автором (bus factor = 1)")
    elif bus is not None and bus > 0.8:
        weaknesses.append(f"{bus * 100:.0f}% коммитов сделал один автор")
    if prs_stale:
        weaknesses.append(f"{int(prs_stale)} merge request зависли")
    if tags == 0 and releases == 0:
        weaknesses.append("Нет тегов и релизов")

    return _facts("ok", metrics, strengths, weaknesses)


def _issues(row: dict) -> dict:
    if text(row, "collection.category_status.issues") == "unavailable":
        return _no_data("API трекера задач недоступно.")

    open_count = num(row, "issues.open_count") or 0
    opened = num(row, "issues.opened_90d") or 0
    closed = num(row, "issues.closed_90d") or 0
    first_resp = num(row, "issues.avg_time_to_first_response_hours")
    to_close = num(row, "issues.avg_time_to_close_hours")
    stale = num(row, "issues.stale_open_count") or 0
    unanswered = num(row, "issues.unanswered_open_count") or 0
    labels = jlist(row, "issues.labels_in_use")

    if open_count == 0 and opened == 0 and closed == 0:
        return _facts("not_applicable", [metric("open_count", "Открытых задач", 0, "0", source="platform_api")],
                      [], [],
                      "В трекере репозитория нет ни одной задачи — оценивать нечего.", 0.0)

    metrics = [
        metric("open_count", "Открытых задач", open_count, f"{int(open_count)}", source="platform_api"),
        metric("opened_90d", "Заведено за 90 дней", opened, f"{int(opened)}", source="platform_api"),
        metric("closed_90d", "Закрыто за 90 дней", closed, f"{int(closed)}", source="platform_api"),
        metric("first_response", "Среднее время до первого ответа", first_resp,
               f"{first_resp:.1f} ч" if first_resp is not None else "нет данных",
               "ok" if first_resp is not None else "no_data", source="platform_api"),
        metric("time_to_close", "Среднее время до закрытия", to_close,
               f"{to_close / 24:.1f} дн." if to_close else "нет данных",
               "ok" if to_close else "no_data", source="platform_api"),
        metric("stale", "Зависших задач", stale, f"{int(stale)}",
               hint="Открыты и не обновлялись более 30 дней.", source="platform_api"),
        metric("unanswered", "Без ответа", unanswered, f"{int(unanswered)}", source="platform_api"),
        metric("labels", "Используемых меток", len(labels), f"{len(labels)}", source="platform_api"),
    ]
    strengths, weaknesses = [], []
    if opened and closed / opened >= 0.8:
        strengths.append("Задачи закрываются быстрее, чем заводятся")
    if open_count and not stale:
        strengths.append("Зависших задач нет")
    if stale:
        weaknesses.append(f"{int(stale)} задач не обновлялись более 30 дней")
    if unanswered:
        weaknesses.append(f"{int(unanswered)} открытых задач без ответа")
    if first_resp is not None and first_resp > 72:
        weaknesses.append(f"Первый ответ в среднем через {first_resp:.0f} ч")

    status = "ok" if first_resp is not None else "partial"
    reason = None if first_resp is not None else "Время первого ответа платформа не отдаёт."
    return _facts(status, metrics, strengths, weaknesses, reason, 1.0 if first_resp is not None else 0.8)


def _code_health(row: dict) -> dict:
    if text(row, "collection.category_status.code_health") == "unavailable":
        return _no_data("Рабочая копия недоступна, код не проанализирован.")

    files = num(row, "code_health.file_count") or 0
    loc = num(row, "code_health.lines_of_code_estimate") or 0
    todo = num(row, "code_health.todo_count") or 0
    fixme = num(row, "code_health.fixme_count") or 0
    hack = num(row, "code_health.hack_count") or 0
    density = num(row, "code_health.todo_density_per_kloc")
    oldest = num(row, "code_health.oldest_todo_age_days")
    largest = num(row, "code_health.largest_file_lines") or 0

    if loc < 200:
        return _facts("not_applicable",
                      [metric("loc", "Строк кода", loc, f"{int(loc)}", source="git_clone")], [], [],
                      f"В репозитории {int(loc)} строк кода — выборка слишком мала для оценки "
                      "технического долга.", 0.0)

    avg = loc / files if files else 0
    metrics = [
        metric("files", "Файлов под контролем версий", files, f"{int(files)}", source="git_clone"),
        metric("loc", "Строк кода (оценка)", loc, f"{int(loc):,}".replace(",", " "), source="git_clone"),
        metric("todo", "TODO", todo, f"{int(todo)}", source="git_clone"),
        metric("fixme", "FIXME", fixme, f"{int(fixme)}", source="git_clone"),
        metric("hack", "HACK", hack, f"{int(hack)}", source="git_clone"),
        metric("todo_density", "Плотность TODO на 1000 строк", density,
               f"{density:.2f}" if density is not None else "—",
               hint="Сопоставимо между проектами разного размера.", source="git_clone"),
        metric("oldest_todo", "Возраст старейшего TODO", oldest, human_days(oldest),
               hint="Считается по дате строки в Git-истории.", source="git_clone"),
        metric("largest_file", "Самый большой файл", largest, f"{int(largest)} строк", source="git_clone"),
        metric("avg_file", "Средний размер файла", avg, f"{avg:.0f} строк", source="git_clone"),
    ]
    marks = int(todo + fixme + hack)
    strengths, weaknesses = [], []
    if density is not None and density <= 1:
        strengths.append("Низкая плотность TODO/FIXME")
    if largest <= 1000:
        strengths.append("Нет файлов-гигантов")
    if marks:
        weaknesses.append(f"{marks} пометок TODO/FIXME/HACK в коде")
    if oldest and oldest > 180:
        weaknesses.append(f"Старейший TODO висит {human_days(oldest)}")
    if largest > 3000:
        weaknesses.append(f"Файл на {int(largest)} строк сложно сопровождать")

    return _facts("ok", metrics, strengths, weaknesses)


# ─────────────────────────────── сборка ──────────────────────────────────────
def _facts(status: str, metrics: list, strengths: list, weaknesses: list,
           reason: str | None = None, coverage: float = 1.0) -> dict:
    return {"status": status, "metrics": metrics, "strengths": strengths,
            "weaknesses": weaknesses, "no_data_reason": reason, "signal_coverage": coverage}


def _no_data(reason: str, metrics: list | None = None) -> dict:
    return _facts("no_data", metrics or [], [], [], reason, 0.0)


EXTRACTORS = {
    "security": _security,
    "code_health": _code_health,
    "activity": _activity,
    "documentation": _documentation,
    "cicd": _cicd,
    "issues": _issues,
}


def category_facts(row: dict) -> dict[str, dict]:
    """Факты по всем шести категориям для одной строки выгрузки."""
    return {key: extractor(row) for key, extractor in EXTRACTORS.items()}


def collection_info(row: dict) -> dict:
    errors = []
    raw = text(row, "collection.errors")
    if raw:
        try:
            for e in json.loads(raw):
                errors.append({"category": e.get("category"), "source": e.get("source"),
                               "code": e.get("code"), "message": (e.get("message") or "")[:400]})
        except json.JSONDecodeError:
            pass
    return {
        "collected_at": text(row, "collection.collected_at"),
        "duration_ms": num(row, "collection.duration_ms"),
        "collector_version": text(row, "collection.collector_version"),
        "sources_used": {
            "git_clone": flag(row, "collection.sources_used.git_clone"),
            "platform_api": flag(row, "collection.sources_used.platform_api"),
            "platform_cli": flag(row, "collection.sources_used.platform_cli"),
            "appsec_api": flag(row, "collection.sources_used.appsec_api"),
        },
        "errors": errors,
    }
