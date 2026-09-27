"""Настройки сервиса. Всё переопределяется переменными окружения."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Читает .env в переменные окружения.

    Уже заданные переменные не перезаписываются: то, что передали при запуске,
    всегда важнее файла.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(BASE_DIR / ".env")

# ─────────────────────────────── данные ──────────────────────────────────────
# Выгрузка сборщика. Витрина строится из неё в память: для рейтинга база не нужна.
CSV_PATH = Path(os.getenv("REPO_HEALTH_CSV", BASE_DIR / "repo_health_report.csv"))

# База нужна для того, что переживает перезапуск: сессии, история оценок, запуски анализа.
# По умолчанию SQLite-файл рядом с проектом; для стенда достаточно подменить строку.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'repo_health.db'}")

# ─────────────────────────────── расписание ──────────────────────────────────
SCHEDULE_CRON = os.getenv("REPO_HEALTH_SCHEDULE", "0 3 * * *")
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
# Писать историю оценок при каждом пересчёте (из неё строится динамика Score)
HISTORY_ON_REBUILD = os.getenv("HISTORY_ON_REBUILD", "true").lower() == "true"

# ─────────────────────────────── авторизация ─────────────────────────────────
# Приложение команды на oauth.yandex.ru. Client ID не секрет — он и так уходит в браузер.
YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "0e306eb0e70e42fca074ede029dc9e1f")
# Секрет включает более надёжный code-поток. Без него работает implicit:
# Яндекс возвращает токен прямо на фронт, сервис его проверяет.
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "")
YANDEX_AUTHORIZE_URL = os.getenv("YANDEX_AUTHORIZE_URL", "https://oauth.yandex.ru/authorize")
YANDEX_TOKEN_URL = os.getenv("YANDEX_TOKEN_URL", "https://oauth.yandex.ru/token")
YANDEX_INFO_URL = os.getenv("YANDEX_INFO_URL", "https://login.yandex.ru/info")

SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Демо-вход без приложения в Яндекс OAuth: нужен, пока client_id не выдан.
# На публичном стенде выключается переменной ALLOW_DEMO_AUTH=false.
ALLOW_DEMO_AUTH = os.getenv("ALLOW_DEMO_AUTH", "true").lower() == "true"

# Куда возвращать пользователя после согласия Я ID, если фронт не передал адрес
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Публичный адрес самого сервиса. Именно <PUBLIC_API_URL>/api/v1/auth/yandex/callback
# указывается как Redirect URI в приложении на oauth.yandex.ru.
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000")

# ─────────────────────────────── SourceCraft ─────────────────────────────────
SOURCECRAFT_API = os.getenv("SOURCECRAFT_API", "https://api.sourcecraft.tech")
# Список репозиториев пользователя. Проверено на живом API 27.09.2026:
#   /me/repos       → 200, репозитории пользователя
#   /user/repos     → 405, /users/me/repos → 404
#   /repos?mine=true → 200, но отдаёт больше записей, чем у пользователя есть,
#                      то есть параметр mine платформой не учитывается — в запасные
#                      адреса не берём, иначе в кабинет попадут чужие проекты.
SOURCECRAFT_REPOS_PATHS = os.getenv("SOURCECRAFT_REPOS_PATHS", "/me/repos").split(",")
# Адреса проверены на живом API 27.09.2026 скриптом tools/dump_my_repos.py.
# Профиль лежит на /user (на /me платформа отвечает 404).
SOURCECRAFT_PROFILE_PATH = os.getenv("SOURCECRAFT_PROFILE_PATH", "/user")
# Только адреса в области пользователя. Глобальные списки вроде /organizations
# сюда добавлять нельзя: сервис уйдёт собирать чужие репозитории.
# /me/orgs → 200; /me/organizations отвечает 405
SOURCECRAFT_ORG_PATHS = os.getenv("SOURCECRAFT_ORG_PATHS", "/me/orgs").split(",")
# /orgs/{slug}/repos → 200; /organizations/{slug}/repos отвечает 404
SOURCECRAFT_ORG_REPOS_TEMPLATES = os.getenv(
    "SOURCECRAFT_ORG_REPOS_TEMPLATES", "/orgs/{slug}/repos"
).split(",")

SOURCECRAFT_AUTH_HEADER = os.getenv("SOURCECRAFT_AUTH_HEADER", "Authorization")
# Запасной токен для стенда: используется, если у сессии своего токена нет.
# Работает только вместе с ALLOW_DEMO_AUTH — иначе все увидят репозитории его владельца.
SOURCECRAFT_FALLBACK_TOKEN = os.getenv("SOURCECRAFT_TOKEN", "")
SOURCECRAFT_AUTH_TEMPLATE = os.getenv("SOURCECRAFT_AUTH_TEMPLATE", "Bearer {t}")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))

# ─────────────────────────────── анализ по запросу ──────────────────────────
# Команда сборщика для одного репозитория: получает {full_path}, дописывает выгрузку.
# Пока не задана, анализ пересчитывает оценку по последнему снимку и честно пишет об этом.
COLLECTOR_COMMAND = os.getenv("COLLECTOR_COMMAND", "")
COLLECTOR_TIMEOUT = int(os.getenv("COLLECTOR_TIMEOUT", "900"))
ANALYSIS_WORKERS = int(os.getenv("ANALYSIS_WORKERS", "2"))

API_PREFIX = "/api/v1"
