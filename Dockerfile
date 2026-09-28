# Бэкенд: API, методика, планировщик.
# Сборщик данных в образ не входит — он запускается отдельно и обновляет CSV,
# который подключается томом (см. docker-compose.yml).
FROM python:3.12-slim AS base

# uv ставит зависимости по uv.lock — сборка воспроизводима
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Слой зависимостей кешируется отдельно от кода
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY main.py ./
COPY backend/ ./backend/
COPY scoring/ ./scoring/

# Выгрузка сборщика и база подключаются томами
ENV REPO_HEALTH_CSV=/data/repo_health_report.csv \
    DATABASE_URL=sqlite:////data/repo_health.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
