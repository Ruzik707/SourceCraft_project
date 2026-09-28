# Сборка и запуск

Документ позволяет стороннему специалисту поднять решение и воспроизвести
продемонстрированные результаты.

## Что потребуется

| Инструмент | Версия | Зачем |
| --- | --- | --- |
| Python | 3.12+ | бэкенд и сборщик |
| [uv](https://docs.astral.sh/uv/) | 0.4+ | зависимости Python и запуск |
| Node.js | 20+ (проверено на 22 и 23) | сборка интерфейса |
| Git | любая | получение кода и клонирование анализируемых репозиториев |

Отдельное оборудование не нужно: сервис работает как веб-приложение в браузере.

## Запуск одной командой

Простой путь — скрипт `run.sh`. Docker не нужен, достаточно Node и `uv`.

```bash
git clone ssh://ssh.sourcecraft.dev/lct-hackaton-2026/case-18-repo-health-score-team-31.git
cd case-18-repo-health-score-team-31
./run.sh
```

Скрипт проверит окружение, поставит зависимости при первом запуске, создаст `.env` и
сгенерирует `SECRET_KEY`, освободит занятые порты, дождётся готовности витрины и поднимет
интерфейс на http://localhost:5173. Остановка — Ctrl+C, оба процесса гасятся вместе.

Кроме Node и `uv` скрипт использует `curl`, `lsof` и `openssl` — на macOS и в большинстве
Linux они уже есть. Файл `frontend/.env` скрипт перезаписывает при каждом запуске под
выбранный режим. Логи: `/tmp/repo-health-api.log` и `/tmp/repo-health-web.log`.

```bash
./run.sh --mock     # только интерфейс на снимке данных, бэкенд не нужен
./run.sh --stop     # погасить процессы от прошлого запуска
API_PORT=9000 WEB_PORT=3000 ./run.sh    # другие порты
```

## Запуск в контейнерах

Тот же вид, в каком сервис разворачивается на стенде: бэкенд и интерфейс за nginx на
одном адресе.

```bash
git clone ssh://ssh.sourcecraft.dev/lct-hackaton-2026/case-18-repo-health-score-team-31.git
cd case-18-repo-health-score-team-31

cp .env.example .env        # задать SECRET_KEY
docker compose up -d --build
docker compose logs -f backend   # дождаться строки «Витрина готова»
```

Откройте http://localhost:8080.

**Если сборка падает на `TLS handshake timeout` или `failed to fetch anonymous token`** —
недоступен Docker Hub. Сначала просто повторите команду, это часто разовый сбой. Если не
помогает, соберите через зеркало Яндекса:

```bash
REGISTRY=cr.yandex/mirror docker compose up -d --build
```

## Режим разработки

Когда нужна горячая перезагрузка интерфейса, части запускаются по отдельности —
тогда Node и Python нужны на самой машине.

```bash
# бэкенд
uv sync
cp .env.example .env
uv run uvicorn main:app --port 8000

# интерфейс — во втором терминале
cd frontend
npm ci
cp .env.example .env
npm run dev
```

Откройте http://localhost:5173. Запросы к `/api` Vite проксирует на бэкенд.

При старте бэкенд читает выгрузку `repo_health_report.csv` (27 761 репозиторий),
прогоняет её через методику из `scoring/` и держит витрину в памяти. Расчёт занимает
около секунды, чтение файла — около пятнадцати. Готовность: `curl localhost:8000/health`.

## Состав решения

```
backend/     REST API, авторизация Я ID, очередь анализа, планировщик
scoring/     методика Repo Health Score: подготовка данных, нормализация, рекомендации
collector/   сборщик данных с платформы (отдельный проект со своими зависимостями)
frontend/    веб-интерфейс
tools/       вспомогательные скрипты
docs/        документация
main.py      точка входа FastAPI
repo_health_report.csv   выгрузка сборщика, из неё строится витрина
```

## Переменные окружения

### Бэкенд — `.env` в корне

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `REPO_HEALTH_CSV` | `repo_health_report.csv` | выгрузка, из которой строится витрина |
| `DATABASE_URL` | `sqlite:///repo_health.db` | сессии, история оценок, запуски анализа |
| `REPO_HEALTH_SCHEDULE` | `0 3 * * *` | расписание пересчёта |
| `SCHEDULER_ENABLED` | `true` | включение планировщика |
| `YANDEX_CLIENT_ID` | client_id приложения команды | вход через Я ID |
| `YANDEX_CLIENT_SECRET` | пусто | если задан, включается code-поток вместо implicit |
| `PUBLIC_API_URL` | `http://localhost:8000` | адрес сервиса; из него строится Redirect URI |
| `FRONTEND_URL` | `http://localhost:5173` | куда возвращать после входа |
| `SECRET_KEY` | `dev-secret-change-me` | подпись state и сессий — **на стенде обязательно свой** |
| `ALLOW_DEMO_AUTH` | `true` | вход без Яндекса по `?demo=1`; **на публичном стенде `false`** |
| `SOURCECRAFT_TOKEN` | пусто | запасной токен платформы для стенда |
| `COLLECTOR_COMMAND` | команда `collect_one.py` | чем собирать данные при анализе по запросу |

Полный список с пояснениями — в `.env.example`.

### Интерфейс — `frontend/.env`

| Переменная | Значения | Назначение |
| --- | --- | --- |
| `VITE_DATA_SOURCE` | `api` \| `mock` | боевой бэкенд или снимок данных в `public/mock` |
| `VITE_AUTH_SOURCE` | `api` \| `mock` | то же отдельно для личного кабинета |
| `VITE_API_BASE_URL` | `/api/v1` | базовый путь API |
| `VITE_PROXY_TARGET` | `http://localhost:8000` | куда Vite проксирует `/api` в разработке |

Переменные читаются при сборке: после изменения нужен перезапуск `npm run dev`.

### Сборщик — `collector/.env`

Токен платформы для сборщика хранится отдельно от бэкенда:

```bash
cp collector/.env.example collector/.env   # вписать SOURCECRAFT_TOKEN
```

## Режимы работы

**Боевой (по умолчанию).** Интерфейс ходит в API, API считает витрину из выгрузки.

**Автономный.** Если бэкенд не поднят, интерфейс работает на снимке:

```bash
./run.sh --mock
# или вручную: cd frontend && VITE_DATA_SOURCE=mock npm run dev
```

В этом режиме доступны рейтинг, страницы анализа, отчёты, сравнение и эмуляция
личного кабинета. Снимок пересобирается из выгрузки:

```bash
python3 tools/build_mock_data.py --csv repo_health_report.csv --out frontend/public/mock --limit 1500
```

## Вход через Я ID

Приложение команды на oauth.yandex.ru уже настроено, `client_id` подставлен по умолчанию.
Используется implicit-поток: Яндекс возвращает токен прямо на `/auth/callback` интерфейса,
сервис проверяет его и заводит сессию.

При переносе на другой адрес добавьте `<адрес интерфейса>/auth/callback` в Redirect URI
приложения. Если появится `YANDEX_CLIENT_SECRET`, сервис сам переключится на code-поток —
тогда в приложении нужно зарегистрировать ещё и
`<PUBLIC_API_URL>/api/v1/auth/yandex/callback`.

Для стенда и автотестов есть вход без Яндекса: `/api/v1/auth/yandex/login?demo=1`.
Работает только при `ALLOW_DEMO_AUTH=true`.

## Сбор данных

Сборщик — отдельный проект в `collector/` со своими зависимостями.

```bash
cd collector
uv sync --extra dev
uv run pytest                 # 18 тестов

# один репозиторий
PYTHONPATH=src uv run python -m collector collect --owner 0003 --name sait1 \
    --clone-url https://git.sourcecraft.dev/0003/sait1.git

# порционный обход: сначала несобранные, затем самые старые, не дольше 45 минут
PYTHONPATH=src uv run python -m collector collect-open --limit 100000 --oldest-first \
    --max-minutes 45 --concurrency 4

# выгрузка в CSV, который читает бэкенд
uv run --extra export python scripts/export_csv.py ../repo_health_report.csv
```

Полный обход каталога занимает дни, поэтому он идёт порциями: `--oldest-first`
упорядочивает по времени последнего сбора, `--max-minutes` ограничивает длительность
запуска. Подробнее — в `collector/README.md`.

## Периодический пересчёт

Планировщик внутри бэкенда пересобирает витрину по расписанию из
`REPO_HEALTH_SCHEDULE` и пишет точку в историю оценок. Ручной запуск:

```bash
curl -X POST http://localhost:8000/api/v1/admin/rebuild
```

## Развёртывание

Весь стенд поднимается одной командой: бэкенд и интерфейс за nginx.

```bash
cp .env.example .env      # заполнить SECRET_KEY, PUBLIC_API_URL, FRONTEND_URL
docker compose up -d --build
```

Интерфейс и API отдаются с одного адреса: nginx отдаёт статику и проксирует `/api/` на
бэкенд. Подробности, HTTPS, обновление данных и чек-лист перед показом — в
[`deploy.md`](./deploy.md).

## Проверка, что всё поднялось

```bash
curl -s localhost:8000/health
# {"status":"ok","repos":27761,...,"auth":"yandex_id"}

curl -s "localhost:8000/api/v1/repos?page_size=1" | head -c 200
curl -s localhost:8000/api/v1/stats
curl -s localhost:8000/api/v1/repos/userver/userver | head -c 200
```

В интерфейсе: рейтинг открывается на `/`, страница анализа — на
`/repo/userver/userver`, методика — на `/methodology`.

## Типичные проблемы

| Симптом | Причина и что делать |
| --- | --- |
| `Address already in use` на 8000 | уже запущен другой экземпляр: `./run.sh --stop` (при запуске через `./run.sh` порты освобождаются сами) |
| `./run.sh` пишет «Бэкенд не поднялся» | скрипт выводит хвост лога; полностью — `/tmp/repo-health-api.log` |
| В кабинете подобранная выборка вместо своих репозиториев | нет действующего токена платформы: вставьте личный токен в поле на странице «Мои репозитории» или задайте `SOURCECRAFT_TOKEN` |
| `ConnectTimeout` при обращении к платформе | нет доступа к `api.sourcecraft.tech`: проверьте сеть и VPN |
| `401` от платформы на все адреса | токен истёк или скопирован не полностью: выпустите новый в профиле SourceCraft |
| Интерфейс показывает демо-баннер | в `frontend/.env` стоит `VITE_DATA_SOURCE=mock` — например, после `./run.sh --mock`; обычный `./run.sh` вернёт `api` |
| `TLS handshake timeout` при сборке образов | недоступен Docker Hub: повторите команду или соберите через зеркало — `REGISTRY=cr.yandex/mirror docker compose up -d --build` |
| Вход через Я ID возвращает не туда | `PUBLIC_API_URL` и `FRONTEND_URL` в `.env` должны указывать на тот адрес, по которому вы открываете сервис |
| `Repo Health Score` не считается у части репозиториев | сборщик не смог получить рабочую копию: смотрите блок «Полнота данных» на странице анализа |
