#!/usr/bin/env bash
# Локальный запуск всего сервиса одной командой: бэкенд и интерфейс вместе.
# Docker не нужен. Остановка — Ctrl+C, оба процесса гасятся.
#
#   ./run.sh              запустить
#   ./run.sh --mock       без бэкенда, на снимке данных
#   ./run.sh --stop       остановить всё, что осталось от прошлого запуска

set -euo pipefail
cd "$(dirname "$0")"

API_PORT=${API_PORT:-8000}
WEB_PORT=${WEB_PORT:-5173}
MOCK=false

for arg in "$@"; do
  case "$arg" in
    --mock) MOCK=true ;;
    --stop)
      pkill -f "uvicorn main:app" 2>/dev/null && echo "Бэкенд остановлен" || echo "Бэкенд не запущен"
      pkill -f "vite" 2>/dev/null && echo "Интерфейс остановлен" || echo "Интерфейс не запущен"
      exit 0 ;;
    *) echo "Неизвестный аргумент: $arg"; exit 1 ;;
  esac
done

say() { printf "\033[36m→\033[0m %s\n" "$1"; }
fail() { printf "\033[31m✗\033[0m %s\n" "$1"; exit 1; }

# ─── проверки окружения ──────────────────────────────────────────────────────
command -v node >/dev/null || fail "Нужен Node.js 20+: https://nodejs.org"
if ! $MOCK; then
  command -v uv >/dev/null || fail "Нужен uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
  [ -f repo_health_report.csv ] || fail "Нет repo_health_report.csv — без него рейтинг будет пустым"
fi

# ─── порты ───────────────────────────────────────────────────────────────────
for port in $API_PORT $WEB_PORT; do
  if lsof -ti :$port >/dev/null 2>&1; then
    say "Порт $port занят, освобождаю"
    lsof -ti :$port | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
done

# ─── настройки ───────────────────────────────────────────────────────────────
[ -f .env ] || { cp .env.example .env; say "Создан .env из примера"; }
if ! grep -q "^SECRET_KEY=.\+" .env || grep -q "^SECRET_KEY=dev-secret-change-me" .env; then
  key=$(openssl rand -hex 32)
  if grep -q "^SECRET_KEY=" .env; then
    sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=$key|" .env 2>/dev/null || sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$key|" .env
  else
    echo "SECRET_KEY=$key" >> .env
  fi
  say "Сгенерирован SECRET_KEY"
fi

if $MOCK; then
  printf 'VITE_DATA_SOURCE=mock\nVITE_AUTH_SOURCE=mock\n' > frontend/.env
  say "Режим снимка данных: бэкенд не нужен"
else
  printf 'VITE_DATA_SOURCE=api\nVITE_AUTH_SOURCE=api\nVITE_API_BASE_URL=/api/v1\nVITE_PROXY_TARGET=http://localhost:%s\n' "$API_PORT" > frontend/.env
fi

# ─── зависимости ─────────────────────────────────────────────────────────────
if ! $MOCK && [ ! -d .venv ]; then say "Ставлю зависимости бэкенда"; uv sync -q; fi
if [ ! -d frontend/node_modules ]; then say "Ставлю зависимости интерфейса"; (cd frontend && npm ci --silent); fi

# ─── запуск ──────────────────────────────────────────────────────────────────
pids=()
cleanup() { printf "\nОстанавливаю…\n"; for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done; exit 0; }
trap cleanup INT TERM

if ! $MOCK; then
  say "Запускаю бэкенд на :$API_PORT"
  uv run uvicorn main:app --port "$API_PORT" >/tmp/repo-health-api.log 2>&1 &
  pids+=($!)

  printf "  читаю выгрузку"
  for _ in $(seq 1 60); do
    if curl -sf "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
      repos=$(curl -s "http://localhost:$API_PORT/health" | sed -n 's/.*"repos":\([0-9]*\).*/\1/p')
      printf "\r  витрина готова: %s репозиториев          \n" "$repos"
      break
    fi
    printf "."; sleep 1
  done
  curl -sf "http://localhost:$API_PORT/health" >/dev/null 2>&1 || {
    echo; echo "Бэкенд не поднялся, последние строки лога:"; tail -15 /tmp/repo-health-api.log; cleanup; }
fi

say "Запускаю интерфейс на :$WEB_PORT"
(cd frontend && npm run dev -- --port "$WEB_PORT" >/tmp/repo-health-web.log 2>&1) &
pids+=($!)
sleep 4

printf "\n\033[32m●\033[0m Сервис работает\n\n"
printf "   Интерфейс   http://localhost:%s\n" "$WEB_PORT"
$MOCK || printf "   API         http://localhost:%s/api/v1/stats\n" "$API_PORT"
$MOCK || printf "   Логи        /tmp/repo-health-api.log\n"
printf "\n   Остановить — Ctrl+C\n\n"

wait
