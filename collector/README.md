# Сборщик данных SourceCraft

Собирает сырые сигналы по открытым репозиториям SourceCraft — документация, CI/CD,
AppSec, активность, issues, здоровье кода — и сводит их в `repo_health_report.csv`,
из которого бэкенд строит витрину рейтинга.

Отдельный Python-проект со своими зависимостями: бэкенд его не импортирует, а только
читает итоговый CSV.

## Как устроено

```
python -m collector collect-open ...   →  output/<owner>__<name>/latest.json   (по файлу на репозиторий)
scripts/export_csv.py                  →  repo_health_report.csv              (одна строка на репозиторий)
```

| Путь | Что там |
| --- | --- |
| `src/collector/` | код сборщика: обход платформы, клонирование, клиенты API, коллекторы по категориям |
| `config/endpoints.yaml` | реестр эндпоинтов платформы и AppSec, с пометками, что проверено |
| `schema/` | JSON Schema записи по репозиторию и пример |
| `scripts/export_csv.py` | выгрузка всех `latest.json` в CSV |
| `tests/` | тесты |

## Запуск

Все команды — из папки `collector/`.

```bash
cp .env.example .env          # вписать SOURCECRAFT_TOKEN (Personal Access Token)
uv sync --extra dev
uv run pytest
```

Пакет не устанавливается, поэтому модуль запускается с `PYTHONPATH=src`:

```bash
# один репозиторий
PYTHONPATH=src uv run python -m collector collect --owner 0003 --name sait1 \
    --clone-url https://git.sourcecraft.dev/0003/sait1.git

# обновление по кругу: сначала ещё не собранные, потом самые старые записи, не дольше 45 минут
PYTHONPATH=src uv run python -m collector collect-open --limit 100000 --oldest-first --max-minutes 45

# выгрузка в корень проекта, откуда её читает бэкенд
uv run --extra export python scripts/export_csv.py ../repo_health_report.csv
```

Полный обход (~27 700 репозиториев) занимает дни. Поэтому обновление идёт порциями:
`--oldest-first` упорядочивает репозитории по `collection.collected_at` из `latest.json`,
а `--max-minutes` останавливает запуск новых сборов, когда бюджет времени исчерпан.
Репозитории, до которых не дошла очередь, в ошибки не попадают — их заберёт следующий запуск.

Переменные окружения описаны в `.env.example`.

## Запуск через API бэкенда

Анализ из личного кабинета (`POST /api/v1/analyses`) умеет запускать сборщик для одного
репозитория. Бэкенд выполняет команду из `COLLECTOR_COMMAND`, подставив в неё `{full_path}`
(`owner/name`), и после её успешного завершения перечитывает `repo_health_report.csv`.
Для этого есть `scripts/collect_one.py`: он собирает репозиторий и **заменяет в CSV только
его строку** — остальные записи не трогает, файл подменяется целиком, без полузаписанного
состояния.

**1. Токен для сборщика** — в `collector/.env` (бэкенд его не читает, сборщик находит сам):

```bash
cp collector/.env.example collector/.env   # вписать SOURCECRAFT_TOKEN
```

**2. Команда сборщика** — в `.env` бэкенда в корне проекта (бэкенд запускается из корня):

```bash
COLLECTOR_COMMAND=uv run --project collector --extra export python collector/scripts/collect_one.py {full_path}
COLLECTOR_TIMEOUT=900
```

**3. Запуск анализа.** Поднять сервис из корня проекта (`./run.sh`), войти и
поставить анализ. На стенде можно взять демо-вход (работает при `ALLOW_DEMO_AUTH=true`):

```bash
# сессия: токен приходит в redirect-ссылке, параметр token=...
curl -si "http://localhost:8000/api/v1/auth/yandex/login?demo=1" | grep -i ^location

# поставить анализ; в ответе id
curl -s -X POST http://localhost:8000/api/v1/analyses \
     -H "Authorization: Bearer <токен_сессии>" -H "Content-Type: application/json" \
     -d '{"repo_full_path": "0003/sait1"}'

# статус и стадии: queue → clone → platform → appsec → score → recommendations
curl -s http://localhost:8000/api/v1/analyses/<id> -H "Authorization: Bearer <токен_сессии>"
```

Сбор одного репозитория занимает от нескольких секунд до нескольких минут у крупных.
Если сборщик упал или не уложился в `COLLECTOR_TIMEOUT`, анализ получает статус `failed`
с хвостом вывода сборщика в `error`. Пока `COLLECTOR_COMMAND` пустая, анализ пересчитывает
оценку по последнему снимку и прямо пишет об этом в стадиях.

Ту же команду можно запустить вручную, без бэкенда:

```bash
uv run --project collector --extra export python collector/scripts/collect_one.py 0003/sait1
```

AppSec при таком запуске пропускается: для него нужен `gitRepo`-идентификатор, а по
`owner/name` его не получить.
